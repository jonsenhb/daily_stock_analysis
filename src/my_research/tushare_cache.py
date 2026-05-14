# -*- coding: utf-8 -*-
"""
Tushare 研究冷缓存：Parquet 明细 + SQLite manifest。

- 不读取 .env，不依赖 get_config；根目录由调用方注入。
- 与 data_provider/tushare_fetcher 解耦：拉数逻辑通过 fetch_fn 注入。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sqlite3
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Mapping, Optional, Sequence, Tuple

import pandas as pd

from data_provider.base import _is_etf_code, _is_hk_market, is_bse_code, normalize_stock_code

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# 与 docs/my_research/tushare_data_plan.md「推荐字段」对齐的子集；可按 dataset 扩展。
DATASET_REQUIRED_FIELDS: Dict[str, Tuple[str, ...]] = {
    "trade_cal": ("cal_date", "is_open"),
    "stock_basic": ("ts_code", "symbol", "name"),
    "daily": ("ts_code", "trade_date", "close"),
    "daily_basic": ("ts_code", "trade_date", "close"),
    "index_daily": ("ts_code", "trade_date", "close"),
    "index_dailybasic": ("ts_code", "trade_date"),
    "top_list": ("trade_date", "ts_code"),
    "top_inst": ("trade_date", "ts_code", "exalter"),
    "stk_limit": ("trade_date", "ts_code"),
    "limit_list_d": ("trade_date", "ts_code"),
    "limit_step": ("trade_date", "ts_code"),
    "limit_list_ths": ("ts_code", "trade_date"),
    "limit_cpt_list": ("ts_code", "trade_date"),
    "moneyflow_ind_ths": ("trade_date", "ts_code"),
    "moneyflow_cnt_ths": ("trade_date", "ts_code"),
    "moneyflow_ths": ("trade_date", "ts_code"),
    "suspend_d": ("ts_code", "trade_date"),
}

# 保守默认：单接口文档与总表取调用方可覆盖；此处为未配置时的兜底。
DEFAULT_RATE_LIMIT_PER_MINUTE: Dict[str, int] = {
    "default": 120,
    "stock_basic": 50,
    "daily": 500,
    "daily_basic": 200,
    "index_daily": 200,
    "trade_cal": 200,
}


class CacheValidationError(ValueError):
    """缓存写入前 DataFrame 字段校验失败。"""


def normalize_trade_date(value: str) -> str:
    """Tushare 风格 YYYYMMDD。"""
    s = (value or "").strip()
    if not re.fullmatch(r"\d{8}", s):
        raise ValueError(f"trade_date 必须为 YYYYMMDD，收到: {value!r}")
    datetime.strptime(s, "%Y%m%d")
    return s


def _detect_exchange_hint(stock_code: str) -> Optional[str]:
    upper = (stock_code or "").strip().upper()
    if upper.startswith(("SH", "SS")) or upper.endswith((".SH", ".SS")):
        return "SH"
    if upper.startswith("SZ") or upper.endswith(".SZ"):
        return "SZ"
    if upper.startswith("BJ") or upper.endswith(".BJ"):
        return "BJ"
    return None


def normalize_ts_code(raw: str) -> str:
    """
    归一为 Tushare ts_code（A 股 / ETF / 北交所 / 港股）。

    美股 ticker 不支持，与 TushareFetcher 范围对齐。
    """
    raw_code = (raw or "").strip()
    if not raw_code:
        raise ValueError("ts_code 不能为空")

    if _is_hk_market(raw_code):
        if "." in raw_code:
            ts_code = raw_code.upper()
            if ts_code.endswith(".HK"):
                return ts_code
        digits = re.sub(r"\D", "", raw_code)
        if not digits:
            raise ValueError(f"无法识别港股代码: {raw!r}")
        code = digits[-5:].rjust(5, "0")
        return f"{code}.HK"

    if "." in raw_code:
        ts_code = raw_code.upper()
        if ts_code.endswith(".SS"):
            return f"{ts_code[:-3]}.SH"
        return ts_code

    code = normalize_stock_code(raw_code)
    hint = _detect_exchange_hint(raw_code)

    if hint == "SH":
        return f"{code}.SH"
    if hint == "SZ":
        return f"{code}.SZ"
    if hint == "BJ":
        return f"{code}.BJ"

    if _is_etf_code(code):
        if code.startswith(("51", "52", "56", "58")):
            return f"{code}.SH"
        return f"{code}.SZ"

    if is_bse_code(code):
        return f"{code}.BJ"

    if code.startswith(("600", "601", "603", "688")):
        return f"{code}.SH"
    if code.startswith(("000", "002", "300")):
        return f"{code}.SZ"

    if re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", raw_code.strip().upper()):
        raise ValueError(f"Tushare ts_code 不支持美股: {raw!r}")

    return f"{code}.SZ"


def _partition_id(partition: Mapping[str, Any]) -> str:
    items = sorted((str(k), str(v)) for k, v in partition.items())
    return "__".join(f"{k}={v}" for k, v in items)


def _param_hash(fetch_params: Optional[Mapping[str, Any]]) -> str:
    payload = json.dumps(fetch_params or {}, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _entry_key(dataset: str, partition: str, phash: str) -> str:
    return f"{dataset}:{partition}:{phash}"


@dataclass(frozen=True)
class _MetaRow:
    entry_key: str
    dataset: str
    partition_id: str
    param_hash: str
    parquet_relpath: str
    fetched_at: str
    row_count: int
    schema_version: int


class MinuteRateLimiter:
    """滑动窗口：每 60 秒最多 max_calls 次（可注入 clock 便于测试）。"""

    def __init__(self, max_calls: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        if max_calls < 1:
            raise ValueError("max_calls 至少为 1")
        self._max = max_calls
        self._clock = clock
        self._times: Deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            while self._times and now - self._times[0] >= 60.0:
                self._times.popleft()
            if len(self._times) >= self._max:
                wait = 60.0 - (now - self._times[0]) + 0.05
                if wait > 0:
                    time.sleep(wait)
                    now = self._clock()
                    while self._times and now - self._times[0] >= 60.0:
                        self._times.popleft()
            self._times.append(self._clock())


class TushareResearchCache:
    """
    Parquet + manifest.sqlite。

    Args:
        root: 缓存根目录（勿指向仓库 data/；测试用 tmp_path）。
        rate_limits: 每 dataset 每分钟最大调用次数；缺省用 DEFAULT_RATE_LIMIT_PER_MINUTE。
        pre_acquire: 若传入则替代内置限流（例如 fetch_fn 内已限流时可 lambda *_: None）。
    """

    def __init__(
        self,
        root: Path,
        *,
        rate_limits: Optional[Dict[str, int]] = None,
        pre_acquire: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._root = Path(root).resolve()
        self._parquet_root = self._root / "parquet"
        self._tmp_root = self._root / "tmp"
        self._manifest_path = self._root / "manifest.sqlite"
        self._parquet_root.mkdir(parents=True, exist_ok=True)
        self._tmp_root.mkdir(parents=True, exist_ok=True)
        self._limits = {**DEFAULT_RATE_LIMIT_PER_MINUTE, **(rate_limits or {})}
        self._limiters: Dict[str, MinuteRateLimiter] = {}
        self._limiter_lock = threading.Lock()
        self._pre_acquire = pre_acquire
        self._init_manifest()

    def _init_manifest(self) -> None:
        with sqlite3.connect(self._manifest_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entry (
                    entry_key TEXT PRIMARY KEY,
                    dataset TEXT NOT NULL,
                    partition_id TEXT NOT NULL,
                    param_hash TEXT NOT NULL,
                    parquet_relpath TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    schema_version INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uix_dataset_partition_param
                ON cache_entry (dataset, partition_id, param_hash)
                """
            )
            conn.commit()

    def _limiter_for(self, dataset: str) -> MinuteRateLimiter:
        cap = self._limits.get(dataset, self._limits.get("default", 120))
        with self._limiter_lock:
            if dataset not in self._limiters:
                self._limiters[dataset] = MinuteRateLimiter(cap)
            return self._limiters[dataset]

    def _acquire_rate(self, dataset: str) -> None:
        if self._pre_acquire is not None:
            self._pre_acquire(dataset)
            return
        self._limiter_for(dataset).acquire()

    @staticmethod
    def _validate_df(df: pd.DataFrame, required_columns: Sequence[str]) -> None:
        missing = [c for c in required_columns if c not in df.columns]
        if missing:
            raise CacheValidationError(f"返回 DataFrame 缺少列: {missing}；已有: {list(df.columns)}")

    def _read_meta(self, entry_key: str) -> Optional[_MetaRow]:
        with sqlite3.connect(self._manifest_path) as conn:
            row = conn.execute(
                "SELECT entry_key, dataset, partition_id, param_hash, parquet_relpath, "
                "fetched_at, row_count, schema_version FROM cache_entry WHERE entry_key = ?",
                (entry_key,),
            ).fetchone()
        if row is None:
            return None
        return _MetaRow(*row)

    def _upsert_meta(self, meta: _MetaRow) -> None:
        with sqlite3.connect(self._manifest_path) as conn:
            conn.execute(
                """
                INSERT INTO cache_entry (
                    entry_key, dataset, partition_id, param_hash, parquet_relpath,
                    fetched_at, row_count, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entry_key) DO UPDATE SET
                    parquet_relpath = excluded.parquet_relpath,
                    fetched_at = excluded.fetched_at,
                    row_count = excluded.row_count,
                    schema_version = excluded.schema_version
                """,
                (
                    meta.entry_key,
                    meta.dataset,
                    meta.partition_id,
                    meta.param_hash,
                    meta.parquet_relpath,
                    meta.fetched_at,
                    meta.row_count,
                    meta.schema_version,
                ),
            )
            conn.commit()

    def _delete_meta(self, entry_key: str) -> None:
        with sqlite3.connect(self._manifest_path) as conn:
            conn.execute("DELETE FROM cache_entry WHERE entry_key = ?", (entry_key,))
            conn.commit()

    def _parquet_abs_path(self, relpath: str) -> Path:
        return (self._root / relpath).resolve()

    def read_or_fetch(
        self,
        dataset: str,
        partition: Mapping[str, Any],
        fetch_fn: Callable[[], pd.DataFrame],
        *,
        fetch_params: Optional[Mapping[str, Any]] = None,
        required_columns: Optional[Sequence[str]] = None,
        force: bool = False,
    ) -> pd.DataFrame:
        """
        命中缓存则直接读 Parquet；否则调用 fetch_fn，校验后写入。

        Args:
            dataset: 与 Tushare api_name 一致的小写名，如 top_list、daily。
            partition: 用于路径与去重，如 {"trade_date": "20240510"}。
            fetch_fn: 无参 lambda，由调用方闭合 API 参数。
            fetch_params: 参与 param_hash 的额外参数（fields、limit_type 等）。
            required_columns: 默认使用 DATASET_REQUIRED_FIELDS[dataset]。
            force: True 时忽略已有缓存。
        """
        if not dataset:
            raise ValueError("dataset 不能为空")

        cols = required_columns
        if cols is None:
            cols = DATASET_REQUIRED_FIELDS.get(dataset)
            if cols is None:
                raise ValueError(f"未知 dataset {dataset!r}，请传入 required_columns 或在 DATASET_REQUIRED_FIELDS 中登记")

        partition_id = _partition_id(partition)
        phash = _param_hash(fetch_params)
        ekey = _entry_key(dataset, partition_id, phash)

        if not force:
            meta = self._read_meta(ekey)
            if meta is not None and meta.schema_version == SCHEMA_VERSION:
                path = self._parquet_abs_path(meta.parquet_relpath)
                if path.is_file():
                    return pd.read_parquet(path)

        self._acquire_rate(dataset)

        try:
            df = fetch_fn()
        except Exception:
            logger.exception("TushareResearchCache fetch_fn 失败: dataset=%s partition=%s", dataset, partition_id)
            raise

        if not isinstance(df, pd.DataFrame):
            raise TypeError(f"fetch_fn 必须返回 DataFrame，收到 {type(df)}")

        self._validate_df(df, cols)

        dataset_dir = self._parquet_root / dataset
        dataset_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{partition_id}__{phash}.parquet"
        final_rel = Path("parquet") / dataset / fname
        final_abs = self._root / final_rel
        tmp_name = f"{uuid.uuid4().hex}.parquet"
        tmp_abs = self._tmp_root / tmp_name

        try:
            df.to_parquet(tmp_abs, engine="pyarrow", index=False)
            final_abs.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp_abs), str(final_abs))
        except Exception:
            if tmp_abs.exists():
                tmp_abs.unlink(missing_ok=True)
            raise

        fetched_at = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        meta = _MetaRow(
            entry_key=ekey,
            dataset=dataset,
            partition_id=partition_id,
            param_hash=phash,
            parquet_relpath=str(final_rel).replace("\\", "/"),
            fetched_at=fetched_at,
            row_count=int(len(df)),
            schema_version=SCHEMA_VERSION,
        )

        if force:
            old = self._read_meta(ekey)
            if old and old.parquet_relpath != str(final_rel).replace("\\", "/"):
                old_abs = self._parquet_abs_path(old.parquet_relpath)
                if old_abs.is_file() and old_abs != final_abs:
                    try:
                        old_abs.unlink()
                    except OSError:
                        logger.warning("无法删除旧缓存文件: %s", old_abs)

        self._upsert_meta(meta)
        return df

    def invalidate(self, dataset: str, partition: Mapping[str, Any], fetch_params: Optional[Mapping[str, Any]] = None) -> None:
        """删除一条缓存记录及对应 Parquet。"""
        partition_id = _partition_id(partition)
        phash = _param_hash(fetch_params)
        ekey = _entry_key(dataset, partition_id, phash)
        meta = self._read_meta(ekey)
        if meta is None:
            return
        path = self._parquet_abs_path(meta.parquet_relpath)
        self._delete_meta(ekey)
        if path.is_file():
            path.unlink(missing_ok=True)

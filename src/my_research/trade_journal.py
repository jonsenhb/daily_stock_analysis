# -*- coding: utf-8 -*-
"""
个人交易日志 — 数据结构、CSV 读写、从 DataFrame 汇总摘要（研究/纪律复盘）。

- `amount`：成交数量（股/张等业务单位由上游统一，本模块不读账户、不推断资金）。
- 不实现自动下单、不读默认 data 目录路径、不提供具体买卖指令或收益承诺。
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

TRADE_JOURNAL_VERSION = "1.0.0"

# position_ratio 约定为 0–1；高于该值且未设止损则记风险标签
MATERIAL_EXPOSURE_WITHOUT_STOP = 0.2

TRADE_RECORD_CSV_COLUMNS: Tuple[str, ...] = (
    "date",
    "ts_code",
    "name",
    "side",
    "price",
    "amount",
    "position_ratio",
    "reason",
    "plan_id",
    "is_plan_trade",
    "market_score",
    "sector",
    "emotion_state",
    "stop_loss",
    "take_profit",
    "result_pnl",
    "result_pct",
    "review",
)


@dataclass(frozen=True)
class TradeRecord:
    """单笔交易记录（字段与 AGENTS / 任务契约一致）。"""

    date: date
    ts_code: str
    name: str
    side: str
    price: float
    amount: float
    position_ratio: Optional[float]
    reason: str
    plan_id: str
    is_plan_trade: bool
    market_score: Optional[int]
    sector: str
    emotion_state: str
    stop_loss: Optional[float]
    take_profit: Optional[float]
    result_pnl: Optional[float]
    result_pct: Optional[float]
    review: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return d


@dataclass(frozen=True)
class TradeJournalSummary:
    total_trades: int
    plan_trade_ratio: float
    impulse_trade_count: int
    avg_result_pct: float
    max_loss: float
    risk_violations: Tuple[str, ...]
    discipline_score: int
    notes: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "plan_trade_ratio": self.plan_trade_ratio,
            "impulse_trade_count": self.impulse_trade_count,
            "avg_result_pct": self.avg_result_pct,
            "max_loss": self.max_loss,
            "risk_violations": list(self.risk_violations),
            "discipline_score": self.discipline_score,
            "notes": self.notes,
        }


def _normalize_side(raw: Any) -> str:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        raise ValueError("side 不能为空")
    s = str(raw).strip().lower()
    if s in ("buy", "b", "买入"):
        return "buy"
    if s in ("sell", "s", "卖出"):
        return "sell"
    raise ValueError(f"无法解析 side: {raw!r}（需 buy/sell）")


def _parse_date(val: Any) -> date:
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if val is None or (isinstance(val, float) and pd.isna(val)):
        raise ValueError("date 不能为空")
    s = str(val).strip().replace("-", "")[:10]
    if len(s) == 8 and s.isdigit():
        return datetime.strptime(s, "%Y%m%d").date()
    try:
        return pd.to_datetime(val, errors="raise").date()
    except Exception as e:
        raise ValueError(f"无法解析 date: {val!r}") from e


def _parse_bool(val: Any) -> bool:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        raise ValueError("is_plan_trade 不能为空")
    if isinstance(val, np.bool_):
        return bool(val)
    if isinstance(val, np.integer):
        return bool(int(val))
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(int(val))
    s = str(val).strip().lower()
    if s in ("true", "1", "yes", "y", "是"):
        return True
    if s in ("false", "0", "no", "n", "否"):
        return False
    raise ValueError(f"无法解析 is_plan_trade: {val!r}")


def _optional_float(val: Any) -> Optional[float]:
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    return float(val)


def _optional_int(val: Any) -> Optional[int]:
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    return int(float(val))


def record_from_mapping(row: Mapping[str, Any]) -> TradeRecord:
    """从单行 dict / Series 构造 TradeRecord。"""
    return TradeRecord(
        date=_parse_date(row["date"]),
        ts_code=str(row["ts_code"]).strip(),
        name=str(row.get("name") or "").strip(),
        side=_normalize_side(row["side"]),
        price=float(row["price"]),
        amount=float(row["amount"]),
        position_ratio=_optional_float(row.get("position_ratio")),
        reason=str(row.get("reason") or "").strip(),
        plan_id=str(row.get("plan_id") or "").strip(),
        is_plan_trade=_parse_bool(row["is_plan_trade"]),
        market_score=_optional_int(row.get("market_score")),
        sector=str(row.get("sector") or "").strip(),
        emotion_state=str(row.get("emotion_state") or "").strip(),
        stop_loss=_optional_float(row.get("stop_loss")),
        take_profit=_optional_float(row.get("take_profit")),
        result_pnl=_optional_float(row.get("result_pnl")),
        result_pct=_optional_float(row.get("result_pct")),
        review=str(row.get("review") or "").strip(),
    )


def records_from_dataframe(df: pd.DataFrame) -> List[TradeRecord]:
    """从 DataFrame 解析记录；列名须覆盖 TradeRecord 字段。"""
    miss = set(TRADE_RECORD_CSV_COLUMNS) - set(df.columns)
    if miss:
        raise ValueError(f"DataFrame 缺少列: {sorted(miss)}")
    out: List[TradeRecord] = []
    for _, row in df.iterrows():
        out.append(record_from_mapping(row))
    return out


def _risk_codes_for_record(r: TradeRecord) -> List[str]:
    codes: List[str] = []
    if (
        r.position_ratio is not None
        and r.position_ratio >= MATERIAL_EXPOSURE_WITHOUT_STOP
        and r.stop_loss is None
    ):
        codes.append("no_stop_loss_on_material_exposure")
    emo = (r.emotion_state or "").strip()
    if any(k in emo for k in ("失控", "恐慌", "冲动")):
        codes.append("emotional_extreme_in_notes")
    if r.result_pct is not None and not (r.review or "").strip():
        codes.append("closed_without_review")
    return codes


def summary_from_records(records: Sequence[TradeRecord]) -> TradeJournalSummary:
    """确定性汇总；不含未来预测或买卖建议文案。"""
    n = len(records)
    if n == 0:
        return TradeJournalSummary(
            total_trades=0,
            plan_trade_ratio=0.0,
            impulse_trade_count=0,
            avg_result_pct=float("nan"),
            max_loss=float("nan"),
            risk_violations=tuple(),
            discipline_score=100,
            notes="无交易记录；统计与纪律分仅供参考。",
        )

    plan_n = sum(1 for r in records if r.is_plan_trade)
    impulse = sum(1 for r in records if not r.is_plan_trade)
    plan_ratio = plan_n / n

    pct_vals = [r.result_pct for r in records if r.result_pct is not None]
    avg_pct = float(sum(pct_vals) / len(pct_vals)) if pct_vals else float("nan")

    pnl_vals = [r.result_pnl for r in records if r.result_pnl is not None]
    max_loss_v = float(min(pnl_vals)) if pnl_vals else float("nan")

    all_codes: List[str] = []
    violation_fire_count = 0
    for r in records:
        rc = _risk_codes_for_record(r)
        if rc:
            violation_fire_count += len(rc)
        all_codes.extend(rc)
    unique_v = tuple(sorted(set(all_codes)))

    # 纪律分：样本量与冲动、风险标签次数挂钩；不表示盈亏能力
    raw = 100 - 4 * impulse - 5 * violation_fire_count
    disc = int(max(0, min(100, raw)))
    if n < 5:
        disc = min(disc, 85)

    notes = (
        f"基于 n={n} 条记录的描述性汇总；纪律分与风险标签为规则打分，"
        f"非投资建议；样本量较小时不确定性高。"
    )
    if n < 5:
        notes += " 当前样本少于 5，任何比例与分数外推需谨慎。"

    return TradeJournalSummary(
        total_trades=n,
        plan_trade_ratio=plan_ratio,
        impulse_trade_count=impulse,
        avg_result_pct=avg_pct,
        max_loss=max_loss_v,
        risk_violations=unique_v,
        discipline_score=disc,
        notes=notes,
    )


def summary_from_dataframe(df: pd.DataFrame) -> TradeJournalSummary:
    return summary_from_records(records_from_dataframe(df))


def write_trade_journal(records: Sequence[TradeRecord], path: Path) -> None:
    """写入 UTF-8 CSV；路径由调用方指定（测试请使用 tmp_path）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(TRADE_RECORD_CSV_COLUMNS), extrasaction="ignore")
        w.writeheader()
        for r in records:
            row = {k: "" for k in TRADE_RECORD_CSV_COLUMNS}
            row["date"] = r.date.isoformat()
            row["ts_code"] = r.ts_code
            row["name"] = r.name
            row["side"] = r.side
            row["price"] = r.price
            row["amount"] = r.amount
            row["position_ratio"] = "" if r.position_ratio is None else r.position_ratio
            row["reason"] = r.reason
            row["plan_id"] = r.plan_id
            row["is_plan_trade"] = r.is_plan_trade
            row["market_score"] = "" if r.market_score is None else r.market_score
            row["sector"] = r.sector
            row["emotion_state"] = r.emotion_state
            row["stop_loss"] = "" if r.stop_loss is None else r.stop_loss
            row["take_profit"] = "" if r.take_profit is None else r.take_profit
            row["result_pnl"] = "" if r.result_pnl is None else r.result_pnl
            row["result_pct"] = "" if r.result_pct is None else r.result_pct
            row["review"] = r.review
            w.writerow(row)


def read_trade_journal(path: Path) -> List[TradeRecord]:
    """从 UTF-8 CSV 读入；空文件返回空列表。"""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return []
    df = pd.read_csv(path, dtype=object)
    if df.empty:
        return []
    return records_from_dataframe(df)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手动 Tushare 连通性烟测：小样本请求，不写 data/、不读 .env。

用法:
  export TUSHARE_TOKEN=...
  python scripts_local/tushare_smoke.py
  python scripts_local/tushare_smoke.py --extended
  python scripts_local/tushare_smoke.py --date 20240510
  # 等价: --trade-date 20240510

环境变量:
  TUSHARE_TOKEN     必填（明文字符串，由 shell 注入）
  TUSHARE_SMOKE_TRADE_DATE  可选，覆盖默认锚定交易日 YYYYMMDD
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.my_research.tushare_research_client import TushareResearchClient  # noqa: E402

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore


def _shanghai_today() -> date:
    if ZoneInfo:
        return datetime.now(ZoneInfo("Asia/Shanghai")).date()
    return date.today()


def default_trade_anchor() -> str:
    """最近一个工作日（周一至周五），最多向前找 14 个自然日。"""
    d = _shanghai_today()
    for i in range(1, 15):
        c = d - timedelta(days=i)
        if c.weekday() < 5:
            return c.strftime("%Y%m%d")
    return (d - timedelta(days=3)).strftime("%Y%m%d")


def resolve_trade_date(cli: Optional[str]) -> str:
    env = (os.environ.get("TUSHARE_SMOKE_TRADE_DATE") or "").strip()
    if cli:
        s = cli.strip()
        if len(s) != 8 or not s.isdigit():
            raise SystemExit(f"Invalid --date/--trade-date (expect YYYYMMDD): {s!r}")
        datetime.strptime(s, "%Y%m%d")
        return s
    if env:
        if len(env) != 8 or not env.isdigit():
            raise SystemExit(f"Invalid TUSHARE_SMOKE_TRADE_DATE: {env!r}")
        datetime.strptime(env, "%Y%m%d")
        return env
    return default_trade_anchor()


def _short_range_end(anchor: str, days: int = 7) -> str:
    a = datetime.strptime(anchor, "%Y%m%d").date()
    b = a - timedelta(days=days)
    return b.strftime("%Y%m%d")


def _format_fields(cols: List[str], max_len: int = 220) -> str:
    s = ",".join(cols)
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _safe_err(exc: Exception) -> str:
    msg = str(exc).strip() or type(exc).__name__
    low = msg.lower()
    if "token" in low or "tushare_token" in low:
        return "<message redacted (may contain credential substring)>"
    return msg[:500]


@dataclass
class CaseResult:
    api_name: str
    ok: bool
    rows: int
    fields_repr: str
    elapsed_sec: float
    error_type: Optional[str] = None
    error_msg: Optional[str] = None


def _run_case(
    api_name: str,
    fn: Callable[[], object],
) -> CaseResult:
    t0 = time.perf_counter()
    try:
        df = fn()
        elapsed = time.perf_counter() - t0
        n = len(df)  # type: ignore[arg-type]
        cols = list(getattr(df, "columns", []))
        fields_repr = _format_fields([str(c) for c in cols])
        return CaseResult(api_name, True, int(n), fields_repr, elapsed, None, None)
    except Exception as exc:  # noqa: BLE001 — 烟测需吞掉单条错误
        elapsed = time.perf_counter() - t0
        return CaseResult(
            api_name,
            False,
            -1,
            "",
            elapsed,
            type(exc).__name__,
            _safe_err(exc),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Tushare manual smoke (small samples, no data/ writes).")
    parser.add_argument("--extended", action="store_true", help="Also run top_list / moneyflow / limit_* etc.")
    parser.add_argument(
        "--trade-date",
        "--date",
        dest="trade_date",
        default=None,
        metavar="YYYYMMDD",
        help="锚定交易日 YYYYMMDD（--date 同义；默认见 TUSHARE_SMOKE_TRADE_DATE 或自动）",
    )
    parser.add_argument("--stock-ts", default="600519.SH", help="Sample stock ts_code")
    parser.add_argument("--index-ts", default="000300.SH", help="Sample index ts_code")
    parser.add_argument("--verbose", action="store_true", help="DEBUG logging")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    logging.getLogger("src.my_research.tushare_research_client").setLevel(
        logging.DEBUG if args.verbose else logging.WARNING,
    )

    token = (os.environ.get("TUSHARE_TOKEN") or "").strip()
    if not token:
        print("ERROR: Set TUSHARE_TOKEN in the environment (not read from .env).", file=sys.stderr)
        return 2

    anchor = resolve_trade_date(args.trade_date)
    start_short = _short_range_end(anchor, days=7)
    stock_ts = args.stock_ts.strip()
    index_ts = args.index_ts.strip()

    client = TushareResearchClient(token=token)

    cases: List[Tuple[str, Callable[[], object]]] = [
        (
            "trade_cal",
            lambda: client.get_trade_calendar(
                exchange="SSE",
                start_date=start_short,
                end_date=anchor,
            ),
        ),
        (
            "stock_basic",
            lambda: client.get_stock_basic(ts_code=stock_ts, list_status="L"),
        ),
        (
            "daily",
            lambda: client.get_daily(ts_code=stock_ts, start_date=start_short, end_date=anchor),
        ),
        (
            "daily_basic",
            lambda: client.get_daily_basic(ts_code=stock_ts, start_date=start_short, end_date=anchor),
        ),
        (
            "index_daily",
            lambda: client.get_index_daily(ts_code=index_ts, start_date=start_short, end_date=anchor),
        ),
    ]

    if args.extended:
        cases.extend(
            [
                ("top_list", lambda: client.get_top_list(trade_date=anchor)),
                ("top_inst", lambda: client.get_top_inst(trade_date=anchor)),
                ("moneyflow_ind_ths", lambda: client.get_moneyflow_ind_ths(trade_date=anchor)),
                ("moneyflow_cnt_ths", lambda: client.get_moneyflow_cnt_ths(trade_date=anchor)),
                ("moneyflow_ths", lambda: client.get_moneyflow_ths(trade_date=anchor)),
                ("limit_list_d", lambda: client.get_limit_list(trade_date=anchor, limit_type="U")),
                ("limit_list_d_Z", lambda: client.get_limit_list(trade_date=anchor, limit_type="Z")),
                ("limit_step", lambda: client.get_limit_step(trade_date=anchor)),
                ("limit_list_ths", lambda: client.get_limit_list_ths(trade_date=anchor, limit_type="涨停池")),
                ("limit_cpt_list", lambda: client.get_limit_cpt_list(trade_date=anchor)),
                ("stk_limit", lambda: client.get_stk_limit(trade_date=anchor)),
                ("suspend_d", lambda: client.get_suspend_d(trade_date=anchor)),
            ]
        )

    print(f"tushare_smoke anchor_trade_date={anchor} extended={args.extended} stock={stock_ts} index={index_ts}")
    print("(empty result is OK for some dates; API errors are reported per case)\n")

    results: List[CaseResult] = []
    for api_name, fn in cases:
        # log logical name matching DEFAULT_FIELDS keys where applicable
        r = _run_case(api_name, fn)
        results.append(r)
        if r.ok:
            flag = "ok"
            if r.rows == 0:
                flag = "ok (empty)"
            line = (
                f"[{flag}] api={r.api_name} rows={r.rows} "
                f"elapsed_ms={r.elapsed_sec * 1000:.1f} fields=({r.fields_repr})"
            )
        else:
            line = (
                f"[FAIL] api={r.api_name} error_type={r.error_type} "
                f"elapsed_ms={r.elapsed_sec * 1000:.1f} msg={r.error_msg}"
            )
        print(line)

    failed = sum(1 for r in results if not r.ok)
    ok_n = sum(1 for r in results if r.ok)
    print(f"\nsummary: ok={ok_n} failed={failed} total={len(results)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

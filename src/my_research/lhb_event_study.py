# -*- coding: utf-8 -*-
"""
LHB 事件研究 — 席位上榜后远期收益与超额收益（研究用）。

- 无 Tushare、无 LLM、不写本地 data 目录；输入输出均为 pandas DataFrame。
- 锚点：事件日 T = 龙虎榜 trade_date，收益以当日收盘价 close[T] 为起点；
  forward_return_kd = close[T+k]/close[T] - 1（k 为向后第 k 个交易日，非自然日）。
- 超额收益：forward_return_3d 股票 − 同持有期基准收益；基准收盘价在 T 与 T+3 **与个股同一贸易日**上取值。
- 基准优先级：提供了 sector_df 时优先按 (ts_code, trade_date) 使用 benchmark_close；
  否则若提供 market_gate_df 且含 index_close，则按 trade_date 使用全市场统一基准；
  均不可用则 excess_return_3d 为 NaN。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

LHB_EVENT_REQUIRED = frozenset({"trade_date", "ts_code", "seat_name", "side", "net_buy"})
DAILY_REQUIRED = frozenset({"ts_code", "trade_date", "close"})
SECTOR_BENCH_REQUIRED = frozenset({"ts_code", "trade_date", "benchmark_close"})
MARKET_BENCH_REQUIRED = frozenset({"trade_date", "index_close"})

LHB_EVENT_STUDY_VERSION = "1.0.0"


def _norm_trade_date(value: Any) -> str:
    if pd.isna(value):
        return ""
    s = str(value).strip()
    if not s:
        return ""
    return s.replace("-", "")[:8]


def _validate_columns(df: pd.DataFrame, required: frozenset, name: str) -> None:
    miss = required - set(df.columns)
    if miss:
        raise ValueError(f"{name} 缺少列: {sorted(miss)}")


def _build_stock_series(daily: pd.DataFrame) -> Dict[str, Tuple[List[str], List[float]]]:
    out: Dict[str, Tuple[List[str], List[float]]] = {}
    for ts_code, g in daily.groupby("ts_code", sort=False):
        g = g.copy()
        g["_td"] = g["trade_date"].map(_norm_trade_date)
        g = g[g["_td"].astype(bool)].sort_values("_td")
        dates = g["_td"].tolist()
        closes = pd.to_numeric(g["close"], errors="coerce").tolist()
        out[str(ts_code)] = (dates, closes)
    return out


def _bench_sector_map(sector_df: pd.DataFrame) -> Dict[Tuple[str, str], float]:
    m: Dict[Tuple[str, str], float] = {}
    for _, row in sector_df.iterrows():
        td = _norm_trade_date(row["trade_date"])
        ts = str(row["ts_code"])
        v = pd.to_numeric(row["benchmark_close"], errors="coerce")
        if td and ts and pd.notna(v):
            m[(ts, td)] = float(v)
    return m


def _bench_market_map(market_df: pd.DataFrame) -> Dict[str, float]:
    m: Dict[str, float] = {}
    for _, row in market_df.iterrows():
        td = _norm_trade_date(row["trade_date"])
        v = pd.to_numeric(row["index_close"], errors="coerce")
        if td and pd.notna(v):
            m[td] = float(v)
    return m


def _forward_simple(
    closes: List[float], i: int, k: int
) -> Tuple[float, Optional[str]]:
    if i + k >= len(closes):
        return float("nan"), f"missing_forward_{k}d"
    a, b = closes[i], closes[i + k]
    if pd.isna(a) or pd.isna(b) or a == 0:
        return float("nan"), "invalid_close_on_path"
    return float(b / a - 1.0), None


def _bench_pair_return(
    ts_code: str,
    d0: str,
    d_k: str,
    sector_map: Optional[Dict[Tuple[str, str], float]],
    market_map: Optional[Dict[str, float]],
    *,
    sector_first: bool,
) -> Tuple[Optional[float], List[str]]:
    warnings: List[str] = []

    def from_sector() -> Optional[float]:
        if not sector_map:
            return None
        p0 = sector_map.get((ts_code, d0))
        pk = sector_map.get((ts_code, d_k))
        if p0 is None or pk is None or p0 == 0:
            return None
        return float(pk / p0 - 1.0)

    def from_market() -> Optional[float]:
        if not market_map:
            return None
        p0 = market_map.get(d0)
        pk = market_map.get(d_k)
        if p0 is None or pk is None or p0 == 0:
            return None
        return float(pk / p0 - 1.0)

    if sector_first and sector_map:
        r = from_sector()
        if r is not None:
            return r, warnings
        warnings.append("benchmark_sector_incomplete")

    if market_map:
        r = from_market()
        if r is not None:
            return r, warnings
        warnings.append("benchmark_market_incomplete")

    if not sector_first and sector_map:
        r = from_sector()
        if r is not None:
            return r, warnings
        warnings.append("benchmark_sector_incomplete")

    warnings.append("no_benchmark_for_excess")
    return None, warnings


def compute_lhb_forward_returns(
    lhb_events: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    sector_df: Optional[pd.DataFrame] = None,
    market_gate_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    计算龙虎榜席位事件的远期收益与（可选）超额收益。

    Parameters
    ----------
    lhb_events:
        须含 trade_date, ts_code, seat_name, side, net_buy。
    daily:
        须含 ts_code, trade_date, close；按股票分组后 trade_date 升序取第 k 根为 T+k。
    sector_df:
        可选；若提供须含 ts_code, trade_date, benchmark_close。优先用于 excess 基准。
    market_gate_df:
        可选；若提供须含 trade_date, index_close。在 sector 不可用或不提供时用于 excess。
    """
    if lhb_events.empty:
        return _empty_result_frame()

    _validate_columns(lhb_events, LHB_EVENT_REQUIRED, "lhb_events")
    _validate_columns(daily, DAILY_REQUIRED, "daily")

    sector_map: Optional[Dict[Tuple[str, str], float]] = None
    if sector_df is not None and not sector_df.empty:
        _validate_columns(sector_df, SECTOR_BENCH_REQUIRED, "sector_df")
        sector_map = _bench_sector_map(sector_df)

    market_map: Optional[Dict[str, float]] = None
    if market_gate_df is not None and not market_gate_df.empty:
        _validate_columns(market_gate_df, MARKET_BENCH_REQUIRED, "market_gate_df")
        market_map = _bench_market_map(market_gate_df)

    stock_series = _build_stock_series(daily)

    rows: List[Dict[str, Any]] = []
    events = lhb_events.reset_index(drop=True)

    for idx in range(len(events)):
        erow = events.iloc[idx]
        ts_code = str(erow["ts_code"])
        td = _norm_trade_date(erow["trade_date"])
        seat_name = str(erow["seat_name"])
        side = erow["side"]
        net_buy = erow["net_buy"]

        event_id = f"{td}|{ts_code}|{seat_name}|{side}|{idx}"

        w: List[str] = []
        fr1 = fr3 = fr5 = float("nan")
        excess = float("nan")

        if not td:
            w.append("invalid_trade_date")
            rows.append(
                _result_row(
                    event_id,
                    ts_code,
                    td,
                    seat_name,
                    side,
                    net_buy,
                    fr1,
                    fr3,
                    fr5,
                    excess,
                    False,
                    w,
                )
            )
            continue

        if ts_code not in stock_series:
            w.append("missing_stock_daily")
            rows.append(
                _result_row(
                    event_id,
                    ts_code,
                    td,
                    seat_name,
                    side,
                    net_buy,
                    fr1,
                    fr3,
                    fr5,
                    excess,
                    False,
                    w,
                )
            )
            continue

        dates, closes = stock_series[ts_code]
        try:
            i = dates.index(td)
        except ValueError:
            w.append("event_date_not_in_daily")
            rows.append(
                _result_row(
                    event_id,
                    ts_code,
                    td,
                    seat_name,
                    side,
                    net_buy,
                    fr1,
                    fr3,
                    fr5,
                    excess,
                    False,
                    w,
                )
            )
            continue

        if pd.isna(closes[i]) or closes[i] == 0:
            w.append("missing_close_on_event_day")
            rows.append(
                _result_row(
                    event_id,
                    ts_code,
                    td,
                    seat_name,
                    side,
                    net_buy,
                    fr1,
                    fr3,
                    fr5,
                    excess,
                    False,
                    w,
                )
            )
            continue

        fr1, w1 = _forward_simple(closes, i, 1)
        if w1:
            w.append(w1)
        fr3, w3 = _forward_simple(closes, i, 3)
        if w3:
            w.append(w3)
        fr5, w5 = _forward_simple(closes, i, 5)
        if w5:
            w.append(w5)

        sample_valid = bool(pd.notna(fr1) and pd.notna(fr3) and pd.notna(fr5))

        if pd.notna(fr3) and i + 3 < len(dates):
            d_k = dates[i + 3]
            br, bw = _bench_pair_return(
                ts_code,
                td,
                d_k,
                sector_map,
                market_map,
                sector_first=True,
            )
            w.extend(bw)
            if br is not None:
                excess = float(fr3 - br)
        elif pd.notna(fr3) and (sector_map or market_map):
            w.append("no_benchmark_for_excess")

        rows.append(
            _result_row(
                event_id,
                ts_code,
                td,
                seat_name,
                side,
                net_buy,
                fr1,
                fr3,
                fr5,
                excess,
                sample_valid,
                w,
            )
        )

    return pd.DataFrame(rows)


def _empty_result_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id",
            "ts_code",
            "trade_date",
            "seat_name",
            "side",
            "net_buy",
            "forward_return_1d",
            "forward_return_3d",
            "forward_return_5d",
            "excess_return_3d",
            "sample_valid",
            "warnings",
        ]
    )


def _result_row(
    event_id: str,
    ts_code: str,
    trade_date: str,
    seat_name: str,
    side: Any,
    net_buy: Any,
    fr1: float,
    fr3: float,
    fr5: float,
    excess: float,
    sample_valid: bool,
    warnings: List[str],
) -> Dict[str, Any]:
    return {
        "event_id": event_id,
        "ts_code": ts_code,
        "trade_date": trade_date,
        "seat_name": seat_name,
        "side": side,
        "net_buy": net_buy,
        "forward_return_1d": fr1,
        "forward_return_3d": fr3,
        "forward_return_5d": fr5,
        "excess_return_3d": excess,
        "sample_valid": sample_valid,
        "warnings": warnings,
    }

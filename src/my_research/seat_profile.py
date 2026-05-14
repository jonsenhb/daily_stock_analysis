# -*- coding: utf-8 -*-
"""
席位画像 — 基于 `lhb_event_study` 产出的事件级 DataFrame 做描述性聚合。

- 研究/复盘用；不构成交易建议，不输出「必涨/必跌」类结论。
- 无网络、无 Tushare、不写 data/。
"""

from __future__ import annotations

from typing import Any, List, Literal, Optional

import numpy as np
import pandas as pd

EVENT_STUDY_REQUIRED = frozenset(
    {
        "seat_name",
        "side",
        "trade_date",
        "forward_return_1d",
        "forward_return_3d",
        "forward_return_5d",
    }
)

SECTOR_COLUMN_CANDIDATES = ("sector", "industry")

ConfidenceLevel = Literal["insufficient", "low", "medium", "high"]

SEAT_PROFILE_VERSION = "1.0.0"


def _validate_columns(df: pd.DataFrame) -> None:
    miss = EVENT_STUDY_REQUIRED - set(df.columns)
    if miss:
        raise ValueError(f"event_study_df 缺少列: {sorted(miss)}")


def _side_bucket(side: Any) -> str:
    if pd.isna(side):
        return "unknown"
    if isinstance(side, (int, np.integer)):
        if int(side) == 0:
            return "buy"
        if int(side) == 1:
            return "sell"
    if isinstance(side, float) and not np.isnan(side):
        if int(side) == 0:
            return "buy"
        if int(side) == 1:
            return "sell"
    sl = str(side).strip().lower()
    if sl in ("0", "buy", "b"):
        return "buy"
    if sl in ("1", "sell", "s"):
        return "sell"
    return "unknown"


def _series_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([False] * len(df), index=df.index)
    return df[col].apply(lambda x: bool(x) if not pd.isna(x) else False)


def _sector_column_name(df: pd.DataFrame) -> Optional[str]:
    for c in SECTOR_COLUMN_CANDIDATES:
        if c in df.columns:
            return c
    return None


def _max_drawdown_proxy(fr3_series: pd.Series) -> float:
    """事件序列上的简单累积净值最大回撤（峰值到谷底相对峰值，非负）。"""
    vals = pd.to_numeric(fr3_series, errors="coerce").dropna().to_numpy()
    if len(vals) < 2:
        return float("nan")
    equity = np.cumprod(1.0 + vals)
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak <= 0:
            continue
        dd = (peak - e) / peak
        max_dd = max(max_dd, dd)
    return float(max_dd)


def _confidence_raw(effective_n: int, min_high: int) -> ConfidenceLevel:
    if effective_n <= 0:
        return "insufficient"
    if effective_n < 10:
        return "low"
    if effective_n < min_high:
        return "medium"
    return "high"


def _downgrade_confidence(level: ConfidenceLevel) -> ConfidenceLevel:
    order = {"high": "medium", "medium": "low", "low": "low", "insufficient": "insufficient"}
    return order[level]  # type: ignore[return-value]


def _apply_valid_ratio_downgrade(
    level: ConfidenceLevel, total_events: int, effective_n: int
) -> ConfidenceLevel:
    if total_events <= 0 or level == "insufficient":
        return level
    ratio = effective_n / total_events
    if ratio < 0.3:
        return _downgrade_confidence(level)
    return level


def _one_seat_profile(
    g: pd.DataFrame,
    *,
    min_events_for_full_confidence: int,
    recent_n: int,
    one_day_tour_fr1_pct: float,
    one_day_tour_fr3_max: float,
) -> dict:
    seat = str(g["seat_name"].iloc[0])
    total_events = int(len(g))

    buckets = g["side"].map(_side_bucket)
    buy_events = int((buckets == "buy").sum())
    sell_events = int((buckets == "sell").sum())

    if "sample_valid" in g.columns:
        valid_mask = _series_col(g, "sample_valid")
    else:
        valid_mask = pd.Series([False] * len(g), index=g.index)

    effective_n = int(valid_mask.sum())

    g_valid = g.loc[valid_mask]
    fr1 = pd.to_numeric(g_valid["forward_return_1d"], errors="coerce")
    fr3 = pd.to_numeric(g_valid["forward_return_3d"], errors="coerce")
    fr5 = pd.to_numeric(g_valid["forward_return_5d"], errors="coerce")

    avg_fr1 = float(fr1.mean()) if fr1.notna().any() else float("nan")
    avg_fr3 = float(fr3.mean()) if fr3.notna().any() else float("nan")
    avg_fr5 = float(fr5.mean()) if fr5.notna().any() else float("nan")

    fr3_all_valid = fr3.dropna()
    win_rate_3d = (
        float((fr3_all_valid > 0).mean()) if len(fr3_all_valid) > 0 else float("nan")
    )

    sort_cols = ["trade_date"]
    if "event_id" in g.columns:
        sort_cols.append("event_id")
    g_sorted = g.sort_values(sort_cols, kind="mergesort")
    g_dd = g_sorted[valid_mask]
    g_dd = g_dd[pd.to_numeric(g_dd["forward_return_3d"], errors="coerce").notna()]
    max_dd = _max_drawdown_proxy(g_dd["forward_return_3d"])

    tail = g_sorted.tail(max(1, recent_n))
    recent_performance = float(
        pd.to_numeric(tail["forward_return_3d"], errors="coerce").mean()
    )

    scol = _sector_column_name(g)
    preferred_sectors: List[str] = []
    if scol is not None:
        sraw = g[scol].dropna().astype(str).str.strip()
        sraw = sraw[sraw != ""]
        if len(sraw) > 0:
            preferred_sectors = sraw.value_counts().head(3).index.tolist()

    f1 = pd.to_numeric(g["forward_return_1d"], errors="coerce")
    f3 = pd.to_numeric(g["forward_return_3d"], errors="coerce")
    mask_dd = f1.notna() & f3.notna()
    if int(mask_dd.sum()) == 0:
        tour_risk = float("nan")
    else:
        tour_hit = (f1 > one_day_tour_fr1_pct) & (f3 <= one_day_tour_fr3_max)
        tour_risk = float(tour_hit[mask_dd].mean())

    level = _confidence_raw(effective_n, min_events_for_full_confidence)
    level = _apply_valid_ratio_downgrade(level, total_events, effective_n)

    return {
        "seat_name": seat,
        "total_events": total_events,
        "buy_events": buy_events,
        "sell_events": sell_events,
        "avg_forward_return_1d": avg_fr1,
        "avg_forward_return_3d": avg_fr3,
        "avg_forward_return_5d": avg_fr5,
        "win_rate_3d": win_rate_3d,
        "max_drawdown_proxy": max_dd,
        "recent_performance": recent_performance,
        "preferred_sectors": preferred_sectors,
        "one_day_tour_risk": tour_risk,
        "confidence_level": level,
    }


def build_seat_profiles(
    event_study_df: pd.DataFrame,
    *,
    min_events_for_full_confidence: int = 30,
    recent_n: int = 10,
    one_day_tour_fr1_pct: float = 0.03,
    one_day_tour_fr3_max: float = 0.0,
) -> pd.DataFrame:
    """
    由 `compute_lhb_forward_returns` 等产出的 **事件级** DataFrame 汇总每个 `seat_name`。

    Parameters
    ----------
    event_study_df :
        须含 seat_name, side, trade_date, forward_return_1d/3d/5d。
        可选：`sample_valid`（缺省则视为全 False）；`sector` / `industry`（用于 preferred_sectors）。
    min_events_for_full_confidence :
        预留与文档一致；`high` 档要求 effective_n（sample_valid 为 True 条数）≥ 该值（默认 30）。
    recent_n :
        recent_performance 取按 trade_date 排序后的最近 N 条事件的 forward_return_3d 均值。
    one_day_tour_fr1_pct / one_day_tour_fr3_max :
        一日游**嫌疑**占比：同时满足 fr1 > 前者且 fr3 ≤ 后者（分母为 fr1、fr3 均非 NaN 的行）。

    Notes
    -----
    - `max_drawdown_proxy` 仅基于事件级 forward_return_3d 连乘净值，**不是**真实持仓路径。
    - 输出为描述性统计；`confidence_level` 仅反映样本量与有效率，**不**表示涨跌确定性。
    """
    if event_study_df.empty:
        return _empty_profile_frame()

    _validate_columns(event_study_df)

    rows: List[dict] = []
    for _, g in event_study_df.groupby("seat_name", sort=True):
        rows.append(
            _one_seat_profile(
                g,
                min_events_for_full_confidence=min_events_for_full_confidence,
                recent_n=recent_n,
                one_day_tour_fr1_pct=one_day_tour_fr1_pct,
                one_day_tour_fr3_max=one_day_tour_fr3_max,
            )
        )

    return pd.DataFrame(rows)


def _empty_profile_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "seat_name",
            "total_events",
            "buy_events",
            "sell_events",
            "avg_forward_return_1d",
            "avg_forward_return_3d",
            "avg_forward_return_5d",
            "win_rate_3d",
            "max_drawdown_proxy",
            "recent_performance",
            "preferred_sectors",
            "one_day_tour_risk",
            "confidence_level",
        ]
    )

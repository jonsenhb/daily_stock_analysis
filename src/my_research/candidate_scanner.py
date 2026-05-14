# -*- coding: utf-8 -*-
"""
Candidate Scanner v1 — 确定性观察池扫描（研究用）。

- 不接 LLM、不请求 Tushare；输入为 pandas DataFrame。
- trade_allowed 恒为 False，后续由 market_gate 与人工决定。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

import pandas as pd

# Tushare daily_basic：circ_mv 常为「万元」量级；20000 万元 ≈ 2 亿人民币
DEFAULT_MIN_TURNOVER_RATE = 0.005
DEFAULT_MIN_CIRC_MV_WAN = 20000.0

ALLOWED_MARKETS = frozenset({"主板", "创业板", "科创板"})

SCANNER_VERSION = "1.0.0"


@dataclass(frozen=True)
class CandidateResult:
    ts_code: str
    name: str
    board: str
    sector: str
    score: float
    watch_allowed: bool
    trade_allowed: bool
    risk_tags: Tuple[str, ...]
    trigger_condition: str
    invalid_condition: str
    evidence: Tuple[str, ...]


def _is_st_name(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return False
    if "*ST" in n:
        return True
    if n.startswith("ST"):
        return True
    return False


def _is_delisting_risk_name(name: str) -> bool:
    return "退" in (name or "")


def _market_to_board(market: str) -> str:
    m = (market or "").strip()
    if m == "主板":
        return "main"
    if m == "创业板":
        return "cyb"
    if m == "科创板":
        return "kcb"
    return "other"


def _require_columns(df: pd.DataFrame, required: Sequence[str], *, name: str) -> None:
    miss = [c for c in required if c not in df.columns]
    if miss:
        raise ValueError(f"{name}: missing columns {miss}")


def _suspended_codes(suspend: Optional[pd.DataFrame], anchor: str) -> FrozenSet[str]:
    if suspend is None or suspend.empty:
        return frozenset()
    _require_columns(suspend, ("ts_code", "trade_date", "suspend_type"), name="suspend")
    s = suspend[
        (suspend["trade_date"].astype(str) == str(anchor)) & (suspend["suspend_type"].astype(str) == "S")
    ]
    return frozenset(s["ts_code"].astype(str).tolist())


def scan_candidates(
    *,
    anchor_trade_date: str,
    stock_basic: pd.DataFrame,
    daily: pd.DataFrame,
    daily_basic: pd.DataFrame,
    stk_limit: pd.DataFrame,
    suspend: Optional[pd.DataFrame] = None,
    hot_sectors: Optional[FrozenSet[str]] = None,
    min_turnover_rate: float = DEFAULT_MIN_TURNOVER_RATE,
    min_circ_mv_wan: float = DEFAULT_MIN_CIRC_MV_WAN,
) -> List[CandidateResult]:
    """
    基于单日截面 DataFrame 产出观察池候选（仅通过硬过滤的行）。

    Args:
        anchor_trade_date: YYYYMMDD，与各表 trade_date 对齐。
        hot_sectors: 强势行业/板块名集合（可选，与 stock_basic.industry 精确匹配）。
        min_turnover_rate: 最低换手率（与 Tushare daily_basic 口径一致，如 0.01=1%）。
        min_circ_mv_wan: 最低流通市值（万元）。
    """
    anchor = str(anchor_trade_date).strip()
    _require_columns(
        stock_basic,
        ("ts_code", "name", "market", "industry", "list_status"),
        name="stock_basic",
    )
    _require_columns(daily, ("ts_code", "trade_date", "close", "pct_chg", "amount"), name="daily")
    _require_columns(
        daily_basic,
        ("ts_code", "trade_date", "turnover_rate", "circ_mv"),
        name="daily_basic",
    )
    _require_columns(stk_limit, ("ts_code", "trade_date", "up_limit", "down_limit"), name="stk_limit")

    hot = hot_sectors or frozenset()
    suspended = _suspended_codes(suspend, anchor)

    sb = stock_basic.copy()
    sb["ts_code"] = sb["ts_code"].astype(str)
    sb = sb[sb["list_status"].astype(str) == "L"]
    if "delist_date" in sb.columns:
        sb = sb[sb["delist_date"].isna() | (sb["delist_date"].astype(str).str.strip() == "")]

    d = daily[daily["trade_date"].astype(str) == anchor].copy()
    db = daily_basic[daily_basic["trade_date"].astype(str) == anchor].copy()
    sl = stk_limit[stk_limit["trade_date"].astype(str) == anchor].copy()

    d["ts_code"] = d["ts_code"].astype(str)
    db["ts_code"] = db["ts_code"].astype(str)
    sl["ts_code"] = sl["ts_code"].astype(str)

    merged = sb.merge(d, on="ts_code", how="inner").merge(db, on="ts_code", how="inner").merge(
        sl, on="ts_code", how="inner"
    )

    out: List[CandidateResult] = []
    for _, row in merged.iterrows():
        ts_code = str(row["ts_code"])
        name = str(row.get("name", "") or "")
        market = str(row.get("market", "") or "")
        industry = str(row.get("industry", "") or "")

        if market not in ALLOWED_MARKETS:
            continue
        if _is_st_name(name):
            continue
        if _is_delisting_risk_name(name):
            continue
        if ts_code in suspended:
            continue

        turnover = float(row["turnover_rate"])
        circ_mv = float(row["circ_mv"])
        if turnover < min_turnover_rate or circ_mv < min_circ_mv_wan:
            continue

        close = float(row["close"])
        pct_chg = float(row["pct_chg"])
        up_limit = float(row["up_limit"])
        down_limit = float(row["down_limit"])

        dist_up_pct: Optional[float] = None
        if close > 0 and up_limit > 0:
            dist_up_pct = (up_limit - close) / close * 100.0
        dist_down_pct: Optional[float] = None
        if close > 0 and down_limit > 0:
            dist_down_pct = (close - down_limit) / close * 100.0

        board = _market_to_board(market)
        risk_tags: List[str] = []
        evidence: List[str] = [f"scanner_version:{SCANNER_VERSION}", f"rule:anchor:{anchor}"]

        if dist_up_pct is not None and dist_up_pct <= 1.0:
            risk_tags.append("near_limit_up")
            evidence.append(f"rule:dist_to_up_limit_pct:{dist_up_pct:.2f}")
        if dist_down_pct is not None and dist_down_pct <= 1.0:
            risk_tags.append("near_limit_down")
            evidence.append(f"rule:dist_to_down_limit_pct:{dist_down_pct:.2f}")
        if pct_chg >= 9.5:
            risk_tags.append("strong_move_day")
            evidence.append(f"rule:pct_chg:{pct_chg:.2f}")

        score = 50.0
        if industry in hot:
            score += 12.0
            risk_tags.append("sector_hot")
            evidence.append("rule:hot_sector")
        if turnover >= 0.03:
            score += 8.0
            evidence.append(f"rule:turnover_rate_ok:{turnover:.4f}")
        if pct_chg >= 5.0:
            score += 10.0
        elif pct_chg >= 2.0:
            score += 5.0
        if dist_up_pct is not None and dist_up_pct <= 0.5:
            score += 8.0
            evidence.append("rule:pressing_limit_up")

        score = max(0.0, min(100.0, round(score, 2)))

        tag_t = tuple(risk_tags)
        trig = (
            f"锚定日 {anchor}：换手与市值满足观察阈值，涨跌幅 {pct_chg:.2f}%"
            + (f"，属热点行业「{industry}」" if industry in hot else "")
            + "。"
        )
        inv = (
            f"若后续跌破锚定日低点或失去量能支撑，则本次技术面/情绪触发条件视为失效"
            f"（锚定收盘 {close:.2f}）。"
        )

        out.append(
            CandidateResult(
                ts_code=ts_code,
                name=name,
                board=board,
                sector=industry,
                score=score,
                watch_allowed=True,
                trade_allowed=False,
                risk_tags=tag_t,
                trigger_condition=trig,
                invalid_condition=inv,
                evidence=tuple(evidence),
            )
        )

    out.sort(key=lambda r: (-r.score, r.ts_code))
    return out


def results_to_dataframe(results: Sequence[CandidateResult]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for r in results:
        rows.append(
            {
                "ts_code": r.ts_code,
                "name": r.name,
                "board": r.board,
                "sector": r.sector,
                "score": r.score,
                "watch_allowed": r.watch_allowed,
                "trade_allowed": r.trade_allowed,
                "risk_tags": ",".join(r.risk_tags),
                "trigger_condition": r.trigger_condition,
                "invalid_condition": r.invalid_condition,
                "evidence": "|".join(r.evidence),
            }
        )
    return pd.DataFrame(rows)

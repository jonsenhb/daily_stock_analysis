# -*- coding: utf-8 -*-
"""
Market Gate v1 — 确定性市场可交易性评分（研究/风控闸门）。

- 不接自动交易、不调 LLM、不调 Tushare。
- 输入须由上游准备好并以本模块约定单位传入。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

MARKET_GATE_RULE_VERSION = "1.0.0"

KNOWN_RISK_MARKERS = frozenset(
    {
        "high_volatility",
        "breadth_divergence",
        "liquidity_stress",
        "policy_uncertainty",
    }
)

MARKER_SCORE_DELTA = {
    "high_volatility": -5,
    "breadth_divergence": -4,
    "liquidity_stress": -6,
    "policy_uncertainty": -4,
}


@dataclass(frozen=True)
class MarketGateInput:
    """
    单位约定：
    - index_pct_chg: 基准指数当日涨跌幅，单位 **%**（如 1.25 表示 +1.25%）
    - turnover_vs_prev_ratio: 全市场成交额相对昨日 **倍数**（1.0 持平；缺失则不参与该项）
    - sector_strength / concept_strength: 归一化强弱 **[-1.0, 1.0]**，缺失不参与
    - risk_markers: 仅 KNOWN_RISK_MARKERS 内键会触发扣分与 risk_flags
    """

    index_pct_chg: Optional[float] = None
    advancing_count: Optional[int] = None
    declining_count: Optional[int] = None
    limit_up_count: Optional[int] = None
    limit_down_count: Optional[int] = None
    blown_limit_count: Optional[int] = None
    turnover_vs_prev_ratio: Optional[float] = None
    sector_strength: Optional[float] = None
    concept_strength: Optional[float] = None
    risk_markers: Optional[Tuple[str, ...]] = None


@dataclass(frozen=True)
class MarketGateResult:
    market_score: int
    trade_allowed: bool
    max_position_ratio: float
    market_state: str
    risk_flags: Tuple[str, ...]
    forbidden_actions: Tuple[str, ...]
    evidence: Tuple[str, ...]
    uncertainty: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # JSON 友好：tuple -> list
        for k, v in d.items():
            if isinstance(v, tuple):
                d[k] = list(v)
        return d


def _clamp_score(x: float) -> int:
    return int(max(0, min(100, round(x))))


def _breadth_ratio(inp: MarketGateInput) -> Optional[float]:
    a, d = inp.advancing_count, inp.declining_count
    if a is None or d is None:
        return None
    s = a + d
    if s <= 0:
        return None
    return a / s


def _count_signal_groups(inp: MarketGateInput) -> int:
    n = 0
    if inp.index_pct_chg is not None:
        n += 1
    if inp.advancing_count is not None and inp.declining_count is not None:
        n += 1
    if inp.limit_up_count is not None or inp.limit_down_count is not None:
        n += 1
    if inp.turnover_vs_prev_ratio is not None:
        n += 1
    if inp.sector_strength is not None or inp.concept_strength is not None:
        n += 1
    return n


def _apply_index(score: float, inp: MarketGateInput, evidence: List[str]) -> float:
    if inp.index_pct_chg is None:
        return score
    p = inp.index_pct_chg
    if p <= -3.0:
        score -= 20
        evidence.append(f"rule:index_pct_chg({p:.2f}<=-3):-20")
    elif p <= -1.5:
        score -= 12
        evidence.append(f"rule:index_pct_chg({p:.2f}<=-1.5):-12")
    elif p < -0.5:
        score -= 5
        evidence.append(f"rule:index_pct_chg({p:.2f}<-0.5):-5")
    elif p <= 0.5:
        evidence.append(f"rule:index_pct_chg(|{p:.2f}|<=0.5):0")
    elif p < 1.5:
        score += 5
        evidence.append(f"rule:index_pct_chg({p:.2f}<1.5):+5")
    elif p < 3.0:
        score += 12
        evidence.append(f"rule:index_pct_chg({p:.2f}<3):+12")
    else:
        score += 18
        evidence.append(f"rule:index_pct_chg({p:.2f}>=3):+18")
    return score


def _apply_breadth(score: float, inp: MarketGateInput, evidence: List[str]) -> float:
    br = _breadth_ratio(inp)
    if br is None:
        return score
    if br >= 0.65:
        score += 10
        evidence.append(f"rule:breadth_adv_share({br:.3f}>=0.65):+10")
    elif br >= 0.55:
        score += 5
        evidence.append(f"rule:breadth_adv_share({br:.3f}>=0.55):+5")
    elif br <= 0.35:
        score -= 10
        evidence.append(f"rule:breadth_adv_share({br:.3f}<=0.35):-10")
    elif br <= 0.45:
        score -= 5
        evidence.append(f"rule:breadth_adv_share({br:.3f}<=0.45):-5")
    else:
        evidence.append(f"rule:breadth_adv_share({br:.3f}):0")
    return score


def _apply_limits(
    score: float,
    inp: MarketGateInput,
    evidence: List[str],
    uncertainty: List[str],
    risk_flags: List[str],
) -> float:
    lu, ld = inp.limit_up_count, inp.limit_down_count
    if lu is None and ld is None:
        return score
    lu = lu or 0
    ld = ld or 0
    net = lu - ld
    polarized = lu >= 50 and ld >= 50
    if polarized:
        score -= 8
        uncertainty.append("polarized_high_limit_up_and_down")
        risk_flags.append("limit_polarity")
        evidence.append(f"rule:limit_polarization(up={lu},down={ld}):-8")

    if net >= 30:
        score += 8
        evidence.append(f"rule:limit_net({net}>=30):+8")
    elif net >= 10:
        score += 4
        evidence.append(f"rule:limit_net({net}>=10):+4")
    elif net <= -30:
        score -= 8
        evidence.append(f"rule:limit_net({net}<=-30):-8")
    elif net <= -10:
        score -= 4
        evidence.append(f"rule:limit_net({net}<=-10):-4")
    else:
        evidence.append(f"rule:limit_net({net}):0")
    return score


def _apply_blown(score: float, inp: MarketGateInput, evidence: List[str]) -> float:
    b = inp.blown_limit_count
    if b is None:
        return score
    if b >= 100:
        score -= 12
        evidence.append(f"rule:blown_limit({b}>=100):-12")
    elif b >= 50:
        score -= 8
        evidence.append(f"rule:blown_limit({b}>=50):-8")
    elif b >= 20:
        score -= 4
        evidence.append(f"rule:blown_limit({b}>=20):-4")
    elif b >= 5:
        score -= 2
        evidence.append(f"rule:blown_limit({b}>=5):-2")
    else:
        evidence.append(f"rule:blown_limit({b}):0")
    return score


def _apply_turnover(score: float, inp: MarketGateInput, evidence: List[str]) -> float:
    r = inp.turnover_vs_prev_ratio
    if r is None:
        evidence.append("skipped:turnover_vs_prev_ratio(missing)")
        return score
    if r >= 1.15:
        score += 6
        evidence.append(f"rule:turnover_ratio({r:.3f}>=1.15):+6")
    elif r >= 1.05:
        score += 3
        evidence.append(f"rule:turnover_ratio({r:.3f}>=1.05):+3")
    elif r <= 0.85:
        score -= 6
        evidence.append(f"rule:turnover_ratio({r:.3f}<=0.85):-6")
    elif r < 0.95:
        score -= 3
        evidence.append(f"rule:turnover_ratio({r:.3f}<0.95):-3")
    else:
        evidence.append(f"rule:turnover_ratio({r:.3f}):0")
    return score


def _apply_sector_concept(score: float, inp: MarketGateInput, evidence: List[str]) -> float:
    if inp.sector_strength is not None:
        ss = max(-1.0, min(1.0, inp.sector_strength))
        d = 8.0 * ss
        score += d
        evidence.append(f"rule:sector_strength({ss:.3f}):{d:+.1f}")
    if inp.concept_strength is not None:
        cs = max(-1.0, min(1.0, inp.concept_strength))
        d = 8.0 * cs
        score += d
        evidence.append(f"rule:concept_strength({cs:.3f}):{d:+.1f}")
    return score


def _apply_markers(
    score: float,
    inp: MarketGateInput,
    evidence: List[str],
    risk_flags: List[str],
    uncertainty: List[str],
) -> float:
    if not inp.risk_markers:
        return score
    for m in inp.risk_markers:
        if m in KNOWN_RISK_MARKERS:
            delta = MARKER_SCORE_DELTA[m]
            score += delta
            risk_flags.append(m)
            evidence.append(f"rule:risk_marker({m}):{delta}")
        else:
            uncertainty.append(f"unknown_risk_marker:{m}")
    return score


def _missing_uncertainty(inp: MarketGateInput, uncertainty: List[str]) -> None:
    if inp.index_pct_chg is None:
        uncertainty.append("missing:index_pct_chg")
    if inp.advancing_count is None or inp.declining_count is None:
        uncertainty.append("missing:advancing_or_declining_count")
    if inp.limit_up_count is None and inp.limit_down_count is None:
        uncertainty.append("missing:limit_up_and_limit_down")
    if inp.blown_limit_count is None:
        uncertainty.append("missing:blown_limit_count")
    if inp.turnover_vs_prev_ratio is None:
        uncertainty.append("missing:turnover_vs_prev_ratio")
    if inp.sector_strength is None:
        uncertainty.append("missing:sector_strength")
    if inp.concept_strength is None:
        uncertainty.append("missing:concept_strength")


def _state_and_actions(
    score: int, trade_allowed: bool
) -> Tuple[str, Tuple[str, ...], float]:
    if score < 32:
        state = "no_trade"
        actions = (
            "do_not_open_new_positions",
            "do_not_scale_in",
            "do_not_chase_unplanned_stocks",
        )
        max_pos = 0.0
    elif score < 42:
        state = "defensive"
        actions = ("do_not_chase_unplanned_stocks", "reduce_impulse_trades")
        max_pos = 0.12 if trade_allowed else 0.0
    elif score < 55:
        state = "light_position"
        actions = ("do_not_chase_unplanned_stocks",)
        max_pos = 0.22 if trade_allowed else 0.0
    elif score < 68:
        state = "normal"
        actions = ("do_not_chase_unplanned_stocks",)
        max_pos = 0.35 if trade_allowed else 0.0
    else:
        state = "elevated"
        actions = ("do_not_chase_unplanned_stocks", "size_new_positions_carefully")
        max_pos = 0.45 if trade_allowed else 0.0
    return state, actions, max_pos


def evaluate_market_gate(inp: MarketGateInput) -> MarketGateResult:
    evidence: List[str] = [f"rule_version:{MARKET_GATE_RULE_VERSION}"]
    uncertainty: List[str] = []
    risk_flags: List[str] = []

    _missing_uncertainty(inp, uncertainty)
    groups = _count_signal_groups(inp)
    insufficient = groups < 2

    if insufficient:
        uncertainty.append("insufficient_signal_groups(<2)")
    score_f = 50.0
    if insufficient:
        score_f -= 8.0
        evidence.append("rule:insufficient_coverage:-8")

    score_f = _apply_index(score_f, inp, evidence)
    score_f = _apply_breadth(score_f, inp, evidence)
    score_f = _apply_limits(score_f, inp, evidence, uncertainty, risk_flags)
    score_f = _apply_blown(score_f, inp, evidence)
    score_f = _apply_turnover(score_f, inp, evidence)
    score_f = _apply_sector_concept(score_f, inp, evidence)
    score_f = _apply_markers(score_f, inp, evidence, risk_flags, uncertainty)

    score = _clamp_score(score_f)

    trade_allowed = True
    if insufficient:
        trade_allowed = False
        evidence.append("gate:trade_disabled_insufficient_data")
    if score < 30:
        trade_allowed = False
        evidence.append("gate:trade_disabled_low_score")
    if "liquidity_stress" in risk_flags and score < 48:
        trade_allowed = False
        evidence.append("gate:trade_disabled_liquidity_stress")

    state, forbidden_actions, max_pos = _state_and_actions(score, trade_allowed)
    if not trade_allowed:
        max_pos = 0.0

    # 去重 risk_flags 保序
    seen: set = set()
    rf: List[str] = []
    for x in risk_flags:
        if x not in seen:
            seen.add(x)
            rf.append(x)

    return MarketGateResult(
        market_score=score,
        trade_allowed=trade_allowed,
        max_position_ratio=round(max_pos, 4),
        market_state=state,
        risk_flags=tuple(rf),
        forbidden_actions=forbidden_actions,
        evidence=tuple(evidence),
        uncertainty=tuple(uncertainty),
    )

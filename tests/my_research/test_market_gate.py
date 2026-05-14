# -*- coding: utf-8 -*-
"""Market Gate v1 单元测试：确定性规则，无网络。"""

from __future__ import annotations

from src.my_research.market_gate import (
    MarketGateInput,
    evaluate_market_gate,
)


def _full_inputs(**over):
    base = dict(
        index_pct_chg=0.5,
        advancing_count=2500,
        declining_count=2200,
        limit_up_count=45,
        limit_down_count=30,
        blown_limit_count=10,
        turnover_vs_prev_ratio=1.02,
        sector_strength=0.1,
        concept_strength=0.05,
    )
    base.update(over)
    return MarketGateInput(**base)


def test_extremely_weak_market():
    inp = _full_inputs(
        index_pct_chg=-3.8,
        advancing_count=600,
        declining_count=4400,
        limit_up_count=15,
        limit_down_count=200,
        blown_limit_count=90,
        turnover_vs_prev_ratio=0.82,
        sector_strength=-0.6,
        concept_strength=-0.5,
    )
    r = evaluate_market_gate(inp)
    assert r.market_score < 38
    assert r.trade_allowed is False
    assert r.max_position_ratio == 0.0
    assert r.market_state == "no_trade"


def test_choppy_neutral_market():
    inp = _full_inputs(
        index_pct_chg=0.05,
        advancing_count=2480,
        declining_count=2520,
        limit_up_count=38,
        limit_down_count=36,
        blown_limit_count=8,
        turnover_vs_prev_ratio=1.0,
        sector_strength=0.0,
        concept_strength=0.0,
    )
    r = evaluate_market_gate(inp)
    assert 46 <= r.market_score <= 58
    assert r.market_state in ("light_position", "normal", "defensive")


def test_strong_market():
    inp = _full_inputs(
        index_pct_chg=2.4,
        advancing_count=4200,
        declining_count=900,
        limit_up_count=130,
        limit_down_count=12,
        blown_limit_count=6,
        turnover_vs_prev_ratio=1.12,
        sector_strength=0.35,
        concept_strength=0.3,
    )
    r = evaluate_market_gate(inp)
    assert r.market_score >= 62
    assert r.trade_allowed is True
    assert r.max_position_ratio >= 0.30
    assert r.market_state in ("normal", "elevated")


def test_many_limit_up_and_many_limit_down():
    inp = _full_inputs(
        index_pct_chg=0.4,
        limit_up_count=200,
        limit_down_count=190,
        advancing_count=2000,
        declining_count=2200,
    )
    r = evaluate_market_gate(inp)
    assert "polarized_high_limit_up_and_down" in r.uncertainty
    assert "limit_polarity" in r.risk_flags


def test_missing_inputs_insufficient_coverage():
    inp = MarketGateInput(index_pct_chg=-0.5)
    r = evaluate_market_gate(inp)
    assert r.trade_allowed is False
    assert "insufficient_signal_groups" in " ".join(r.uncertainty)
    assert any("missing:" in u for u in r.uncertainty)


def test_missing_inputs_but_two_groups_still_trade_evaluated():
    inp = MarketGateInput(
        index_pct_chg=1.0,
        advancing_count=3000,
        declining_count=1500,
    )
    r = evaluate_market_gate(inp)
    assert r.trade_allowed is True
    assert "insufficient_signal_groups" not in " ".join(r.uncertainty)


def test_liquidity_stress_blocks_when_score_low():
    inp = _full_inputs(
        index_pct_chg=-0.8,
        advancing_count=1800,
        declining_count=2600,
        risk_markers=("liquidity_stress",),
    )
    r = evaluate_market_gate(inp)
    if r.market_score < 48:
        assert r.trade_allowed is False


def test_unknown_risk_marker_goes_to_uncertainty():
    inp = MarketGateInput(
        index_pct_chg=0.5,
        advancing_count=2500,
        declining_count=2200,
        risk_markers=("not_a_real_marker",),
    )
    r = evaluate_market_gate(inp)
    assert any("unknown_risk_marker" in u for u in r.uncertainty)


def test_result_to_dict_json_friendly():
    inp = _full_inputs()
    d = evaluate_market_gate(inp).to_dict()
    assert isinstance(d["risk_flags"], list)
    assert isinstance(d["market_score"], int)

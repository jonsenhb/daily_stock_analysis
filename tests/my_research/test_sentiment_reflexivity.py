# -*- coding: utf-8 -*-
"""sentiment_reflexivity：Mock DataFrame，无网络、无 LLM。"""

from __future__ import annotations

import pandas as pd
import pytest

from src.my_research.sentiment_reflexivity import evaluate_sentiment_reflexivity


def _frames(
    *,
    news_volume: float,
    sentiment_score: float,
    sentiment_dispersion: float | None,
    ret_short: float,
    ret_bench: float,
    vol_short: float,
    sector_p: float,
    sector_breadth: float | None = None,
):
    s = {"news_volume": [news_volume], "sentiment_score": [sentiment_score]}
    if sentiment_dispersion is not None:
        s["sentiment_dispersion"] = [sentiment_dispersion]
    s_df = pd.DataFrame(s)
    p_df = pd.DataFrame(
        [{"ret_short": ret_short, "ret_bench_short": ret_bench, "volatility_short": vol_short}]
    )
    h = {"sector_heat_percentile": [sector_p]}
    if sector_breadth is not None:
        h["sector_breadth"] = [sector_breadth]
    h_df = pd.DataFrame(h)
    return s_df, p_df, h_df


def test_overheat_high_heat_stagnant_price():
    s_df, p_df, h_df = _frames(
        news_volume=25.0,
        sentiment_score=0.85,
        sentiment_dispersion=0.1,
        ret_short=0.005,
        ret_bench=0.04,
        vol_short=0.02,
        sector_p=0.92,
    )
    r = evaluate_sentiment_reflexivity(s_df, p_df, h_df)
    assert r.overheat_risk is True
    assert r.sentiment_heat_score >= 60.0
    assert r.price_confirmation_score <= 50.0
    assert len(r.evidence) >= 3


def test_no_overheat_with_strong_confirmation():
    s_df, p_df, h_df = _frames(
        news_volume=30.0,
        sentiment_score=0.8,
        sentiment_dispersion=0.05,
        ret_short=0.08,
        ret_bench=0.02,
        vol_short=0.015,
        sector_p=0.9,
    )
    r = evaluate_sentiment_reflexivity(s_df, p_df, h_df)
    assert r.overheat_risk is False
    assert r.price_confirmation_score > 50.0


def test_missing_dispersion_adds_uncertainty():
    s_df, p_df, h_df = _frames(
        news_volume=5.0,
        sentiment_score=0.5,
        sentiment_dispersion=None,
        ret_short=0.02,
        ret_bench=0.02,
        vol_short=0.01,
        sector_p=0.5,
    )
    # 无 sentiment_dispersion 列
    r = evaluate_sentiment_reflexivity(s_df, p_df, h_df)
    assert any("dispersion" in u for u in r.uncertainty)
    assert r.disagreement_score <= 20.0


def test_missing_column_raises():
    s_df = pd.DataFrame([{"news_volume": 1.0}])  # no sentiment_score
    p_df = pd.DataFrame(
        [{"ret_short": 0.0, "ret_bench_short": 0.0, "volatility_short": 0.01}]
    )
    h_df = pd.DataFrame([{"sector_heat_percentile": 0.5}])
    with pytest.raises(ValueError, match="缺少列"):
        evaluate_sentiment_reflexivity(s_df, p_df, h_df)


def test_neutral_inputs_low_risk():
    s_df, p_df, h_df = _frames(
        news_volume=1.0,
        sentiment_score=0.05,
        sentiment_dispersion=0.01,
        ret_short=0.01,
        ret_bench=0.01,
        vol_short=0.01,
        sector_p=0.45,
    )
    r = evaluate_sentiment_reflexivity(s_df, p_df, h_df)
    assert r.overheat_risk is False


def test_sector_percentile_0_100_scale():
    s_df, p_df, h_df = _frames(
        news_volume=20.0,
        sentiment_score=0.9,
        sentiment_dispersion=0.2,
        ret_short=0.0,
        ret_bench=0.03,
        vol_short=0.02,
        sector_p=90.0,
    )
    r = evaluate_sentiment_reflexivity(s_df, p_df, h_df)
    assert r.sentiment_heat_score >= 60.0


def test_multi_row_uses_first_only():
    s_df = pd.DataFrame(
        {
            "news_volume": [20.0, 1.0],
            "sentiment_score": [0.9, 0.0],
            "sentiment_dispersion": [0.1, 0.0],
        }
    )
    p_df = pd.DataFrame(
        [
            {"ret_short": 0.0, "ret_bench_short": 0.03, "volatility_short": 0.02},
            {"ret_short": 0.5, "ret_bench_short": 0.0, "volatility_short": 0.01},
        ]
    )
    h_df = pd.DataFrame([{"sector_heat_percentile": 0.95}, {"sector_heat_percentile": 0.1}])
    r = evaluate_sentiment_reflexivity(s_df, p_df, h_df)
    assert any("仅使用" in u for u in r.uncertainty)

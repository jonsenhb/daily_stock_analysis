# -*- coding: utf-8 -*-
"""market_gate_adapter 单元测试：无网络。"""

from __future__ import annotations

from src.market_analyzer import MarketIndex, MarketOverview
from src.my_research.market_gate_adapter import (
    build_market_gate_section_for_review,
    ladder_to_concept_strength,
    overview_to_market_gate_input,
    sector_spread_to_strength,
)


def test_ladder_to_concept_none_without_tushare_date():
    assert ladder_to_concept_strength(5, 10, tushare_limit_trade_date=None) is None


def test_ladder_to_concept_none_without_max_streak():
    assert ladder_to_concept_strength(None, 10, tushare_limit_trade_date="20241125") is None


def test_ladder_to_concept_bounded():
    v = ladder_to_concept_strength(6, 20, tushare_limit_trade_date="20241125")
    assert v is not None
    assert -1.0 <= v <= 1.0


def test_sector_spread_strength():
    top = [{"name": "a", "change_pct": 3.0}, {"name": "b", "change_pct": 2.0}]
    bot = [{"name": "x", "change_pct": -1.0}]
    s = sector_spread_to_strength(top, bot)
    assert s is not None and s > 0


def test_overview_to_input_and_section_zh():
    ov = MarketOverview(date="2025-01-10")
    ov.indices = [
        MarketIndex(code="sh000001", name="上证", change_pct=0.8),
    ]
    ov.up_count = 2000
    ov.down_count = 1800
    ov.limit_up_count = 60
    ov.limit_down_count = 10
    ov.blown_limit_count = 15
    ov.tushare_limit_trade_date = "20250110"
    ov.limit_ladder_max_streak = 5
    ov.limit_ladder_ge3_count = 12
    ov.top_sectors = [{"name": "半导体", "change_pct": 2.1}]
    ov.bottom_sectors = [{"name": "地产", "change_pct": -0.5}]

    inp = overview_to_market_gate_input(ov, mood_index_code="000001")
    assert inp.concept_strength is not None
    assert inp.blown_limit_count == 15

    md = build_market_gate_section_for_review(ov, "000001", "zh")
    assert "### 市场交易闸门" in md
    assert "market_score" in md
    assert "trade_allowed" in md
    assert "max_position_ratio" in md
    assert "forbidden_actions" in md


def test_section_en_title():
    ov = MarketOverview(date="2025-01-10")
    ov.indices = [MarketIndex(code="sh000001", name="SSE", change_pct=0.5)]
    ov.up_count = 1500
    ov.down_count = 2000
    ov.limit_up_count = 30
    ov.limit_down_count = 25
    ov.tushare_limit_trade_date = "20250110"
    ov.limit_ladder_max_streak = 3
    ov.limit_ladder_ge3_count = 5

    md = build_market_gate_section_for_review(ov, "000001", "en")
    assert "### Market Trading Gate" in md
    assert "market_score" in md
    assert "trade_allowed" in md

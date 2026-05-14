# -*- coding: utf-8 -*-
"""trade_journal_agent：Mock LLM，无 Ollama、不读真实日志。"""

from __future__ import annotations

import pandas as pd
import pytest

from src.agent.llm_adapter import LLMResponse
from src.my_agents.trade_journal_agent import (
    build_trade_journal_review_messages,
    run_trade_journal_discipline_review,
    _parse_review_json,
)
from src.my_research.trade_journal import TradeJournalSummary, summary_from_dataframe


def _sample_summary() -> TradeJournalSummary:
    return TradeJournalSummary(
        total_trades=3,
        plan_trade_ratio=2 / 3,
        impulse_trade_count=1,
        avg_result_pct=0.5,
        max_loss=-100.0,
        risk_violations=("no_stop_loss_on_material_exposure",),
        discipline_score=72,
        notes="测试摘要。",
    )


def _valid_json_text() -> str:
    return (
        '{"discipline_score": 68, "plan_adherence": "计划执行尚可", '
        '"impulse_trades": ["20260110 600000 非计划追涨"], '
        '"risk_violations": ["重仓未止损"], '
        '"good_decisions": ["止损纪律一次"], '
        '"bad_decisions": ["情绪下单"], '
        '"tomorrow_forbidden_actions": ["禁止追未计划标的"], '
        '"uncertainty": ["样本仅3笔，外推有限"]}'
    )


def test_run_review_with_mock_llm():
    def llm_call(messages):
        assert any("纪律复盘" in m.get("content", "") for m in messages if m["role"] == "user")
        return LLMResponse(content=_valid_json_text(), provider="mock", model="mock")

    res = run_trade_journal_discipline_review(
        summary=_sample_summary(),
        llm_call=llm_call,
    )
    assert res.success is True
    assert res.discipline_score == 68
    assert len(res.impulse_trades) == 1
    assert "禁止" in res.tomorrow_forbidden_actions[0] or "标的" in res.tomorrow_forbidden_actions[0]


def test_parse_json_with_fence():
    raw = "```json\n" + _valid_json_text() + "\n```"
    r = _parse_review_json(raw)
    assert r.success and r.discipline_score == 68


def test_discipline_score_clamped():
    txt = _valid_json_text().replace("68", "150")
    r = _parse_review_json(txt)
    assert r.success and r.discipline_score == 100


def test_invalid_json_fails():
    r = _parse_review_json("not json")
    assert r.success is False
    assert r.error


def test_missing_llm_raises_usage():
    res = run_trade_journal_discipline_review(summary=_sample_summary())
    assert res.success is False
    assert "llm_adapter" in (res.error or "")


def test_empty_uncertainty_fails_review():
    def llm_call(_messages):
        j = (
            '{"discipline_score":50,"plan_adherence":"x","impulse_trades":[],"risk_violations":[],'
            '"good_decisions":[],"bad_decisions":[],"tomorrow_forbidden_actions":[],"uncertainty":[]}'
        )
        return LLMResponse(content=j, provider="mock", model="mock")

    res = run_trade_journal_discipline_review(summary=_sample_summary(), llm_call=llm_call)
    assert res.success is False
    assert "uncertainty" in (res.error or "")


def test_records_excerpt_from_dataframe():
    df = pd.DataFrame(
        [
            {
                "date": "20260110",
                "ts_code": "600000.SH",
                "name": "A",
                "side": "buy",
                "price": 10.0,
                "amount": 100.0,
                "position_ratio": 0.1,
                "reason": "测试",
                "plan_id": "p1",
                "is_plan_trade": True,
                "market_score": 50,
                "sector": "银行",
                "emotion_state": "冷静",
                "stop_loss": 9.0,
                "take_profit": None,
                "result_pnl": None,
                "result_pct": None,
                "review": "",
            }
        ]
    )
    msgs = build_trade_journal_review_messages(
        summary_from_dataframe(df), records_excerpt=df, max_records=20
    )
    user = msgs[-1]["content"]
    assert "600000.SH" in user

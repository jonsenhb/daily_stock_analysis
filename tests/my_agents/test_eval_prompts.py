# -*- coding: utf-8 -*-
"""评测提示与评分器：黄金样例，无 Ollama。"""

from __future__ import annotations

import pytest

from src.my_agents.eval_prompts import (
    EVAL_INJECT_TOKEN,
    EXPECT_JSON_TASKS,
    TASK_PROMPT_BUILDERS,
    get_eval_prompt,
    score_eval_response,
)


def test_all_tasks_have_prompt_and_token():
    for tid, builder in TASK_PROMPT_BUILDERS.items():
        p = builder()
        assert len(p) > 80
        assert EVAL_INJECT_TOKEN in p
        assert "禁止" in p or "不要" in p or "须" in p or "复盘" in p


def test_get_eval_prompt_unknown():
    with pytest.raises(ValueError, match="未知"):
        get_eval_prompt("not_a_task")


def test_score_good_market_review_json():
    sample = (
        '{"market_mood":"中性","liquidity_comment":"一般",'
        '"key_risks":["波动"],"invalidation_conditions":["放量上行"],'
        f'"uncertainty":["样本少 token {EVAL_INJECT_TOKEN}"]}}'
    )
    s = score_eval_response("market_review_json", sample)
    assert s.json_legal is True
    assert s.fields_complete is True
    assert s.no_profit_promise is True
    assert s.no_trade_instruction is True
    assert s.cites_evidence is True
    assert s.has_uncertainty is True


def test_score_invalid_json():
    s = score_eval_response("market_review_json", "not json")
    assert s.json_legal is False
    assert s.fields_complete is False


def test_profit_promise_detected():
    s = score_eval_response("risk_notice", "此股必涨，稳赚不赔。" + EVAL_INJECT_TOKEN)
    assert s.no_profit_promise is False
    assert s.json_legal is None


def test_trade_instruction_detected():
    s = score_eval_response("market_gate_explain", "建议立即买入 " + EVAL_INJECT_TOKEN)
    assert s.no_trade_instruction is False


def test_forbidden_phrase_not_trade_instruction():
    s = score_eval_response("forbidden_actions", "明日禁止立即买入冲动单。" + EVAL_INJECT_TOKEN)
    assert s.no_trade_instruction is True


def test_non_json_task_scores():
    body = f"风险包括集中度。不确定性：样本有限。{EVAL_INJECT_TOKEN}"
    s = score_eval_response("market_gate_explain", body)
    assert s.json_legal is None
    assert s.fields_complete is None
    assert s.cites_evidence is True
    assert s.has_uncertainty is True


def test_expect_json_task_list_consistent():
    for tid in EXPECT_JSON_TASKS:
        assert tid in TASK_PROMPT_BUILDERS

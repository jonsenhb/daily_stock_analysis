# -*- coding: utf-8 -*-
"""json_output：无 LLM，纯字符串解析。"""

from __future__ import annotations

import pytest

from src.my_agents.json_output import (
    extract_json_text_from_markdown,
    parse_llm_json_object,
    validate_value_types,
)


def test_plain_object():
    r = parse_llm_json_object('{"a": 1, "b": "x"}')
    assert r.success is True
    assert r.data == {"a": 1, "b": "x"}
    assert r.error is None
    assert r.missing_required_keys == ()


def test_fenced_json():
    raw = '前言\n```json\n{"x": true}\n```\n后记'
    r = parse_llm_json_object(raw)
    assert r.success is True
    assert r.data == {"x": True}


def test_invalid_json_returns_failure():
    r = parse_llm_json_object("{not json")
    assert r.success is False
    assert r.data is None
    assert r.error is not None
    assert "JSON" in r.error


def test_root_array_fails():
    r = parse_llm_json_object("[1,2,3]")
    assert r.success is False
    assert "对象" in (r.error or "")


def test_missing_required_keys_fail():
    r = parse_llm_json_object('{"a": 1}', required_keys=("a", "b"))
    assert r.success is False
    assert r.missing_required_keys == ("b",)
    assert r.data is None
    assert "b" in (r.error or "")


def test_required_keys_satisfied():
    r = parse_llm_json_object(
        '{"discipline_score": 1, "plan_adherence": ""}',
        required_keys=("discipline_score", "plan_adherence"),
    )
    assert r.success is True


def test_extract_markdown_only():
    t = extract_json_text_from_markdown("```\n{\"k\":1}\n```")
    assert '"k"' in t


def test_none_input():
    r = parse_llm_json_object(None)
    assert r.success is False


def test_validate_value_types():
    errs = validate_value_types({"n": 3, "s": "x"}, {"n": int, "s": str})
    assert errs == ()
    errs2 = validate_value_types({"n": "bad"}, {"n": int})
    assert len(errs2) == 1

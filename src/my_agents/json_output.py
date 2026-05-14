# -*- coding: utf-8 -*-
"""
LLM 输出 JSON 提取与可验证解析（自定义 Agent / 研究模块复用）。

- 仅从文本提取并 json.loads；不调用 LLM。
- 必填键缺失或根非 object 时 success=False，不静默返回不完整对象。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

JSON_OUTPUT_VERSION = "1.0.0"

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


@dataclass(frozen=True)
class JsonOutputParseResult:
    """解析结果；失败时 data 为 None。"""

    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    missing_required_keys: Tuple[str, ...] = ()
    raw_extracted: Optional[str] = None


def extract_json_text_from_markdown(raw: str) -> str:
    """
    从可能的 Markdown 围栏中提取待解析 JSON 文本。
    若无围栏，返回去空白后的全文（或由 parse_llm_json_object 再截取对象）。
    """
    s = (raw or "").strip()
    if not s:
        return ""
    m = _FENCE_RE.search(s)
    if m:
        return m.group(1).strip()
    return s


def _first_json_object_slice(text: str) -> str:
    """取首个 { 到最后一个 } 的子串（与现有 agent 启发式一致）。"""
    s = text.strip()
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        return s[start : end + 1]
    return s


def parse_llm_json_object(
    raw: Optional[str],
    *,
    required_keys: Sequence[str] = (),
) -> JsonOutputParseResult:
    """
    从 LLM 原文中提取 JSON 对象并校验必填键。

    - 根节点必须是 JSON object（dict），数组或其它类型视为失败。
    - required_keys 中任一缺失则 success=False，missing_required_keys 列出键名。
    """
    if raw is None:
        return JsonOutputParseResult(success=False, error="输入为 None")

    extracted = extract_json_text_from_markdown(str(raw))
    if not extracted.strip():
        return JsonOutputParseResult(success=False, error="提取后文本为空")

    candidate = _first_json_object_slice(extracted)
    raw_for_result = candidate if len(candidate) <= 8000 else candidate[:8000] + "…"

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as e:
        return JsonOutputParseResult(
            success=False,
            error=f"JSON 解析失败: {e}",
            raw_extracted=raw_for_result,
        )

    if not isinstance(data, dict):
        return JsonOutputParseResult(
            success=False,
            error=f"根节点必须是 JSON 对象，实际为 {type(data).__name__}",
            raw_extracted=raw_for_result,
        )

    req = tuple(str(k) for k in required_keys if str(k).strip())
    if not req:
        return JsonOutputParseResult(
            success=True,
            data=data,
            missing_required_keys=tuple(),
            raw_extracted=raw_for_result,
        )

    missing = tuple(k for k in req if k not in data)
    if missing:
        return JsonOutputParseResult(
            success=False,
            data=None,
            error=f"缺少必填字段: {', '.join(missing)}",
            missing_required_keys=missing,
            raw_extracted=raw_for_result,
        )

    return JsonOutputParseResult(
        success=True,
        data=data,
        missing_required_keys=tuple(),
        raw_extracted=raw_for_result,
    )


def validate_value_types(
    data: Mapping[str, Any],
    schema: Mapping[str, type | tuple[type, ...]],
) -> Tuple[str, ...]:
    """
    对扁平键做类型检查；返回问题描述元组（空表示通过）。
    """
    errs: list[str] = []
    for key, expected in schema.items():
        if key not in data:
            continue
        val = data[key]
        types = expected if isinstance(expected, tuple) else (expected,)
        if val is not None and not isinstance(val, types):
            errs.append(f"{key!r}: 期望 {types}，实际 {type(val).__name__}")
    return tuple(errs)

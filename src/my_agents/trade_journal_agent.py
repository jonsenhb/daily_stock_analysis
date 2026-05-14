# -*- coding: utf-8 -*-
"""
交易纪律复盘 Agent — prompt 模板 + 经 `LLMToolAdapter.call_text` 的本地调用封装。

- 仅复盘与纪律讨论；不承诺收益、不输出下单指令、不读取默认交易日志路径。
- 测试请注入 `llm_call`，禁止依赖真实 Ollama/网络。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd

from src.agent.llm_adapter import LLMResponse, LLMToolAdapter
from src.my_research.trade_journal import TradeJournalSummary, TradeRecord, records_from_dataframe

TRADE_JOURNAL_AGENT_VERSION = "1.0.0"

DEFAULT_MAX_RECORDS_IN_PROMPT = 20

TRADE_JOURNAL_REVIEW_SYSTEM = """\
你是个人交易纪律与执行复盘助手，仅基于用户提供的结构化摘要与交易摘录做反思与总结。

硬性约束（违反则视为严重错误）：
1. 只做复盘与纪律讨论，不是投资顾问，不提供「买/卖/加仓/减仓」等具体交易指令，不代替用户或系统下单。
2. 不承诺未来收益；禁止使用「必涨」「必跌」「稳赚」等确定性表述。
3. 必须区分并讨论（在材料足够时）：计划内（模式内）亏损、计划外（模式外）盈利、冲动交易（非计划成交）；材料不足时写入 uncertainty。
4. 输出格式：只输出一个 JSON 对象本身，不要 Markdown 说明、不要代码围栏以外的文字。键名与 schema 必须与用户消息中给出的完全一致。
5. JSON 中列表缺失信息时用 []，字符串用 \"\"；uncertainty 必须包含至少一条与本材料局限相关的说明。

字段语义提示：
- discipline_score：0–100 的纪律复盘分（可与摘要中的规则分不同，但若差异大须在 uncertainty 中说明依据有限）。
- tomorrow_forbidden_actions：明日纪律约束用语（如「禁止追未计划标的」），不得写成订单。
"""


def _sanitize_json_value(v: Any) -> Any:
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, dict):
        return {k: _sanitize_json_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitize_json_value(x) for x in v]
    return v


def _summary_to_payload(summary: Union[TradeJournalSummary, Mapping[str, Any]]) -> Dict[str, Any]:
    if isinstance(summary, TradeJournalSummary):
        d = summary.to_dict()
    else:
        d = dict(summary)
    return _sanitize_json_value(d)  # type: ignore[return-value]


def _normalize_records_excerpt(
    records_excerpt: Union[Sequence[TradeRecord], pd.DataFrame, str, None],
    *,
    max_records: int,
) -> Optional[str]:
    if records_excerpt is None:
        return None
    if isinstance(records_excerpt, str):
        return records_excerpt.strip() or None
    if isinstance(records_excerpt, pd.DataFrame):
        recs = records_from_dataframe(records_excerpt)
    else:
        recs = list(records_excerpt)
    recs = recs[: max(0, max_records)]
    payload = [_sanitize_json_value(r.to_dict()) for r in recs]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_trade_journal_review_messages(
    summary: Union[TradeJournalSummary, Mapping[str, Any]],
    *,
    records_excerpt: Union[Sequence[TradeRecord], pd.DataFrame, str, None] = None,
    max_records: int = DEFAULT_MAX_RECORDS_IN_PROMPT,
) -> List[Dict[str, str]]:
    """组装 `LLMToolAdapter.call_text` 所需的 messages。"""
    summary_json = json.dumps(_summary_to_payload(summary), ensure_ascii=False, indent=2)
    excerpt = _normalize_records_excerpt(records_excerpt, max_records=max_records)
    excerpt_block = (
        f"以下为最多 {max_records} 条交易摘录（JSON 数组）：\n{excerpt}\n"
        if excerpt
        else "未提供交易明细摘录，仅根据摘要复盘；须在 uncertainty 中说明信息不全。\n"
    )
    schema = json.dumps(
        {
            "discipline_score": 0,
            "plan_adherence": "",
            "impulse_trades": [],
            "risk_violations": [],
            "good_decisions": [],
            "bad_decisions": [],
            "tomorrow_forbidden_actions": [],
            "uncertainty": [],
        },
        ensure_ascii=False,
        indent=2,
    )
    user = f"""请根据以下数据完成纪律复盘，并只输出符合 schema 的 JSON（键名、类型一致）。

## 确定性摘要（可为规则引擎结果，仅供对照）
{summary_json}

## 交易摘录
{excerpt_block}

## 输出 JSON schema（键必须齐全）
{schema}
"""
    return [
        {"role": "system", "content": TRADE_JOURNAL_REVIEW_SYSTEM},
        {"role": "user", "content": user},
    ]


def _extract_json_object(text: str) -> str:
    s = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.IGNORECASE)
    if fence:
        s = fence.group(1).strip()
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        return s[start : end + 1]
    return s


def _as_str_list(val: Any) -> Tuple[str, ...]:
    if not val:
        return tuple()
    if not isinstance(val, list):
        return (str(val).strip(),) if str(val).strip() else tuple()
    out: List[str] = []
    for x in val:
        if x is None:
            continue
        t = str(x).strip()
        if t:
            out.append(t)
    return tuple(out)


def _clamp_discipline_score(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        x = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return int(max(0, min(100, round(x))))


@dataclass
class TradeJournalReviewResult:
    """LLM 纪律复盘解析结果（非下单指令）。"""

    success: bool
    error: Optional[str] = None
    raw_content: Optional[str] = None
    discipline_score: Optional[int] = None
    plan_adherence: str = ""
    impulse_trades: Tuple[str, ...] = ()
    risk_violations: Tuple[str, ...] = ()
    good_decisions: Tuple[str, ...] = ()
    bad_decisions: Tuple[str, ...] = ()
    tomorrow_forbidden_actions: Tuple[str, ...] = ()
    uncertainty: Tuple[str, ...] = ()


def _parse_review_json(content: str) -> TradeJournalReviewResult:
    raw = content
    try:
        blob = _extract_json_object(content)
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        return TradeJournalReviewResult(
            success=False,
            error=f"JSON 解析失败: {e}",
            raw_content=raw,
        )
    if not isinstance(data, dict):
        return TradeJournalReviewResult(
            success=False,
            error="根节点必须是 JSON 对象",
            raw_content=raw,
        )
    disc = _clamp_discipline_score(data.get("discipline_score"))
    pa = data.get("plan_adherence")
    plan_adherence = str(pa).strip() if pa is not None else ""

    return TradeJournalReviewResult(
        success=True,
        raw_content=raw,
        discipline_score=disc,
        plan_adherence=plan_adherence,
        impulse_trades=_as_str_list(data.get("impulse_trades")),
        risk_violations=_as_str_list(data.get("risk_violations")),
        good_decisions=_as_str_list(data.get("good_decisions")),
        bad_decisions=_as_str_list(data.get("bad_decisions")),
        tomorrow_forbidden_actions=_as_str_list(data.get("tomorrow_forbidden_actions")),
        uncertainty=_as_str_list(data.get("uncertainty")),
    )


def run_trade_journal_discipline_review(
    *,
    summary: Union[TradeJournalSummary, Mapping[str, Any]],
    records_excerpt: Union[Sequence[TradeRecord], pd.DataFrame, str, None] = None,
    max_records: int = DEFAULT_MAX_RECORDS_IN_PROMPT,
    llm_adapter: Optional[LLMToolAdapter] = None,
    llm_call: Optional[Callable[[List[Dict[str, str]]], LLMResponse]] = None,
    temperature: Optional[float] = None,
    timeout: Optional[float] = None,
) -> TradeJournalReviewResult:
    """
    调用 LLM 完成交易纪律复盘；默认需 `llm_adapter` 或测试用 `llm_call` 之一。

    参数 `records_excerpt` 默认最多取 `max_records` 条写入 prompt；不读磁盘日志路径。
    """
    messages = build_trade_journal_review_messages(
        summary, records_excerpt=records_excerpt, max_records=max_records
    )

    if llm_call is not None:
        response = llm_call(messages)
    elif llm_adapter is not None:
        response = llm_adapter.call_text(messages, temperature=temperature, timeout=timeout)
    else:
        return TradeJournalReviewResult(
            success=False,
            error="需要提供 llm_adapter 或 llm_call",
        )

    if not response or response.provider == "error":
        return TradeJournalReviewResult(
            success=False,
            error=(response.content or "LLM 调用失败") if response else "无响应",
            raw_content=response.content if response else None,
        )
    content = (response.content or "").strip()
    if not content:
        return TradeJournalReviewResult(success=False, error="模型返回空内容")

    parsed = _parse_review_json(content)
    if not parsed.success:
        return parsed
    if not parsed.uncertainty:
        return TradeJournalReviewResult(
            success=False,
            error="模型输出缺少有效的 uncertainty 列表",
            raw_content=parsed.raw_content,
        )
    return parsed

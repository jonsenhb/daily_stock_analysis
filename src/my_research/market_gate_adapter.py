# -*- coding: utf-8 -*-
"""
Market Gate ↔ 大盘复盘：从 MarketOverview 构造输入并渲染 Markdown 段落。

- 仅 A 股（cn）在复盘末尾追加；不调 LLM、不在此模块请求网络。
"""

from __future__ import annotations

from typing import Any, List, Optional

from src.my_research.market_gate import MarketGateInput, MarketGateResult, evaluate_market_gate


def ladder_to_concept_strength(
    max_streak: Optional[int],
    ge3_count: Optional[int],
    *,
    tushare_limit_trade_date: Optional[str],
) -> Optional[float]:
    """
    将连板天梯摘要映射到 [-1, 1]，供 MarketGateInput.concept_strength。

    无 Tushare 快照（trade_date 未写入）或无有效最高连板时返回 None。
    """
    if not tushare_limit_trade_date or max_streak is None:
        return None
    ms = int(max_streak)
    if ms < 1:
        return None
    g = int(ge3_count or 0)

    if ms <= 2:
        base = -0.15 + 0.05 * (ms - 1)
    elif ms <= 4:
        base = 0.05 + 0.1 * (ms - 2)
    elif ms <= 7:
        base = 0.25 + 0.05 * (ms - 4)
    else:
        base = min(0.85, 0.4 + 0.045 * (ms - 7))

    base += 0.12 * min(g, 45) / 45.0
    return max(-1.0, min(1.0, base))


def sector_spread_to_strength(top_sectors: List[Any], bottom_sectors: List[Any]) -> Optional[float]:
    """领涨/领跌平均涨跌幅之差，压到 [-1, 1]。"""
    if not top_sectors and not bottom_sectors:
        return None

    def _avg_pct(rows: List[Any]) -> Optional[float]:
        if not rows:
            return None
        vals: List[float] = []
        for r in rows[:5]:
            if isinstance(r, dict):
                v = r.get("change_pct")
            else:
                v = getattr(r, "change_pct", None)
            try:
                if v is not None:
                    vals.append(float(v))
            except (TypeError, ValueError):
                continue
        if not vals:
            return None
        return sum(vals) / len(vals)

    top_m = _avg_pct(list(top_sectors))
    bot_m = _avg_pct(list(bottom_sectors))
    if top_m is None and bot_m is None:
        return None
    top_m = top_m or 0.0
    bot_m = bot_m or 0.0
    spread = top_m - bot_m
    return max(-1.0, min(1.0, spread / 8.0))


def overview_benchmark_pct_chg(overview: Any, mood_index_code: str) -> Optional[float]:
    indices = getattr(overview, "indices", None) or []
    if not indices:
        return None
    for idx in indices:
        code = str(getattr(idx, "code", "") or "")
        if code == mood_index_code or code.endswith(mood_index_code):
            cp = getattr(idx, "change_pct", None)
            return float(cp) if cp is not None else None
    first = indices[0]
    cp = getattr(first, "change_pct", None)
    return float(cp) if cp is not None else None


def overview_to_market_gate_input(overview: Any, *, mood_index_code: str) -> MarketGateInput:
    """从当次 MarketOverview 组装 MarketGateInput；缺失项为 None，交由 evaluate 记 uncertainty。"""
    idx_pct = overview_benchmark_pct_chg(overview, mood_index_code)

    concept = ladder_to_concept_strength(
        getattr(overview, "limit_ladder_max_streak", None),
        getattr(overview, "limit_ladder_ge3_count", None),
        tushare_limit_trade_date=getattr(overview, "tushare_limit_trade_date", None),
    )
    sector = sector_spread_to_strength(
        getattr(overview, "top_sectors", None) or [],
        getattr(overview, "bottom_sectors", None) or [],
    )

    return MarketGateInput(
        index_pct_chg=idx_pct,
        advancing_count=int(getattr(overview, "up_count", 0)),
        declining_count=int(getattr(overview, "down_count", 0)),
        limit_up_count=int(getattr(overview, "limit_up_count", 0)),
        limit_down_count=int(getattr(overview, "limit_down_count", 0)),
        blown_limit_count=getattr(overview, "blown_limit_count", None),
        turnover_vs_prev_ratio=None,
        sector_strength=sector,
        concept_strength=concept,
        risk_markers=None,
    )


def render_market_gate_section_md(
    result: MarketGateResult,
    overview: Any,
    *,
    language: str,
) -> str:
    """渲染复盘追加块：含必选字段与合规提示。"""
    lang = (language or "zh").lower()
    if lang.startswith("en"):
        title = "### Market Trading Gate"
        intro = (
            "Deterministic **research / risk-control** summary from available snapshot data. "
            "**Not** buy/sell advice; **no** guaranteed returns. Human judgment required."
        )
        ta = "yes" if result.trade_allowed else "no"
        forbid = ", ".join(result.forbidden_actions) if result.forbidden_actions else "(none)"
        lines: List[str] = [
            title,
            "",
            intro,
            "",
            f"- **market_score**: {result.market_score}",
            f"- **trade_allowed**: {ta}",
            f"- **max_position_ratio**: {result.max_position_ratio}",
            f"- **forbidden_actions**: {forbid}",
            f"- **market_state**: `{result.market_state}`",
        ]
        if result.risk_flags:
            lines.append(f"- **risk_flags**: {', '.join(str(x) for x in result.risk_flags)}")
        unc = list(result.uncertainty or ())[:6]
        if unc:
            lines.append(f"- **uncertainty** (excerpt): {', '.join(unc)}")
        td = getattr(overview, "tushare_limit_trade_date", None)
        mx = getattr(overview, "limit_ladder_max_streak", None)
        bl = getattr(overview, "blown_limit_count", None)
        if td is not None:
            lines.append(
                f"- **snapshot note** (facts only): Tushare `trade_date={td}`; "
                f"blown (Z) count={bl if bl is not None else 'N/A'}; ladder max streak={mx if mx is not None else 'N/A'}."
            )
        return "\n".join(lines)

    title = "### 市场交易闸门"
    intro = (
        "以下为基于当前可得的盘面结构化数据、经**确定性规则**汇总的**研究与风控参考**，"
        "**不构成**任何买入/卖出/建仓建议，**不保证**收益；是否交易需您独立判断。"
    )
    ta = "是" if result.trade_allowed else "否"
    forbid = "、".join(result.forbidden_actions) if result.forbidden_actions else "（无）"
    lines = [
        title,
        "",
        intro,
        "",
        f"- **market_score**：{result.market_score}",
        f"- **trade_allowed**：{ta}",
        f"- **max_position_ratio**：{result.max_position_ratio}",
        f"- **forbidden_actions**：{forbid}",
        f"- **market_state**：`{result.market_state}`",
    ]
    if result.risk_flags:
        lines.append(f"- **risk_flags**：{'、'.join(str(x) for x in result.risk_flags)}")
    unc = list(result.uncertainty or ())[:6]
    if unc:
        lines.append(f"- **uncertainty**（节选）：{'、'.join(unc)}")
    td = getattr(overview, "tushare_limit_trade_date", None)
    mx = getattr(overview, "limit_ladder_max_streak", None)
    bl = getattr(overview, "blown_limit_count", None)
    if td is not None:
        lines.append(
            f"- **数据备忘**（事实陈列）：Tushare 快照 `trade_date={td}`；炸板（Z）**{bl if bl is not None else 'N/A'}** 家；"
            f"连板高度最高 **{mx if mx is not None else 'N/A'}** 板。"
        )
    return "\n".join(lines)


def build_market_gate_section_for_review(
    overview: Any,
    mood_index_code: str,
    review_language: str,
) -> str:
    """生成追加全文；调用方保证 region 为 cn。"""
    inp = overview_to_market_gate_input(overview, mood_index_code=mood_index_code)
    res = evaluate_market_gate(inp)
    return render_market_gate_section_md(res, overview, language=review_language)

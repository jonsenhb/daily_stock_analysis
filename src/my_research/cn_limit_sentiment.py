# -*- coding: utf-8 -*-
"""
A 股涨停情绪快照：Tushare limit_list_d（含炸板 Z）与 limit_step（连板天梯）。

- 供大盘复盘 enrichment 使用；不读 .env，token 由调用方传入。
- 交易日锚定：trade_cal + 上海时区；收盘前会话使用前一交易日（limit 类接口多为盘后完整口径）。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, List

import pandas as pd
from zoneinfo import ZoneInfo

from src.my_research.tushare_research_client import TushareResearchClient

logger = logging.getLogger(__name__)

_CN_TZ = ZoneInfo("Asia/Shanghai")


def resolve_cn_trade_date_for_limit_snapshot(
    client: TushareResearchClient,
    *,
    now_cn: datetime | None = None,
) -> str:
    """
    返回 YYYYMMDD：用于 limit_list_d / limit_step 的 trade_date。

    规则：
    - 取 SSE 历日上「今天（上海）」及之前的最近开市日；
    - 若「今天」本身是交易日且当地时刻早于 15:05，则退回上一交易日（盘中/盘前不强行套当日收盘快照）。
    """
    now_cn = now_cn or datetime.now(_CN_TZ)
    if now_cn.tzinfo is None:
        now_cn = now_cn.replace(tzinfo=_CN_TZ)
    today = now_cn.date()
    end_s = today.strftime("%Y%m%d")
    start_s = (today - timedelta(days=400)).strftime("%Y%m%d")
    try:
        cal = client.get_trade_calendar(
            exchange="SSE",
            start_date=start_s,
            end_date=end_s,
            is_open="1",
        )
    except Exception as exc:
        logger.warning("[cn_limit_sentiment] trade_cal 失败，回退日历日 anchor=%s: %s", end_s, exc)
        return end_s

    if cal is None or cal.empty or "cal_date" not in cal.columns:
        logger.warning("[cn_limit_sentiment] trade_cal 为空或缺 cal_date，回退 %s", end_s)
        return end_s

    open_days: List[date] = []
    for raw in cal["cal_date"].astype(str).tolist():
        try:
            open_days.append(datetime.strptime(raw, "%Y%m%d").date())
        except ValueError:
            continue
    open_days.sort()
    eligible = [d for d in open_days if d <= today]
    if not eligible:
        return end_s
    latest = max(eligible)
    if latest == today:
        t = now_cn.timetz()
        pre_close = (t.hour < 15) or (t.hour == 15 and t.minute < 5)
        if pre_close:
            before_today = [d for d in eligible if d < today]
            if before_today:
                latest = max(before_today)
    return latest.strftime("%Y%m%d")


def enrich_overview_cn_limit_sentiment(overview: Any, *, token: str) -> None:
    """
    就地写入 overview 的 Tushare 涨跌停快照字段（失败则保持默认，不打断主流程）。

    依赖 overview 为 MarketOverview（duck typing），需具备：
    tushare_limit_trade_date, blown_limit_count, limit_ladder_max_streak,
    limit_ladder_ge3_count, limit_step_top
    """
    tok = str(token or "").strip()
    if not tok:
        return

    try:
        client = TushareResearchClient(token=tok)
        anchor = resolve_cn_trade_date_for_limit_snapshot(client)
        df_z = client.get_limit_list(trade_date=anchor, limit_type="Z")
        df_step = client.get_limit_step(trade_date=anchor)
    except Exception as exc:
        logger.warning("[cn_limit_sentiment] Tushare 快照跳过: %s", exc)
        return

    overview.tushare_limit_trade_date = anchor
    overview.blown_limit_count = int(len(df_z)) if df_z is not None else 0

    if df_step is None or df_step.empty:
        overview.limit_ladder_max_streak = None
        overview.limit_ladder_ge3_count = None
        overview.limit_step_top = []
        logger.info(
            "[cn_limit_sentiment] trade_date=%s blown=%s ladder_rows=0",
            anchor,
            overview.blown_limit_count,
        )
        return

    if "nums" not in df_step.columns:
        overview.limit_ladder_max_streak = None
        overview.limit_ladder_ge3_count = None
        overview.limit_step_top = []
        logger.warning("[cn_limit_sentiment] limit_step 返回缺 nums 列，跳过天梯统计")
        return

    nums = pd.to_numeric(df_step["nums"], errors="coerce").fillna(0).astype(int)
    enriched = df_step.copy()
    enriched["_nums_i"] = nums
    overview.limit_ladder_max_streak = int(nums.max())
    overview.limit_ladder_ge3_count = int((nums >= 3).sum())
    top = enriched.sort_values("_nums_i", ascending=False).head(5)
    names_col = "name" if "name" in top.columns else None
    code_col = "ts_code" if "ts_code" in top.columns else None
    top_list: List[dict[str, Any]] = []
    for _, row in top.iterrows():
        top_list.append(
            {
                "ts_code": str(row[code_col]) if code_col else "",
                "name": str(row[names_col]) if names_col else "",
                "nums": int(row["_nums_i"]),
            }
        )
    overview.limit_step_top = top_list
    logger.info(
        "[cn_limit_sentiment] trade_date=%s blown=%s ladder_max=%s ge3=%s",
        anchor,
        overview.blown_limit_count,
        overview.limit_ladder_max_streak,
        overview.limit_ladder_ge3_count,
    )

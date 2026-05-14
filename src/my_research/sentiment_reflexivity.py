# -*- coding: utf-8 -*-
"""
舆情反身性研究 — 在已有「舆情 / 价格 / 板块热度」特征上识别「舆情偏热但价格未确认」的结构信号。

- 不抓新闻、不调用 LLM、不调用搜索；输入为 pandas DataFrame（通常单行截面）。
- 输出为研究用描述量，不构成投资建议，不承诺收益。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import FrozenSet, List, Tuple

import pandas as pd

SENTIMENT_REFLEXIVITY_VERSION = "1.0.0"

SENTIMENT_REQUIRED = frozenset({"news_volume", "sentiment_score"})
PRICE_REQUIRED = frozenset({"ret_short", "ret_bench_short", "volatility_short"})
SECTOR_REQUIRED = frozenset({"sector_heat_percentile"})

# 过热判定：舆情热 + 价格确认弱 + 超额偏弱
OVERHEAT_HEAT_MIN = 60.0
OVERHEAT_CONFIRM_MAX = 50.0
OVERHEAT_EXCESS_MAX = 0.01  # 相对基准超额低于约 1pp 视为滞涨侧


def _require_columns(df: pd.DataFrame, required: FrozenSet[str], name: str) -> None:
    miss = required - set(df.columns)
    if miss:
        raise ValueError(f"{name} 缺少列: {sorted(miss)}")
    if df.empty:
        raise ValueError(f"{name} 不得为空")


def _row(df: pd.DataFrame) -> pd.Series:
    if len(df) > 1:
        # 仅取首行，避免无声错误
        pass
    return df.iloc[0]


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _saturation_volume(news_volume: float) -> float:
    """将新闻量映射到 [0,100]，边际递减。"""
    v = max(0.0, float(news_volume))
    return 100.0 * (1.0 - math.exp(-v / 8.0))


def _sentiment_magnitude(sentiment_score: float) -> float:
    s = _clamp(float(sentiment_score), -1.0, 1.0)
    return abs(s) * 100.0


def _sector_component(sector_p: float) -> float:
    p = float(sector_p)
    if p > 1.0 + 1e-6:
        # 允许误传 0-100
        p = p / 100.0
    p = _clamp(p, 0.0, 1.0)
    return p * 100.0


def _disagreement_from_dispersion(disp: float) -> float:
    d = max(0.0, float(disp))
    return _clamp(100.0 * (1.0 - math.exp(-d / 0.25)), 0.0, 100.0)


def _price_confirmation(
    ret_short: float,
    ret_bench_short: float,
    volatility_short: float,
) -> float:
    excess = float(ret_short) - float(ret_bench_short)
    vol = max(0.0, float(volatility_short))
    # 超额：±5% 左右拉满一侧
    base = 50.0 + 50.0 * _clamp(excess / 0.05, -1.0, 1.0)
    # 波动过高略降确认（噪声/不稳）
    vol_pen = 0.0
    if vol > 0.025:
        vol_pen = min(25.0, (vol - 0.025) * 400.0)
    return _clamp(base - vol_pen, 0.0, 100.0)


@dataclass(frozen=True)
class SentimentReflexivityResult:
    sentiment_heat_score: float
    disagreement_score: float
    price_confirmation_score: float
    overheat_risk: bool
    evidence: Tuple[str, ...]
    uncertainty: Tuple[str, ...]


def evaluate_sentiment_reflexivity(
    sentiment_features: pd.DataFrame,
    price_features: pd.DataFrame,
    sector_heat_features: pd.DataFrame,
) -> SentimentReflexivityResult:
    """
    基于单行（取每组 DataFrame 的 iloc[0]）特征评估反身性过热风险。

    sentiment_features 必填：news_volume (≥0), sentiment_score ([-1,1] 利多偏正)。
    可选：sentiment_dispersion (≥0)，缺失时分歧分偏低并在 uncertainty 中说明。

    price_features 必填：ret_short, ret_bench_short, volatility_short (≥0)，收益为小数。

    sector_heat_features 必填：sector_heat_percentile ∈ [0,1]（或 0–100 会自动缩放）。
    可选：sector_breadth ∈ [0,1]，当前版本仅记入 evidence 若存在。
    """
    _require_columns(sentiment_features, SENTIMENT_REQUIRED, "sentiment_features")
    _require_columns(price_features, PRICE_REQUIRED, "price_features")
    _require_columns(sector_heat_features, SECTOR_REQUIRED, "sector_heat_features")

    srow = _row(sentiment_features)
    prow = _row(price_features)
    hrow = _row(sector_heat_features)

    nv = pd.to_numeric(srow["news_volume"], errors="coerce")
    news_volume = 0.0 if pd.isna(nv) else float(nv)
    news_volume = max(0.0, news_volume)
    sentiment_score = float(srow["sentiment_score"])
    sentiment_score = _clamp(sentiment_score, -1.0, 1.0)

    disp_raw = None
    if "sentiment_dispersion" in srow.index:
        disp_raw = srow["sentiment_dispersion"]
    has_disp = disp_raw is not None and str(disp_raw).strip() != "" and not pd.isna(disp_raw)
    if has_disp:
        dispersion = max(0.0, float(pd.to_numeric(disp_raw, errors="coerce") or 0.0))
        disagreement_score = _disagreement_from_dispersion(dispersion)
    else:
        dispersion = float("nan")
        disagreement_score = 15.0

    vol_n = _saturation_volume(news_volume)
    mag_n = _sentiment_magnitude(sentiment_score)
    sec_p = _sector_component(float(hrow["sector_heat_percentile"]))
    sentiment_heat_score = _clamp(0.35 * vol_n + 0.35 * mag_n + 0.30 * sec_p, 0.0, 100.0)

    ret_short = float(prow["ret_short"])
    ret_bench = float(prow["ret_bench_short"])
    volat = max(0.0, float(prow["volatility_short"]))
    excess = ret_short - ret_bench
    price_confirmation_score = _price_confirmation(ret_short, ret_bench, volat)

    overheat_risk = bool(
        sentiment_heat_score >= OVERHEAT_HEAT_MIN
        and price_confirmation_score <= OVERHEAT_CONFIRM_MAX
        and excess < OVERHEAT_EXCESS_MAX
    )

    evidence: List[str] = [
        f"sentiment_heat={sentiment_heat_score:.1f} 组成: vol_sat={vol_n:.1f}, |sent|×100={mag_n:.1f}, sector={sec_p:.1f}",
        f"disagreement={disagreement_score:.1f}"
        + (f" (dispersion={dispersion:.3f})" if has_disp else " (无 dispersion，取默认低分)"),
        f"price_confirmation={price_confirmation_score:.1f}, excess_ret={excess:.4f}",
        f"规则: overheat 需 heat≥{OVERHEAT_HEAT_MIN}, confirm≤{OVERHEAT_CONFIRM_MAX}, excess<{OVERHEAT_EXCESS_MAX}",
    ]
    if "sector_breadth" in hrow.index:
        br = hrow["sector_breadth"]
        if br is not None and not pd.isna(br):
            evidence.append(f"sector_breadth={float(br):.3f}")

    uncertainty: List[str] = []
    if not has_disp:
        uncertainty.append("未提供 sentiment_dispersion，分歧分仅为占位，解释力弱。")
    if len(sentiment_features) > 1 or len(price_features) > 1 or len(sector_heat_features) > 1:
        uncertainty.append("输入多行，仅使用每组第一行；横截面比较需在调用方完成。")
    uncertainty.append("若后续放量上行并持续跑赢基准，则过热结构可快速失效。")

    return SentimentReflexivityResult(
        sentiment_heat_score=round(sentiment_heat_score, 2),
        disagreement_score=round(disagreement_score, 2),
        price_confirmation_score=round(price_confirmation_score, 2),
        overheat_risk=overheat_risk,
        evidence=tuple(evidence),
        uncertainty=tuple(uncertainty),
    )

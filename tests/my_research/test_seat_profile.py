# -*- coding: utf-8 -*-
"""seat_profile：Mock 事件级 DataFrame，无网络、不写 data/。"""

from __future__ import annotations

import pandas as pd
import pytest

from src.my_research.seat_profile import build_seat_profiles


def _base_row(
    *,
    seat: str,
    td: str,
    side: str = "0",
    fr1: float,
    fr3: float,
    fr5: float,
    valid: bool,
    sector: str | None = None,
):
    r = {
        "event_id": f"{td}|{seat}|x",
        "ts_code": "600000.SH",
        "trade_date": td,
        "seat_name": seat,
        "side": side,
        "net_buy": 100.0,
        "forward_return_1d": fr1,
        "forward_return_3d": fr3,
        "forward_return_5d": fr5,
        "excess_return_3d": 0.0,
        "sample_valid": valid,
        "warnings": [],
    }
    if sector is not None:
        r["sector"] = sector
    return r


def test_insufficient_sample():
    """有效样本为 0 → insufficient；均值NaN 或无关。"""
    df = pd.DataFrame(
        [
            _base_row(seat="席位甲", td="20260106", fr1=0.01, fr3=0.02, fr5=0.03, valid=False),
            _base_row(seat="席位甲", td="20260107", fr1=0.01, fr3=0.02, fr5=0.03, valid=False),
        ]
    )
    out = build_seat_profiles(df)
    r = out.iloc[0]
    assert r["confidence_level"] == "insufficient"
    assert r["total_events"] == 2
    assert pd.isna(r["avg_forward_return_3d"])


def test_recent_decay():
    """前期 fr3 高、近期 N 条低 → recent_performance 低于全样本 avg_forward_return_3d。"""
    rows = []
    # 9 条历史偏高，日期早于后 3 条
    for i in range(9):
        d = f"202601{10 + i:02d}"
        rows.append(
            _base_row(
                seat="游资A",
                td=d,
                fr1=0.01,
                fr3=0.10,
                fr5=0.10,
                valid=True,
            )
        )
    for i in range(3):
        d = f"202601{25 + i:02d}"
        rows.append(
            _base_row(
                seat="游资A",
                td=d,
                fr1=0.01,
                fr3=-0.08,
                fr5=-0.08,
                valid=True,
            )
        )
    df = pd.DataFrame(rows)
    out = build_seat_profiles(df, recent_n=3)
    r = out.iloc[0]
    assert r["avg_forward_return_3d"] == pytest.approx((9 * 0.10 + 3 * -0.08) / 12)
    assert r["recent_performance"] == pytest.approx(-0.08)
    assert r["recent_performance"] < r["avg_forward_return_3d"]


def test_positive_returns():
    df = pd.DataFrame(
        [
            _base_row(seat="买席", td="20260106", fr1=0.02, fr3=0.05, fr5=0.07, valid=True),
            _base_row(seat="买席", td="20260107", fr1=0.01, fr3=0.01, fr5=0.02, valid=True),
            _base_row(seat="买席", td="20260108", fr1=0.01, fr3=0.02, fr5=0.03, valid=True),
        ]
    )
    out = build_seat_profiles(df)
    r = out.iloc[0]
    assert r["avg_forward_return_3d"] > 0
    assert r["win_rate_3d"] == 1.0
    assert r["confidence_level"] == "low"


def test_negative_returns():
    df = pd.DataFrame(
        [
            _base_row(seat="卖席", td="20260106", fr1=-0.01, fr3=-0.04, fr5=-0.05, valid=True),
            _base_row(seat="卖席", td="20260107", fr1=-0.02, fr3=-0.02, fr5=-0.03, valid=True),
        ]
    )
    out = build_seat_profiles(df)
    r = out.iloc[0]
    assert r["avg_forward_return_3d"] < 0
    assert r["win_rate_3d"] == 0.0


def test_one_day_tour_risk():
    df = pd.DataFrame(
        [
            _base_row(seat="接席", td="20260106", fr1=0.05, fr3=-0.02, fr5=0.0, valid=True),
            _base_row(seat="接席", td="20260107", fr1=0.04, fr3=-0.01, fr5=0.0, valid=True),
            _base_row(seat="接席", td="20260108", fr1=0.01, fr3=0.05, fr5=0.05, valid=True),
            _base_row(seat="接席", td="20260109", fr1=0.01, fr3=0.02, fr5=0.02, valid=True),
        ]
    )
    out = build_seat_profiles(df, one_day_tour_fr1_pct=0.03, one_day_tour_fr3_max=0.0)
    r = out.iloc[0]
    # 前两行满足 fr1>0.03 且 fr3<=0
    assert r["one_day_tour_risk"] == pytest.approx(0.5)


def test_preferred_sectors():
    df = pd.DataFrame(
        [
            _base_row(
                seat="混席", td="20260106", fr1=0.01, fr3=0.01, fr5=0.02, valid=True, sector="银行"
            ),
            _base_row(
                seat="混席", td="20260107", fr1=0.01, fr3=0.01, fr5=0.02, valid=True, sector="银行"
            ),
            _base_row(
                seat="混席", td="20260108", fr1=0.01, fr3=0.01, fr5=0.02, valid=True, sector="地产"
            ),
        ]
    )
    out = build_seat_profiles(df)
    assert out.iloc[0]["preferred_sectors"] == ["银行", "地产"]


def test_missing_required_columns():
    df = pd.DataFrame([{"seat_name": "x", "trade_date": "20260106"}])
    with pytest.raises(ValueError, match="缺少列"):
        build_seat_profiles(df)


def test_valid_ratio_downgrades_confidence():
    """effective_n 够高但 total 中有效占比 <30% → 降一级。"""
    dr = pd.date_range("2026-01-01", periods=40).strftime("%Y%m%d").tolist()
    rows = [
        _base_row(
            seat="席位乙",
            td=dr[i],
            fr1=0.01,
            fr3=0.02,
            fr5=0.03,
            valid=(i < 10),
        )
        for i in range(40)
    ]
    df = pd.DataFrame(rows)
    out = build_seat_profiles(df, min_events_for_full_confidence=30)
    r = out.iloc[0]
    assert r["total_events"] == 40
    assert int(df["sample_valid"].sum()) == 10
    # raw: 10 < 30 → medium；占比 10/40=0.25 < 0.3 → downgrade → low
    assert r["confidence_level"] == "low"


def test_empty_input():
    out = build_seat_profiles(pd.DataFrame())
    assert len(out) == 0
    assert "seat_name" in out.columns

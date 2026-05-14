# -*- coding: utf-8 -*-
"""lhb_event_study：Mock DataFrame，无网络、无 Tushare、不写 data/。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.my_research.lhb_event_study import compute_lhb_forward_returns


def _daily_8d():
    """T=20260108，close 10；T+1=11，T+3=13，T+5=15 — fr1=0.1, fr3=0.3, fr5=0.5"""
    days = ["20260106", "20260107", "20260108", "20260109", "20260110", "20260111", "20260112", "20260113"]
    closes = [10.0, 10.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    return pd.DataFrame(
        {"ts_code": ["600000.SH"] * len(days), "trade_date": days, "close": closes}
    )


def test_normal_forward_and_excess_sector():
    lhb = pd.DataFrame(
        [
            {
                "trade_date": "20260108",
                "ts_code": "600000.SH",
                "seat_name": "测试席位",
                "side": "0",
                "net_buy": 1e6,
            }
        ]
    )
    daily = _daily_8d()
    sector = pd.DataFrame(
        {
            "ts_code": ["600000.SH"] * 8,
            "trade_date": daily["trade_date"],
            "benchmark_close": [100.0, 100.0, 100.0, 105.0, 106.0, 110.0, 111.0, 112.0],
        }
    )
    out = compute_lhb_forward_returns(lhb, daily, sector_df=sector)
    assert len(out) == 1
    r = out.iloc[0]
    assert r["forward_return_1d"] == pytest.approx(0.1)
    assert r["forward_return_3d"] == pytest.approx(0.3)
    assert r["forward_return_5d"] == pytest.approx(0.5)
    # bench T+3: 110/100 - 1 = 0.1
    assert r["excess_return_3d"] == pytest.approx(0.2)
    assert r["sample_valid"]
    assert r["warnings"] == []


def test_excess_market_gate_fallback():
    lhb = pd.DataFrame(
        [
            {
                "trade_date": "20260108",
                "ts_code": "600000.SH",
                "seat_name": "席位A",
                "side": 0,
                "net_buy": 100.0,
            }
        ]
    )
    daily = _daily_8d()
    mg = pd.DataFrame(
        {
            "trade_date": daily["trade_date"],
            "index_close": [1000.0, 1000.0, 1000.0, 1010.0, 1020.0, 1100.0, 1040.0, 1050.0],
        }
    )
    out = compute_lhb_forward_returns(lhb, daily, market_gate_df=mg)
    r = out.iloc[0]
    assert r["forward_return_3d"] == pytest.approx(0.3)
    # bench 1100/1000 - 1 = 0.1
    assert r["excess_return_3d"] == pytest.approx(0.2)
    assert r["sample_valid"]


def test_missing_forward_5d():
    lhb = pd.DataFrame(
        [
            {
                "trade_date": "20260108",
                "ts_code": "600000.SH",
                "seat_name": "S",
                "side": "0",
                "net_buy": 1.0,
            }
        ]
    )
    days = ["20260106", "20260107", "20260108", "20260109", "20260110", "20260111"]
    daily = pd.DataFrame(
        {
            "ts_code": ["600000.SH"] * len(days),
            "trade_date": days,
            "close": [10.0, 10.0, 10.0, 11.0, 12.0, 13.0],
        }
    )
    out = compute_lhb_forward_returns(lhb, daily)
    r = out.iloc[0]
    assert r["forward_return_3d"] == pytest.approx(0.3)
    assert np.isnan(r["forward_return_5d"])
    assert not r["sample_valid"]
    assert "missing_forward_5d" in r["warnings"]


def test_event_date_not_in_daily():
    lhb = pd.DataFrame(
        [
            {
                "trade_date": "20260199",
                "ts_code": "600000.SH",
                "seat_name": "S",
                "side": "0",
                "net_buy": 1.0,
            }
        ]
    )
    out = compute_lhb_forward_returns(lhb, _daily_8d())
    r = out.iloc[0]
    assert all(np.isnan(r[x]) for x in ["forward_return_1d", "forward_return_3d", "forward_return_5d"])
    assert not r["sample_valid"]
    assert "event_date_not_in_daily" in r["warnings"]


def test_missing_close_event_day():
    daily = _daily_8d().copy()
    daily.loc[daily["trade_date"] == "20260108", "close"] = np.nan
    lhb = pd.DataFrame(
        [
            {
                "trade_date": "20260108",
                "ts_code": "600000.SH",
                "seat_name": "S",
                "side": "0",
                "net_buy": 1.0,
            }
        ]
    )
    out = compute_lhb_forward_returns(lhb, daily)
    r = out.iloc[0]
    assert not r["sample_valid"]
    assert "missing_close_on_event_day" in r["warnings"]


def test_missing_lhb_columns():
    lhb = pd.DataFrame([{"trade_date": "20260108", "ts_code": "600000.SH"}])
    with pytest.raises(ValueError, match="缺少列"):
        compute_lhb_forward_returns(lhb, _daily_8d())


def test_empty_events():
    out = compute_lhb_forward_returns(pd.DataFrame(), _daily_8d())
    assert len(out) == 0
    assert list(out.columns) == [
        "event_id",
        "ts_code",
        "trade_date",
        "seat_name",
        "side",
        "net_buy",
        "forward_return_1d",
        "forward_return_3d",
        "forward_return_5d",
        "excess_return_3d",
        "sample_valid",
        "warnings",
    ]


def test_multi_row_event_id():
    lhb = pd.DataFrame(
        [
            {
                "trade_date": "20260108",
                "ts_code": "600000.SH",
                "seat_name": "S1",
                "side": "0",
                "net_buy": 1.0,
            },
            {
                "trade_date": "20260108",
                "ts_code": "600000.SH",
                "seat_name": "S2",
                "side": "1",
                "net_buy": 2.0,
            },
        ]
    )
    out = compute_lhb_forward_returns(lhb, _daily_8d())
    assert out.iloc[0]["event_id"].endswith("|0")
    assert out.iloc[1]["event_id"].endswith("|1")
    assert out.iloc[0]["seat_name"] == "S1"
    assert out.iloc[1]["seat_name"] == "S2"


def test_sector_priority_over_market():
    """sector 有该 ts 则优先；sector 在该日内缺失则退回 market。"""
    lhb = pd.DataFrame(
        [
            {
                "trade_date": "20260108",
                "ts_code": "600000.SH",
                "seat_name": "S",
                "side": "0",
                "net_buy": 1.0,
            }
        ]
    )
    daily = _daily_8d()
    sector = pd.DataFrame(
        {
            "ts_code": ["600000.SH"] * 8,
            "trade_date": daily["trade_date"],
            "benchmark_close": [100.0, 100.0, 100.0, 100.0, 100.0, 120.0, 120.0, 120.0],
        }
    )
    mg = pd.DataFrame(
        {
            "trade_date": daily["trade_date"],
            "index_close": [1000.0, 1000.0, 1000.0, 1010.0, 1020.0, 1100.0, 1040.0, 1050.0],
        }
    )
    out = compute_lhb_forward_returns(lhb, daily, sector_df=sector, market_gate_df=mg)
    r = out.iloc[0]
    # sector T+3: 120/100 - 1 = 0.2, excess = 0.3 - 0.2 = 0.1
    assert r["excess_return_3d"] == pytest.approx(0.1)
# -*- coding: utf-8 -*-
"""candidate_scanner v1：Mock DataFrame，无网络、无 Tushare。"""

from __future__ import annotations

import pandas as pd
import pytest

from src.my_research.candidate_scanner import (
    CandidateResult,
    scan_candidates,
    results_to_dataframe,
)


def _base_frames(*, anchor: str = "20260513"):
    stock_basic = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "name": "正常票",
                "market": "主板",
                "industry": "银行",
                "list_status": "L",
                "delist_date": None,
            },
        ]
    )
    daily = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "trade_date": anchor,
                "close": 10.0,
                "pct_chg": 3.5,
                "amount": 500000.0,
            },
        ]
    )
    daily_basic = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "trade_date": anchor,
                "turnover_rate": 0.02,
                "circ_mv": 500000.0,
            },
        ]
    )
    stk_limit = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "trade_date": anchor,
                "up_limit": 11.0,
                "down_limit": 9.0,
            },
        ]
    )
    return stock_basic, daily, daily_basic, stk_limit


def test_normal_candidate():
    sb, d, db, sl = _base_frames()
    hot = frozenset({"银行"})
    res = scan_candidates(
        anchor_trade_date="20260513",
        stock_basic=sb,
        daily=d,
        daily_basic=db,
        stk_limit=sl,
        hot_sectors=hot,
    )
    assert len(res) == 1
    r = res[0]
    assert isinstance(r, CandidateResult)
    assert r.ts_code == "600000.SH"
    assert r.name == "正常票"
    assert r.board == "main"
    assert r.sector == "银行"
    assert r.watch_allowed is True
    assert r.trade_allowed is False
    assert r.score > 0
    assert len(r.evidence) >= 1
    assert "sector_hot" in r.risk_tags
    df = results_to_dataframe(res)
    assert len(df) == 1
    assert not bool(df.iloc[0]["trade_allowed"])


def test_st_excluded():
    sb, d, db, sl = _base_frames()
    sb.loc[0, "name"] = "*ST 淘汰"
    res = scan_candidates(
        anchor_trade_date="20260513",
        stock_basic=sb,
        daily=d,
        daily_basic=db,
        stk_limit=sl,
    )
    assert res == []


def test_suspend_excluded():
    sb, d, db, sl = _base_frames()
    suspend = pd.DataFrame(
        [{"ts_code": "600000.SH", "trade_date": "20260513", "suspend_type": "S"}]
    )
    res = scan_candidates(
        anchor_trade_date="20260513",
        stock_basic=sb,
        daily=d,
        daily_basic=db,
        stk_limit=sl,
        suspend=suspend,
    )
    assert res == []


def test_low_turnover_excluded():
    sb, d, db, sl = _base_frames()
    db.loc[0, "turnover_rate"] = 0.0001
    res = scan_candidates(
        anchor_trade_date="20260513",
        stock_basic=sb,
        daily=d,
        daily_basic=db,
        stk_limit=sl,
    )
    assert res == []


def test_low_circ_mv_excluded():
    sb, d, db, sl = _base_frames()
    db.loc[0, "circ_mv"] = 1000.0
    res = scan_candidates(
        anchor_trade_date="20260513",
        stock_basic=sb,
        daily=d,
        daily_basic=db,
        stk_limit=sl,
    )
    assert res == []


def test_delisting_risk_name_excluded():
    sb, d, db, sl = _base_frames()
    sb.loc[0, "name"] = "某退整理"
    res = scan_candidates(
        anchor_trade_date="20260513",
        stock_basic=sb,
        daily=d,
        daily_basic=db,
        stk_limit=sl,
    )
    assert res == []


def test_non_listed_board_excluded():
    sb, d, db, sl = _base_frames()
    sb.loc[0, "market"] = "北交所"
    res = scan_candidates(
        anchor_trade_date="20260513",
        stock_basic=sb,
        daily=d,
        daily_basic=db,
        stk_limit=sl,
    )
    assert res == []


def test_missing_columns_raises():
    sb, d, db, sl = _base_frames()
    bad = db.drop(columns=["circ_mv"])
    with pytest.raises(ValueError, match="missing columns"):
        scan_candidates(
            anchor_trade_date="20260513",
            stock_basic=sb,
            daily=d,
            daily_basic=bad,
            stk_limit=sl,
        )

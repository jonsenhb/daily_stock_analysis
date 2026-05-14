# -*- coding: utf-8 -*-
"""cn_limit_sentiment：Mock Tushare，无网络。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd

from src.market_analyzer import MarketOverview
from src.my_research.cn_limit_sentiment import (
    enrich_overview_cn_limit_sentiment,
    resolve_cn_trade_date_for_limit_snapshot,
)
from src.my_research.tushare_research_client import TushareResearchClient

_CN = ZoneInfo("Asia/Shanghai")


def test_resolve_anchor_uses_previous_day_before_close():
    pro = MagicMock()

    def query(api_name, fields="", **kwargs):
        if api_name == "trade_cal":
            return pd.DataFrame(
                {
                    "cal_date": ["20241122", "20241125"],
                    "is_open": ["1", "1"],
                }
            )
        return pd.DataFrame()

    pro.query.side_effect = query
    client = TushareResearchClient(pro)
    now = datetime(2024, 11, 25, 10, 30, tzinfo=_CN)
    assert resolve_cn_trade_date_for_limit_snapshot(client, now_cn=now) == "20241122"


def test_resolve_anchor_same_day_after_close():
    pro = MagicMock()

    def query(api_name, fields="", **kwargs):
        if api_name == "trade_cal":
            return pd.DataFrame({"cal_date": ["20241125"], "is_open": ["1"]})
        return pd.DataFrame()

    pro.query.side_effect = query
    client = TushareResearchClient(pro)
    now = datetime(2024, 11, 25, 16, 0, tzinfo=_CN)
    assert resolve_cn_trade_date_for_limit_snapshot(client, now_cn=now) == "20241125"


@patch("src.my_research.cn_limit_sentiment.TushareResearchClient")
def test_enrich_writes_overview(mock_client_cls):
    mock_pro = MagicMock()

    def query(api_name, fields="", **kwargs):
        if api_name == "trade_cal":
            return pd.DataFrame({"cal_date": ["20241125"], "is_open": ["1"]})
        if api_name == "limit_list_d":
            return pd.DataFrame([{"ts_code": "x"}], columns=["ts_code"])
        if api_name == "limit_step":
            return pd.DataFrame(
                [
                    {"ts_code": "000833.SZ", "name": "粤桂股份", "trade_date": "20241125", "nums": "11"},
                    {"ts_code": "002611.SZ", "name": "东方精工", "trade_date": "20241125", "nums": "8"},
                ]
            )
        return pd.DataFrame()

    mock_pro.query.side_effect = query
    mock_client_cls.return_value = TushareResearchClient(mock_pro)

    ov = MarketOverview(date="2024-11-25")
    enrich_overview_cn_limit_sentiment(ov, token="dummy_token")
    assert ov.tushare_limit_trade_date == "20241125"
    assert ov.blown_limit_count == 1
    assert ov.limit_ladder_max_streak == 11
    assert ov.limit_ladder_ge3_count == 2
    assert ov.limit_step_top[0]["nums"] == 11


def test_enrich_empty_token_noop():
    ov = MarketOverview(date="2024-11-25")
    enrich_overview_cn_limit_sentiment(ov, token="  ")
    assert ov.tushare_limit_trade_date is None

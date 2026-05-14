# -*- coding: utf-8 -*-
"""TushareResearchClient 单元测试：仅 Mock pro.query，无网络、无 data/ 写入。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.my_research.tushare_research_client import (
    DEFAULT_FIELDS,
    TushareResearchApiError,
    TushareResearchClient,
    TushareResearchPermissionError,
    _sanitize_for_log,
)


@pytest.fixture
def mock_pro():
    p = MagicMock()
    p.query.return_value = pd.DataFrame([{"a": 1}])
    return p


def test_constructor_requires_xor():
    with pytest.raises(ValueError, match="必须且仅能指定"):
        TushareResearchClient()
    pro = MagicMock()
    with pytest.raises(ValueError, match="必须且仅能指定"):
        TushareResearchClient(pro, token="x")


def test_get_trade_calendar(mock_pro):
    c = TushareResearchClient(mock_pro)
    df = c.get_trade_calendar(start_date="20240101", end_date="20240131")
    assert len(df) == 1
    mock_pro.query.assert_called_once()
    args, kwargs = mock_pro.query.call_args
    assert args[0] == "trade_cal"
    assert "cal_date" in kwargs["fields"]


def test_get_limit_list_uses_limit_list_d(mock_pro):
    c = TushareResearchClient(mock_pro)
    c.get_limit_list(trade_date="20240510", limit_type="U")
    assert mock_pro.query.call_args[0][0] == "limit_list_d"


def test_default_fields_when_none(mock_pro):
    c = TushareResearchClient(mock_pro)
    c.get_top_list(trade_date="20240510")
    assert mock_pro.query.call_args[1]["fields"] == DEFAULT_FIELDS["top_list"]


def test_custom_fields_override(mock_pro):
    c = TushareResearchClient(mock_pro)
    c.get_top_list(trade_date="20240510", fields="trade_date,ts_code")
    assert mock_pro.query.call_args[1]["fields"] == "trade_date,ts_code"


def test_none_params_omitted(mock_pro):
    c = TushareResearchClient(mock_pro)
    c.get_daily(ts_code="600519.SH", trade_date="20240510")
    kwargs = mock_pro.query.call_args[1]
    assert "start_date" not in kwargs
    assert kwargs["ts_code"] == "600519.SH"


def test_empty_dataframe_ok(mock_pro):
    mock_pro.query.return_value = pd.DataFrame()
    c = TushareResearchClient(mock_pro)
    df = c.get_stock_basic(list_status="L")
    assert df.empty


def test_permission_error_mapping(mock_pro):
    mock_pro.query.side_effect = Exception("您的积分不足")
    c = TushareResearchClient(mock_pro)
    with pytest.raises(TushareResearchPermissionError):
        c.get_daily(trade_date="20240510")


def test_generic_api_error(mock_pro):
    mock_pro.query.side_effect = Exception("network down")
    c = TushareResearchClient(mock_pro)
    with pytest.raises(TushareResearchApiError) as ei:
        c.get_daily(trade_date="20240510")
    assert not isinstance(ei.value, TushareResearchPermissionError)


def test_non_dataframe_raises(mock_pro):
    mock_pro.query.return_value = None
    c = TushareResearchClient(mock_pro)
    with pytest.raises(TushareResearchApiError, match="非 DataFrame"):
        c.get_suspend_d(trade_date="20200312", suspend_type="S")


def test_sanitize_for_log_redacts_token():
    assert _sanitize_for_log({"token": "secret", "x": 1})["token"] == "<redacted>"


def test_get_index_daily_requires_ts_code_in_call(mock_pro):
    c = TushareResearchClient(mock_pro)
    c.get_index_daily(ts_code="000300.SH", start_date="20240101", end_date="20240110")
    assert mock_pro.query.call_args[0][0] == "index_daily"
    assert mock_pro.query.call_args[1]["ts_code"] == "000300.SH"


@pytest.mark.parametrize(
    "method,api,kwargs",
    [
        ("get_stock_basic", "stock_basic", {"list_status": "L"}),
        ("get_daily_basic", "daily_basic", {"trade_date": "20240510"}),
        ("get_index_dailybasic", "index_dailybasic", {"trade_date": "20240510"}),
        ("get_stk_limit", "stk_limit", {"trade_date": "20240601"}),
        ("get_limit_step", "limit_step", {"trade_date": "20241125"}),
        ("get_limit_list_ths", "limit_list_ths", {"trade_date": "20241125"}),
        ("get_limit_cpt_list", "limit_cpt_list", {"trade_date": "20241127"}),
        ("get_top_inst", "top_inst", {"trade_date": "20240510"}),
        ("get_moneyflow_ind_ths", "moneyflow_ind_ths", {"trade_date": "20240927"}),
        ("get_moneyflow_cnt_ths", "moneyflow_cnt_ths", {"trade_date": "20250320"}),
        ("get_moneyflow_ths", "moneyflow_ths", {"trade_date": "20241011"}),
    ],
)
def test_method_routes_api(mock_pro, method, api, kwargs):
    c = TushareResearchClient(mock_pro)
    getattr(c, method)(**kwargs)
    assert mock_pro.query.call_args[0][0] == api

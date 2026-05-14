# -*- coding: utf-8 -*-
"""
Tushare 研究用封装：仅服务 src/my_research，不读 .env。

- 依赖与 data_provider/tushare_fetcher._TushareHttpClient 相同的 ``query(api_name, fields=..., **params)`` 契约。
- get_limit_list 对应官方接口 limit_list_d（涨跌停列表-新）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import pandas as pd

from data_provider.tushare_fetcher import _TushareHttpClient

logger = logging.getLogger(__name__)

# 默认 fields 与 docs/my_research/tushare_data_plan.md §3 推荐字段一致；传 fields= 可覆盖。
DEFAULT_FIELDS: Dict[str, str] = {
    "trade_cal": "exchange,cal_date,is_open,pretrade_date",
    "stock_basic": "ts_code,symbol,name,area,industry,market,exchange,list_status,list_date,delist_date",
    "daily": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
    "daily_basic": "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,total_mv,circ_mv,float_share,free_share",
    "index_daily": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
    "index_dailybasic": "ts_code,trade_date,total_mv,float_mv,turnover_rate,turnover_rate_f,pe,pe_ttm,pb",
    "stk_limit": "trade_date,ts_code,pre_close,up_limit,down_limit",
    "limit_list_d": "trade_date,ts_code,industry,name,close,pct_chg,amount,turnover_ratio,fd_amount,first_time,last_time,open_times,up_stat,limit_times,limit",
    "limit_list_ths": "ts_code,trade_date,name,pct_chg,open_num,lu_desc,limit_type,tag,status,first_lu_time,last_lu_time,turnover_rate,turnover,market_type",
    "limit_cpt_list": "ts_code,name,trade_date,days,up_stat,cons_nums,up_nums,pct_chg,rank",
    "top_list": "trade_date,ts_code,name,close,pct_change,turnover_rate,amount,l_buy,l_sell,l_amount,net_amount,net_rate,amount_rate,float_values,reason",
    "top_inst": "trade_date,ts_code,exalter,side,buy,sell,buy_rate,sell_rate,net_buy,reason",
    "moneyflow_ind_ths": "trade_date,ts_code,industry,close,pct_change,company_num,net_amount,net_buy_amount,net_sell_amount",
    "moneyflow_cnt_ths": "trade_date,ts_code,name,pct_change,company_num,net_amount,net_buy_amount,net_sell_amount,industry_index",
    "moneyflow_ths": "trade_date,ts_code,name,pct_change,latest,net_amount,net_d5_amount,buy_lg_amount,buy_lg_amount_rate",
    "suspend_d": "ts_code,trade_date,suspend_timing,suspend_type",
}


class TushareResearchApiError(RuntimeError):
    """Tushare API 或 query 层返回/抛出的错误（已剥离 token）。"""


class TushareResearchPermissionError(TushareResearchApiError):
    """启发式：错误信息含权限/积分/permission 等（以官网 msg 为准）。"""


def _drop_none(params: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in params.items() if v is not None}


def _sanitize_for_log(params: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in params.items():
        lk = str(k).lower()
        if lk in ("token", "tushare_token", "api_key", "secret"):
            out[k] = "<redacted>"
        else:
            out[k] = v
    return out


def _wrap_exception(exc: Exception) -> TushareResearchApiError:
    msg = str(exc).strip() or type(exc).__name__
    low = msg.lower()
    if (
        "权限" in msg
        or "积分" in msg
        or "permission" in low
        or "point" in low
        or "not enough" in low
    ):
        return TushareResearchPermissionError(msg)
    return TushareResearchApiError(msg)


class TushareResearchClient:
    """
    Args:
        pro: 已实现 ``query(api_name, fields="", **params) -> pd.DataFrame`` 的客户端（测试请用 Mock）。
        token: 与 pro 二选一；不读 .env，由调用方传入明文字符串。
    """

    def __init__(
        self,
        pro: Any | None = None,
        *,
        token: Optional[str] = None,
        timeout: int = 30,
        api_url: str = "http://api.tushare.pro",
    ) -> None:
        if (pro is None) == (token is None):
            raise ValueError("必须且仅能指定 pro 或 token 之一")
        if token is not None:
            if not str(token).strip():
                raise ValueError("token 不能为空")
            self._pro = _TushareHttpClient(token=str(token).strip(), timeout=timeout, api_url=api_url)
        else:
            self._pro = pro

    def _call(self, api_name: str, params: Dict[str, Any], *, fields: Optional[str]) -> pd.DataFrame:
        payload = _drop_none(params)
        f = DEFAULT_FIELDS.get(api_name, "") if fields is None else fields
        log_params = _sanitize_for_log({**payload, "fields": f or "(none)"})
        try:
            df = self._pro.query(api_name, fields=f or "", **payload)
        except Exception as exc:
            raise _wrap_exception(exc) from exc
        if not isinstance(df, pd.DataFrame):
            raise TushareResearchApiError(f"query 返回非 DataFrame: {type(df)!r}")
        n = len(df)
        logger.info(
            "TushareResearchClient api=%s rows=%d params=%s",
            api_name,
            n,
            log_params,
        )
        return df

    def get_trade_calendar(
        self,
        *,
        exchange: str = "",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        is_open: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """trade_cal"""
        return self._call(
            "trade_cal",
            {"exchange": exchange, "start_date": start_date, "end_date": end_date, "is_open": is_open},
            fields=fields,
        )

    def get_stock_basic(
        self,
        *,
        ts_code: Optional[str] = None,
        name: Optional[str] = None,
        market: Optional[str] = None,
        list_status: Optional[str] = None,
        exchange: Optional[str] = None,
        is_hs: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """stock_basic"""
        return self._call(
            "stock_basic",
            {
                "ts_code": ts_code,
                "name": name,
                "market": market,
                "list_status": list_status,
                "exchange": exchange,
                "is_hs": is_hs,
            },
            fields=fields,
        )

    def get_daily(
        self,
        *,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """daily"""
        return self._call(
            "daily",
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "start_date": start_date,
                "end_date": end_date,
            },
            fields=fields,
        )

    def get_daily_basic(
        self,
        *,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """daily_basic（ts_code 与 trade_date/start_end 组合以官网为准）。"""
        return self._call(
            "daily_basic",
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "start_date": start_date,
                "end_date": end_date,
            },
            fields=fields,
        )

    def get_index_daily(
        self,
        *,
        ts_code: str,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """index_daily：ts_code 必选。"""
        return self._call(
            "index_daily",
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "start_date": start_date,
                "end_date": end_date,
            },
            fields=fields,
        )

    def get_index_dailybasic(
        self,
        *,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """index_dailybasic：trade_date 与 ts_code 至少其一（官网）。"""
        return self._call(
            "index_dailybasic",
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "start_date": start_date,
                "end_date": end_date,
            },
            fields=fields,
        )

    def get_stk_limit(
        self,
        *,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """stk_limit"""
        return self._call(
            "stk_limit",
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "start_date": start_date,
                "end_date": end_date,
            },
            fields=fields,
        )

    def get_limit_list(
        self,
        *,
        trade_date: Optional[str] = None,
        ts_code: Optional[str] = None,
        limit_type: Optional[str] = None,
        exchange: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        涨跌停列表（新）。对应 Tushare Pro API：limit_list_d。
        文档：https://tushare.pro/document/2?doc_id=298
        """
        return self._call(
            "limit_list_d",
            {
                "trade_date": trade_date,
                "ts_code": ts_code,
                "limit_type": limit_type,
                "exchange": exchange,
                "start_date": start_date,
                "end_date": end_date,
            },
            fields=fields,
        )

    def get_limit_list_ths(
        self,
        *,
        trade_date: Optional[str] = None,
        ts_code: Optional[str] = None,
        limit_type: Optional[str] = None,
        market: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """limit_list_ths"""
        return self._call(
            "limit_list_ths",
            {
                "trade_date": trade_date,
                "ts_code": ts_code,
                "limit_type": limit_type,
                "market": market,
                "start_date": start_date,
                "end_date": end_date,
            },
            fields=fields,
        )

    def get_limit_cpt_list(
        self,
        *,
        trade_date: Optional[str] = None,
        ts_code: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """limit_cpt_list"""
        return self._call(
            "limit_cpt_list",
            {
                "trade_date": trade_date,
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date,
            },
            fields=fields,
        )

    def get_top_list(
        self,
        *,
        trade_date: str,
        ts_code: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """top_list：trade_date 必选。"""
        return self._call(
            "top_list",
            {"trade_date": trade_date, "ts_code": ts_code},
            fields=fields,
        )

    def get_top_inst(
        self,
        *,
        trade_date: str,
        ts_code: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """top_inst：trade_date 必选。"""
        return self._call(
            "top_inst",
            {"trade_date": trade_date, "ts_code": ts_code},
            fields=fields,
        )

    def get_moneyflow_ind_ths(
        self,
        *,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """moneyflow_ind_ths"""
        return self._call(
            "moneyflow_ind_ths",
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "start_date": start_date,
                "end_date": end_date,
            },
            fields=fields,
        )

    def get_moneyflow_cnt_ths(
        self,
        *,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """moneyflow_cnt_ths"""
        return self._call(
            "moneyflow_cnt_ths",
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "start_date": start_date,
                "end_date": end_date,
            },
            fields=fields,
        )

    def get_moneyflow_ths(
        self,
        *,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """moneyflow_ths"""
        return self._call(
            "moneyflow_ths",
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "start_date": start_date,
                "end_date": end_date,
            },
            fields=fields,
        )

    def get_suspend_d(
        self,
        *,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        suspend_type: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> pd.DataFrame:
        """suspend_d"""
        return self._call(
            "suspend_d",
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "start_date": start_date,
                "end_date": end_date,
                "suspend_type": suspend_type,
            },
            fields=fields,
        )

# -*- coding: utf-8 -*-
"""trade_journal：临时目录 CSV 与 Mock DataFrame，不读真实 data/journal。"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.my_research.trade_journal import (
    TradeRecord,
    read_trade_journal,
    record_from_mapping,
    records_from_dataframe,
    summary_from_dataframe,
    summary_from_records,
    write_trade_journal,
)


def _row(**kw):
    base = {
        "date": "20260110",
        "ts_code": "600000.SH",
        "name": "测试",
        "side": "buy",
        "price": 10.0,
        "amount": 100.0,
        "position_ratio": 0.1,
        "reason": "计划",
        "plan_id": "p1",
        "is_plan_trade": True,
        "market_score": 60,
        "sector": "银行",
        "emotion_state": "冷静",
        "stop_loss": 9.5,
        "take_profit": 11.0,
        "result_pnl": None,
        "result_pct": None,
        "review": "",
    }
    base.update(kw)
    return base


def test_summary_from_dataframe_plan_and_impulse():
    df = pd.DataFrame(
        [
            _row(is_plan_trade=True, result_pct=2.0, result_pnl=200.0, review="ok"),
            _row(is_plan_trade=True, result_pct=-1.0, result_pnl=-100.0, review="ok"),
            _row(
                is_plan_trade=False,
                ts_code="600001.SH",
                result_pct=1.0,
                result_pnl=50.0,
                review="复盘",
            ),
        ]
    )
    s = summary_from_dataframe(df)
    assert s.total_trades == 3
    assert s.plan_trade_ratio == pytest.approx(2 / 3)
    assert s.impulse_trade_count == 1
    assert s.avg_result_pct == pytest.approx((2.0 - 1.0 + 1.0) / 3)
    assert s.max_loss == pytest.approx(-100.0)


def test_empty_summary():
    s = summary_from_records([])
    assert s.total_trades == 0
    assert s.plan_trade_ratio == 0.0
    assert s.impulse_trade_count == 0
    assert np.isnan(s.avg_result_pct)
    assert s.discipline_score == 100


def test_csv_roundtrip(tmp_path):
    recs = [
        TradeRecord(
            date=date(2026, 1, 10),
            ts_code="600000.SH",
            name="A",
            side="buy",
            price=10.0,
            amount=100.0,
            position_ratio=0.25,
            reason="r",
            plan_id="p",
            is_plan_trade=True,
            market_score=None,
            sector="",
            emotion_state="",
            stop_loss=9.0,
            take_profit=None,
            result_pnl=-50.0,
            result_pct=-0.5,
            review="done",
        )
    ]
    p = tmp_path / "journal.csv"
    write_trade_journal(recs, p)
    back = read_trade_journal(p)
    assert len(back) == 1
    assert back[0].ts_code == "600000.SH"
    assert back[0].side == "buy"
    assert back[0].amount == 100.0
    assert back[0].stop_loss == 9.0


def test_missing_columns_raises():
    df = pd.DataFrame([{"date": "20260110", "ts_code": "x"}])
    with pytest.raises(ValueError, match="缺少列"):
        records_from_dataframe(df)


def test_discipline_and_risk_violations():
    # 重仓无止损 + 已平仓无复盘 + 冲动标签
    df = pd.DataFrame(
        [
            _row(
                is_plan_trade=False,
                position_ratio=0.25,
                stop_loss=None,
                emotion_state="恐慌抛售",
                result_pct=-2.0,
                result_pnl=-200.0,
                review="",
            ),
            _row(
                date="20260111",
                is_plan_trade=True,
                position_ratio=0.1,
                stop_loss=9.0,
                emotion_state="冷静",
                result_pct=1.0,
                result_pnl=100.0,
                review="ok",
            ),
        ]
    )
    s = summary_from_dataframe(df)
    assert s.impulse_trade_count == 1
    assert "no_stop_loss_on_material_exposure" in s.risk_violations
    assert "closed_without_review" in s.risk_violations
    assert "emotional_extreme_in_notes" in s.risk_violations
    assert s.discipline_score < 100
    assert s.discipline_score >= 0


def test_small_sample_caps_discipline_score():
    df = pd.DataFrame([_row(is_plan_trade=True, review="x") for _ in range(3)])
    s = summary_from_dataframe(df)
    assert s.total_trades == 3
    assert s.discipline_score <= 85


def test_record_from_mapping_side_normalization():
    r = record_from_mapping({**_row(), "side": "BUY"})
    assert r.side == "buy"

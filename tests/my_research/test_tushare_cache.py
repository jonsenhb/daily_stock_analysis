# -*- coding: utf-8 -*-
"""tushare_cache 单元测试：临时目录 + mock fetch，无网络、无真实 data/。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.my_research.tushare_cache import (
    DATASET_REQUIRED_FIELDS,
    CacheValidationError,
    MinuteRateLimiter,
    TushareResearchCache,
    normalize_trade_date,
    normalize_ts_code,
)


def test_normalize_trade_date_ok():
    assert normalize_trade_date("20240510") == "20240510"


def test_normalize_trade_date_bad():
    with pytest.raises(ValueError):
        normalize_trade_date("2024-05-10")
    with pytest.raises(ValueError):
        normalize_trade_date("20241301")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("600519", "600519.SH"),
        ("600519.sh", "600519.SH"),
        ("000001.SZ", "000001.SZ"),
        ("SZ000001", "000001.SZ"),
        ("SH600519", "600519.SH"),
        ("688001", "688001.SH"),
        ("300001", "300001.SZ"),
        ("920001.BJ", "920001.BJ"),
        ("HK00700", "00700.HK"),
        ("510050", "510050.SH"),
        ("159919", "159919.SZ"),
    ],
)
def test_normalize_ts_code(raw, expected):
    assert normalize_ts_code(raw) == expected


def test_normalize_ts_code_us_rejected():
    with pytest.raises(ValueError, match="美股"):
        normalize_ts_code("AAPL")


def test_cache_miss_and_hit(tmp_path: Path):
    root = tmp_path / "tcache"
    cache = TushareResearchCache(root, pre_acquire=lambda d: None)
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return pd.DataFrame(
            {
                "trade_date": ["20240510"],
                "ts_code": ["600519.SH"],
                "close": [1700.0],
            }
        )

    df1 = cache.read_or_fetch(
        "top_list",
        {"trade_date": "20240510"},
        fetch,
        fetch_params={"fields": "a,b"},
    )
    assert calls["n"] == 1
    assert len(df1) == 1
    df2 = cache.read_or_fetch(
        "top_list",
        {"trade_date": "20240510"},
        fetch,
        fetch_params={"fields": "a,b"},
    )
    assert calls["n"] == 1
    pd.testing.assert_frame_equal(df1.reset_index(drop=True), df2.reset_index(drop=True))


def test_cache_force_refresh(tmp_path: Path):
    cache = TushareResearchCache(tmp_path / "t3", pre_acquire=lambda d: None)
    seq = iter([1, 2])

    def fetch():
        v = next(seq)
        return pd.DataFrame({"trade_date": ["20240510"], "ts_code": ["600519.SH"], "close": [float(v)]})

    df1 = cache.read_or_fetch("top_list", {"trade_date": "20240510"}, fetch, fetch_params={})
    df2 = cache.read_or_fetch("top_list", {"trade_date": "20240510"}, fetch, fetch_params={}, force=True)
    assert float(df1["close"].iloc[0]) == 1.0
    assert float(df2["close"].iloc[0]) == 2.0


def test_cache_validation_error(tmp_path: Path):
    cache = TushareResearchCache(tmp_path / "t4", pre_acquire=lambda d: None)

    def bad_fetch():
        return pd.DataFrame({"trade_date": ["20240510"]})

    with pytest.raises(CacheValidationError):
        cache.read_or_fetch("top_list", {"trade_date": "20240510"}, bad_fetch, fetch_params={})


def test_param_hash_different_partition_files(tmp_path: Path):
    cache = TushareResearchCache(tmp_path / "t5", pre_acquire=lambda d: None)

    def mk(rows):
        return pd.DataFrame(rows)

    cache.read_or_fetch(
        "top_list",
        {"trade_date": "20240510"},
        lambda: mk([{"trade_date": "20240510", "ts_code": "600519.SH"}]),
        fetch_params={"x": 1},
    )
    cache.read_or_fetch(
        "top_list",
        {"trade_date": "20240510"},
        lambda: mk([{"trade_date": "20240510", "ts_code": "000001.SZ"}]),
        fetch_params={"x": 2},
    )
    pq = list((tmp_path / "t5" / "parquet" / "top_list").glob("*.parquet"))
    assert len(pq) == 2


def test_minute_rate_limiter_window():
    times = [0.0]

    def clock():
        return times[0]

    lim = MinuteRateLimiter(2, clock=clock)
    lim.acquire()
    lim.acquire()
    assert len(lim._times) == 2
    times[0] = 61.0
    lim.acquire()
    assert len(lim._times) <= 2


def test_invalidate_removes_parquet(tmp_path: Path):
    cache = TushareResearchCache(tmp_path / "t6", pre_acquire=lambda d: None)

    def fetch():
        return pd.DataFrame([{"trade_date": "20240510", "ts_code": "600519.SH"}])

    cache.read_or_fetch("top_list", {"trade_date": "20240510"}, fetch, fetch_params={"k": 1})
    pq_dir = tmp_path / "t6" / "parquet" / "top_list"
    assert any(pq_dir.glob("*.parquet"))
    cache.invalidate("top_list", {"trade_date": "20240510"}, fetch_params={"k": 1})
    assert not any(pq_dir.glob("*.parquet"))


def test_dataset_required_fields_nonempty():
    assert "daily" in DATASET_REQUIRED_FIELDS
    assert "top_inst" in DATASET_REQUIRED_FIELDS

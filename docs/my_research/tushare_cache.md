# Tushare Research Cache

面向 `market_gate`、龙虎榜席位画像、候选扫描与事件研究的 **Tushare 研究冷缓存**：明细用 **Parquet**，元数据用 **独立 manifest SQLite**（与 `src/storage.py` 业务库 **不是** 同一文件）。

设计原则见 `docs/my_research/tushare_data_plan.md`。实现：`src/my_research/tushare_cache.py`。拉取接口数据可配合 `src/my_research/tushare_research_client.py`（`query` 封装，不读 `.env`）。

## 目录结构（`cache_root` 由调用方传入）

```text
{cache_root}/
  manifest.sqlite
  parquet/
    {dataset}/
      {partition_id}__{param_hash}.parquet
  tmp/                     # 写入过程中的临时文件（可定期清理）
```

**勿**将 `cache_root` 指向仓库内真实 `data/`，测试请用 `tmp_path`。

## 约定

| 项 | 说明 |
|----|------|
| `trade_date` | 字符串 `YYYYMMDD`，由 `normalize_trade_date()` 校验 |
| `ts_code` | Tushare 后缀大写，如 `600519.SH`；`normalize_ts_code()` 与 `data_provider/tushare_fetcher` 规则对齐 |
| `partition` | 参与路径与去重的键，如 `{"trade_date": "20240510"}`；将排序后拼接为 `partition_id` |
| `fetch_params` | 参与 `param_hash` 的 API 可变参数（`fields`、`limit_type` 等），避免同 partition 不同请求互相覆盖 |

## API 摘要

- `TushareResearchCache(root, rate_limits=..., pre_acquire=...)`
  - `pre_acquire(dataset)` 若提供，则 **替代** 内置分钟滑动窗口限流（适合 fetch 内已限流的场景）。
- `read_or_fetch(dataset, partition, fetch_fn, *, fetch_params=None, required_columns=None, force=False) -> pd.DataFrame`
  - `fetch_fn`：**无参数** 的可调用对象，由调用方用闭包捕获 Tushare 请求参数。
  - `required_columns` 默认取 `DATASET_REQUIRED_FIELDS[dataset]`（与接口矩阵推荐字段对齐的子集）。

## 限流默认值

`DEFAULT_RATE_LIMIT_PER_MINUTE` 为保守占位（如 `stock_basic`: 50，`daily`: 500），**以 Tushare 官网为准**，可在构造时传入 `rate_limits` 覆盖。

## 接入 `TushareFetcher`（示意，非自动接线）

```python
from pathlib import Path
import pandas as pd
from src.my_research.tushare_cache import TushareResearchCache, normalize_trade_date

# fetcher = 已初始化的 TushareFetcher 实例（主流程中已有）
cache = TushareResearchCache(Path("/your/cache/root"))

def load_top_list(trade_date: str) -> pd.DataFrame:
    d = normalize_trade_date(trade_date)
    return cache.read_or_fetch(
        "top_list",
        {"trade_date": d},
        fetch_fn=lambda: fetcher._call_api_with_rate_limit("top_list", trade_date=d),
        fetch_params={"trade_date": d},
    )
```

实际字段与权限以官网为准；研究开发阶段请继续遵守 `tushare_data_plan` 中的积分与更新时点说明。

## 测试

```bash
python -m pytest tests/my_research/test_tushare_cache.py -q
python -m py_compile src/my_research/tushare_cache.py
```

依赖：`pyarrow`（`requirements.txt`）。

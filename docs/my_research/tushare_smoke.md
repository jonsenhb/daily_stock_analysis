# Tushare 手动烟测（`tushare_smoke`）

本脚本用于在本机 **确认 Tushare Pro 核心接口是否可用**（约 15000 积分场景），**不写入**仓库 `data/`，**不读取、不修改** `.env`。

## 前置

1. 在 shell 中设置 Token（**勿**提交到仓库、勿粘贴到日志）：

   ```bash
   export TUSHARE_TOKEN="你的token"
   ```

2. 若访问 `api.tushare.pro` 受代理影响，可按本机习惯设置 `NO_PROXY`（与 DGX 说明一致）。

3. 在仓库根目录执行：

   ```bash
   cd /path/to/daily_stock_analysis
   conda activate stock   # 若使用 conda
   python scripts_local/tushare_smoke.py
   ```

## 行为说明

- **默认**：仅请求小样本的「基础」接口：`trade_cal`、`stock_basic`、`daily`、`daily_basic`、`index_daily`。
- **`--extended`**：额外请求 `top_list`、`top_inst`、`moneyflow_*`、`limit_list_d`（含涨停 `U` 与炸板 `Z`）、`limit_step`（连板天梯）、`limit_list_ths`、`limit_cpt_list`、`stk_limit`、`suspend_d`（权限/积分以账号为准）。
- **锚定交易日**：用于单日类接口；默认取「上海时区下最近一个工作日（周一至周五）」，也可：
  - `export TUSHARE_SMOKE_TRADE_DATE=20240510`，或
  - `python scripts_local/tushare_smoke.py --date 20240510`（与 **`--trade-date`** 等价）
- **样本量**：日期区间约 7 自然日、股票默认 `600519.SH`、指数默认 `000300.SH`；可用 `--stock-ts` / `--index-ts` 覆盖。

## 输出与退出码

- 每行输出：`api`、**行数**、**字段列表**（过长截断）、**耗时（毫秒）**；成功且 0 行会标 `(empty)`（部分日期无龙虎榜/涨跌停数据属正常）。
- 单条失败：打印 **错误类型** 与脱敏后的简要 `msg`，**不中断**后续用例。
- **不打印** `TUSHARE_TOKEN`；若异常信息可能含敏感片段会显示为 redacted。
- 退出码：`2` = 未设置 `TUSHARE_TOKEN`；`1` = 至少一条失败；`0` = 全部成功。

## 实现与依赖

- 脚本：[`scripts_local/tushare_smoke.py`](../../scripts_local/tushare_smoke.py)
- 封装：[`src/my_research/tushare_research_client.py`](../../src/my_research/tushare_research_client.py)
- 接口与字段背景：[`tushare_data_plan.md`](tushare_data_plan.md)

## 语法检查（无需 Token）

```bash
python -m py_compile scripts_local/tushare_smoke.py
```

## 合规

- 脚本会发起 **真实 API** 调用，占用积分与频次；仅作个人连通性验证。
- 输出不构成投资建议。

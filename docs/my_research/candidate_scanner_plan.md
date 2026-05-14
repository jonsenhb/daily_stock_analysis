# Candidate Scanner v1 设计说明（观察池 / 非买入池）

本文档定义 **A 股候选股扫描（Candidate Scanner）v1** 的规则与数据契约，供后续实现与测试对照。  
**定位**：从全市场或指定股票池中筛出 **「观察池」**，用于投研跟踪与人工复盘；**不是**「买入池」，**不构成**买卖建议，**不**与自动下单挂钩。

**依据**：已对齐仓库内 [tushare_data_plan.md](./tushare_data_plan.md) 与官方接口说明（以页面为准）：

- [stock_basic · doc_id=25](https://tushare.pro/document/2?doc_id=25)
- [daily · doc_id=27](https://tushare.pro/document/2?doc_id=27)
- [daily_basic · doc_id=32](https://tushare.pro/document/2?doc_id=32)
- [stk_limit · doc_id=183](https://tushare.pro/document/2?doc_id=183)
- [suspend_d · doc_id=214](https://tushare.pro/document/2?doc_id=214)

**实现约束（与 AGENTS 一致）**：数据可通过现有 `data_provider` / `TushareResearchClient` 拉取；**不读取、不修改** 真实 `.env`；v1 逻辑放在 `src/my_research/` 下独立模块为佳，**接入主流程前**须可单测、可回滚。

---

## 1. 输入数据

### 1.1 运行参数（逻辑输入）

| 名称 | 类型 | 说明 |
|------|------|------|
| `trade_date` | `YYYYMMDD` | 扫描锚定交易日（通常为 **上一完整交易日** 或配置日；与 `daily` 盘后入库口径一致） |
| `universe` | `full \| pool` | `full`：在可选板过滤后的全市场；`pool`：用户/配置文件给定的 `ts_code` 列表 |
| `pool_codes` | `list[str]` | `universe=pool` 时生效 |
| `max_output` | `int` | 观察池最大行数上限（默认如 200，可配置，防报告膨胀） |

### 1.2 Tushare 数据集（v1 必选）

| 接口 | 典型参数 | 用途 |
|------|----------|------|
| `stock_basic` | `list_status='L'`，按需 `fields` | 建 **可交易宇宙**：`ts_code`、`name`、`market`、`exchange`、`industry`、`list_date`、`delist_date` |
| `daily` | `trade_date` 单日全市场 **或** 按代码分批 | 当日（锚定日）**OHLCV、pct_chg、amount**；扩展窗口时 `start_date/end_date` 算均线与振幅 |
| `daily_basic` | 与 `trade_date` 对齐 | **换手率、流通市值、量比**等流动性/体量过滤 |
| `stk_limit` | `trade_date` | 当日 **涨停价/跌停价**，用于判断是否封堵涨停、距涨停距离等 |
| `suspend_d` | `trade_date`、`suspend_type='S'` | **剔除停牌**（当日仍处于停牌的不进入观察池） |

### 1.3 可选扩展（v1.1+，文档预留）

- `limit_list_d`（[doc_id=298](https://tushare.pro/document/2?doc_id=298)）：精确标记 **U/D/Z（炸板）**；与现有研究侧 `get_limit_list(limit_type=...)` 对齐。
- `limit_cpt_list` / 行业资金流：与 `industry` 或热点板块 **交叉**，强化「近期强势板块」。
- `trade_cal`：严格锚定 **上一交易日**，避免非交易日误判。

### 1.4 与现有个股分析流程的关系（只读理解）

当前主流程为：`StockAnalysisPipeline.process_single_stock` → `fetch_and_save_stock_data` → `analyze_stock`（LLM 等），入口可由 `main.py --stocks`、`analyzer_service`、`analysis_service` 等触发。  
**Scanner v1 不修改该流水线**；产出为 **`ts_code` 列表 + 元数据**，供人工复制到 `--stocks`、自选股文件或后续「批量 enqueue」扩展使用。

---

## 2. 输出字段（单条候选 / 一行）

以下为 **建议 schema**（实现时可 JSON/CSV/DataFrame，字段名可冻结为 snake_case）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `ts_code` | str | Tushare 代码 |
| `symbol` | str | 可选，纯数字代码 |
| `name` | str | 证券简称 |
| `industry` | str | 行业 |
| `market` | str | 主板/创业板/科创板等 |
| `close` | float | 锚定日收盘价 |
| `pct_chg` | float | 锚定日涨跌幅（%） |
| `amount` | float | 锚定日成交额（**须统一单位**：Tushare `daily.amount` 为千元；若与本地「元」混用需转换） |
| `turnover_rate` | float | 锚定日换手率（`daily_basic`） |
| `circ_mv` | float | 流通市值（亿元或万元，**实现时选定并写死到契约**） |
| `volume_ratio` | float | 量比（若有） |
| `dist_to_up_limit_pct` | float | 相对涨停价空间（%），由 `close` 与 `stk_limit.up_limit` 计算；触及涨停可标 0 |
| `dist_to_down_limit_pct` | float | 相对跌停价空间（%） |
| `scan_tags` | list[str] | 见 §5 |
| `scan_score` | float | 见 §4（排序用综合分，**非**预测收益） |
| `rule_hits` | list[str] | 命中的规则 id（可解释性） |
| `as_of_trade_date` | str | 与输入锚定日一致 |
| `scanner_version` | str | 如 `1.0.0` |

---

## 3. 过滤规则（v1）

**原则**：先 **硬剔除**（不可交易/高风险底层），再 **软保留**（模式与板块标签）。具体阈值 **实现时用常量 + 配置覆盖**，文档只给建议初值。

### 3.1 板与交易所（符合「主板、创业板、科创板」）

- **保留**：`stock_basic.market` ∈ {`主板`, `创业板`, `科创板`}（以 Tushare 原文枚举为准）。
- **默认排除**：北交所、CDR 等（若需北交所，单列 `include_bse` 开关，默认 `false`）。
- **`exchange`**：可与 `692` 北交所代码前缀等二次校验，防脏数据。

### 3.2 ST / *ST

- **排除**：`name` 含 `ST`、`*ST`、`S*ST` 等（实现时与 `data_provider` 内 ST 规则对齐，避免漏网）。

### 3.3 停牌

- **排除**：`suspend_d` 在锚定日 **`suspend_type=S`** 的 `ts_code`。
- **注意**：复牌首日波动大，可打标签 `post_suspend` 但不默认剔除（可选规则）。

### 3.4 退市 / 暂停 / 退市风险

- **排除**：`list_status` ≠ `L` 的不进入全市场宇宙。
- **排除或强标签**：`delist_date` 非空、名称含「退」、或其他明确退市整理期关键字 → **至少** `risk_delisting` 标签；v1 建议 **直接剔除** 整理期标的。
- **IPO 过短**：`list_date` 距锚定日不足 N 交易日（如 60）可剔除或降权（可选）。

### 3.5 流动性过低

- **建议阈值**（可配置）：
  - `daily_basic.turnover_rate` < 0.5%（或分主板/双创分层阈值）→ **剔除**；
  - `daily.amount` 低于全市场分位（如低于当日市场 20% 分位）→ **剔除** 或 **降权**；
  - `circ_mv` 过小（如 < 20 亿）→ **剔除**（防操纵与滑点，阈值慎评）。

### 3.6 极端高位风险（非预测，仅结构）

- **建议**（需 `daily` 窗口，如 60/120 交易日）：
  - 收盘价处于近 N 日 **最高价区间** 上方 y%（如 98% 分位）且 `pct_chg` 连续多日走强 → 标签 `extended_high`，默认 **保留在观察池但降权** 或 **需二次确认**（产品择一）。
  - 可用 `dist_to_up_limit_pct` 很小（< 0.5%）标识 **接近涨停**，与 `limit_list_d` 呼应。

### 3.7 近期强势板块（保留倾向）

- **软规则**：`industry` 属于当日/近日 **行业涨幅前 K**（数据源可用 `moneyflow_ind_ths` 或内部已有 sector 排行）→ `rule_hits` 记 `sector_leader`，**加分**（见 §4）。
- **不与个股因果混写**：板块强 ≠ 个股可买，文档与输出须写清。

### 3.8 成交额放大 / 缩量回踩 / 放量突破（模式标签）

- **成交额放大**：`amount` / `median(amount, 20d)` ≥ 1.5（阈值可调）→ 标签 `volume_expansion`。
- **缩量回踩**：近几日下跌或横盘 + 当日量显著低于 20 日均量 + 未破关键均线（规则实现时定义）→ `pullback_shrink_volume`。
- **放量突破**：close 突破近 N 日高 + 放量 → `breakout_volume`。

以上 **均为「观察理由」**，**不**输出「突破必涨」类结论。

### 3.9 涨停 / 炸板 / 跌停风险（标记）

- **base v1**（仅 `stk_limit` + `daily`）：  
  - `pct_chg` 接近 `up_limit`（或达到涨停幅度）→ `tag_limit_up`；  
  - 接近 `down_limit` → `tag_limit_down_risk`。  
- **增强**（v1.1，`limit_list_d`）：  
  - `limit_type=Z` → `tag_blown`; `U`/`D` 与 limit 字段对齐。

---

## 4. 排序规则

**目标**：便于人工从上到下浏览，而非自动推荐Top1。

建议 **二级排序**：

1. **主排序**：`scan_score` **降序**（见下式）。
2. **次排序**：`amount` **降序**（同级别先看流动性）。

**`scan_score`（示例，0～100 或归一化）**：

- 基础分 50。
- `sector_leader`：+10。
- `volume_expansion`：+8；`breakout_volume`：+12；`pullback_shrink_volume`：+6（互斥时取最高档或加权和，实现时定稿）。
- `extended_high`：−15（或上限封顶）。
- `tag_limit_up`：+5（情绪波动观察）；`tag_blown`：+3（分歧）；`tag_limit_down_risk`：−20。
- 流动性过低已在硬过滤剔除，此处不再重复扣分。

**输出截断**：仅保留 `max_output` 行；**同分随机打散可选**，避免同一板块垄断（可配置）。

---

## 5. 风险标签（`scan_tags` / `rule_hits`）

| 标签 / rule id | 含义 |
|------------------|------|
| `liquidity_low` | 触达流动性剔除前边界（若用于软筛） |
| `extended_high` | 价格/涨幅结构上处于阶段极端 |
| `sector_leader` | 所属板块近期相对强势 |
| `volume_expansion` | 放量 |
| `pullback_shrink_volume` | 缩量回踩结构 |
| `breakout_volume` | 放量突破结构 |
| `tag_limit_up` | 涨停或近涨停 |
| `tag_blown` | 炸板（需 limit_list_d） |
| `tag_limit_down_risk` | 跌停或近跌停 |
| `risk_delisting` | 退市整理 / 高危名示 |
| `post_suspend` | 复牌不久 |

标签可 **并存**；报告中须附 **失效条件** 示例：如「止损以跌破锚定日低点为准」类仅作 **用户自行定义**，**不由扫描器生成买卖单**。

---

## 6. 与 market_gate 的关系

| 维度 | 说明 |
|------|------|
| **职责分离** | `market_gate`：**市场级**可否偏好交易、仓位上限、`forbidden_actions`（见 `MarketGateResult`）。Scanner：**个股级**观察列表与结构标签。 |
| **组合使用** | `trade_allowed == false` 或 `market_state` 为防守态时，观察池仍可生成，但输出须 **附带** 当日 `MarketGateResult` 摘要（同一 `trade_date`），并在文案注明「**闸门禁止事项仍优先**」。 |
| **不重复算分** | Scanner 的 `scan_score` **不得**与 `market_score` 混名；可选字段 `gate_market_score` **只读引用**。 |
| **输入可选** | v1 可 **不**把 gate 结果喂入 scanner 过滤（避免循环依赖）；v2 可设「闸门关时仅输出 `extended_high` 降权」等软联动。 |

---

## 7. 与 LLM 的关系

| 维度 | 说明 |
|------|------|
| **Scanner 本体** | v1 **确定性规则 + 数据**，**不调用** LLM 选股。 |
| **下游** | 用户可将观察池 `ts_code` 喂给现有 `process_single_stock` / 报告生成；LLM 仅做 **个股深度分析与解读**。 |
| **Prompt 纪律** | 若未来做「LLM 总结观察池」，须遵循与大盘闸门类似原则：**不得**覆盖硬标签与硬剔除结果；须声明 **不确定性与失效条件**；**禁止**收益承诺与硬性买卖指令。 |
| **JSON** | 若 LLM 输出结构化结果，须 **schema 校验与容错**（与任务 2.3 同哲学）；Scanner 主输出可不经过 LLM。 |

---

## 8. 后续测试方案

### 8.1 单元测试（无网络）

- Mock `stock_basic` / `daily` / `daily_basic` / `stk_limit` / `suspend_d` 小样本 DataFrame。
- 覆盖：**ST 剔除**、**停牌剔除**、**退市状态**、**流动性阈值**、**dist_to_up_limit** 计算、**标签并集**、**排序与截断**。

### 8.2 契约测试

- 固定 `trade_date` 的 golden 文件（**脱敏、小型**）放在 `tests/fixtures/`，校验输出行数与关键列。

### 8.3 可选集成测试（网络/真实 token，人工触发）

- `pytest -m network` 或脚本：单日全市场拉取 **仅限行数上限**，比对 `daily` 条数与 `stock_basic` 宇宙一致性。

### 8.4 与主流程的冒烟

- 观察池前 3 个 `ts_code`：`python main.py --stocks xxx --no-notify --debug`（由用户在配置齐全环境执行）。

### 8.5 文档与治理

- 实现落地时更新 `docs/CHANGELOG.md`；较大行为写入本篇 **修订小节**（版本号 + 日期）。

---

## 9. 修订历史

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0.0 | 2026-05-14 | 初稿：输入/输出/过滤/排序/标签/与 gate & LLM 关系/测试方案 |

---

*本文档为研究规划，不构成投资建议。实现以仓库代码与 Tushare 官网最新说明为准。*

# Tushare 官方接口矩阵与数据底座规划

本文档供 **DGX Spark 本地投研 / 数据底座** 参考，字段名、积分与限量均以 **Tushare 官网接口说明** 为准；**不替代**官网正文，开发前请再次打开对应 `doc_id` 页面核对。

- **不读取**本仓库 `.env`，正文也不依赖真实 API 调用结果。
- **口径**：若某接口页在当前抓取/浏览器中**未写明**积分、频次或单次行数上限，下表一律标为「**官方接口页未载明（勿臆测）**」，以 [积分与频次说明](https://tushare.pro/document/1?doc_id=290) 与各接口页后续更新为准。
- **账户**：下文「约 15000 积分」指与 [积分表 15000 以上档](https://tushare.pro/document/1?doc_id=290) 对照；**具体是否可调某接口**以 Tushare 个人中心权限为准。

---

## 1. 约 15000 积分下的平台档位（表一摘录）

摘自 [积分与频次权限对应表 · doc_id=290](https://tushare.pro/document/1?doc_id=290) **表（一）：积分接口** 中与 **15000 以上** 相关描述（原文含义摘要，仍以官网为准）：

| 积分数 | 每分钟频次 | 每天总量上限 | 可访问范围（原文要点） |
|--------|------------|--------------|------------------------|
| 15000 以上 | 500 | **特色数据无总量限制** | **特色数据专属权限** |

**同页说明（逻辑务必分开理解）：**

1. **需要积分的接口**：达到接口文档所写积分门槛即可调取（如日线、基础数据等）。
2. **需要单独开通的接口**：与积分无关、分别开通 —— 例如 **股票历史/实时分钟、港美股日线/分钟/财报、新闻公告、集合竞价** 等，见表（二）。本文矩阵**未展开表（二）**；若产品需要分钟或港美股，须另行评估 **付费开通** 与限频，**不能**假设 15000 积分即包含。

**与单接口文档的关系**：单接口可能写明「每分钟请求 50 次」等 **窄于或细于** 表（一）的规则。实现时应对 **290 总表 + 该接口页** 取 **更保守** 的一侧，并预留 backoff。

---

## 2. 接口矩阵（用途、积分、更新、限量、频次）

下列均为 **Tushare Pro** 风格调用（示例见各官方页）。**「官方接口页未载明」** 表示在 2026-05-14 前后通过文档站拉取的**该 doc 正文**中未见对应段落。

| Pro API / 接口名 | 文档 | 用途（官方描述摘要） | 积分（原文或载明情况） | 更新时点（官方） | 单次返回上限 / 限量（官方） | 频次 / 其它（官方） |
|------------------|------|----------------------|------------------------|------------------|-----------------------------|----------------------|
| `stock_basic` | [doc_id=25](https://tushare.pro/document/2?doc_id=25) | 基础信息：代码、名称、上市日期、退市日期等 | **2000 积分起**； | 官方接口页**未载明** | **每次最多 6000 行** | **每分钟请求 50 次**；建议本地保存 |
| `trade_cal` | [doc_id=26](https://tushare.pro/document/2?doc_id=26) | 交易日历 | **官方接口页未载明** | **官方接口页未载明** | **官方接口页未载明** | **官方接口页未载明** |
| `daily` | [doc_id=27](https://tushare.pro/document/2?doc_id=27) | A 股 **未复权** 日线；停牌日无数据；可用 `trade_date` 取某日全市场 | 文档写「**基础积分**」可调；与档位关系见 290 | **交易日每天 15 点～16 点之间入库** | **每次 6000 条**（写明约等于单股 23 年量级） | **每分钟可调取 500 次**（接口页原文） |
| `daily_basic` | [doc_id=32](https://tushare.pro/document/2?doc_id=32) | 每日估值与股本市值等基本面指标 | **至少 2000 积分**；并写 **5000 积分无总量限制**（详见 doc） | **交易日每日 15 点～17 点之间** | **单次最大 6000 条** | 见 [积分办法](https://tushare.pro/document/1?doc_id=13) / 290 |
| `index_daily` | [doc_id=95](https://tushare.pro/document/2?doc_id=95) | 指数日线（**不含**申万行业指数，见该页说明） | **2000 积分**；**5000 以上频次相对较高** | **官方接口页未载明** | **单次最多 8000 行** | 见积分办法 / 290 |
| `index_dailybasic` | [doc_id=128](https://tushare.pro/document/2?doc_id=128) | 上证综指、深成指、上证50、中证500、中小板指、创业板指等 **每日指标** | **至少 400 积分** | **官方接口页未载明**；数据自 **2004-01** 起 | **`trade_date` 与 `ts_code` 至少填一个**；**单次限量 3000 条** | **总量不限制**（接口页原文） |
| `top_list` | [doc_id=106](https://tushare.pro/document/2?doc_id=106) | **龙虎榜每日明细**（上榜股票层面） | **官方接口页未载明** | **官方接口页未载明** | **官方接口页未载明** | `trade_date` **必选** |
| `top_inst` | [doc_id=107](https://tushare.pro/document/2?doc_id=107) | **龙虎榜机构/营业部成交明细** | **至少 5000 积分** | **官方接口页未载明** | **单次最大 10000 行** | 可按参数循环取全历史 |
| `stk_limit` | [doc_id=183](https://tushare.pro/document/2?doc_id=183) | **每日涨跌停价格** | **官方接口页未载明** | **官方接口页未载明** | **官方接口页未载明** | 支持单日全市场或单票区间 |
| `limit_list_d` | [doc_id=298](https://tushare.pro/document/2?doc_id=298) | **涨跌停列表（新）**；类型 U/D/Z 等 | **官方接口页未载明** | **官方接口页未载明** | **官方接口页未载明** | 按交易所等参数筛选 |
| `limit_step` | [doc_id=356](https://tushare.pro/document/2?doc_id=356) | **连板天梯**（当日连板高度分布） | **官方接口页未载明** | **官方接口页未载明** | **官方接口页未载明** | `trade_date` 等与官网一致 |
| `limit_list_ths` | [doc_id=355](https://tushare.pro/document/2?doc_id=355) | **涨跌停榜单（同花顺）**；多类池（涨停池等） | **官方接口页未载明** | **官方接口页未载明** | **官方接口页未载明** | `limit_type` 等见接口页 |
| `limit_cpt_list` | [doc_id=357](https://tushare.pro/document/2?doc_id=357) | **涨停家数最多的概念板块**（强势板块轮动） | **8000 积分以上每分钟 500 次，每天总量不限制** | **官方接口页未载明** | **单次最大 2000 行** | 可按日期/板块代码循环 |
| `moneyflow_ind_ths` | [doc_id=343](https://tushare.pro/document/2?doc_id=343) | **同花顺行业** 资金流向 | **6000 积分可调取** | **每日盘后更新** | **单次最大 5000 条** | 可按日期/代码循环 |
| `moneyflow_cnt_ths` | [doc_id=371](https://tushare.pro/document/2?doc_id=371) | **同花顺概念板块** 资金流向 | **6000 积分可调取** | **官方接口页未载明**（行业版写盘后） | **单次最大 5000 条** | 可按日期/代码循环 |
| `moneyflow_ths` | [doc_id=348](https://tushare.pro/document/2?doc_id=348) | **同花顺个股** 资金流向 | **6000 积分可调取** | **每日盘后更新** | **单次最大 6000** | 可按日期或股票循环 |
| `suspend_d` | [doc_id=214](https://tushare.pro/document/2?doc_id=214) | 每日 **停复牌** | **官方接口页未载明** | **不定期** | **官方接口页未载明** | `suspend_type`：S 停牌 / R 复牌 |

**约 15000 积分粗判（非承诺）**：表内写明 **≤15000** 或「表一特色无总量限制」的接口，一般与 15000 档 **不矛盾**；写明 **8000 以上** 的（如 `limit_cpt_list`）通常可覆盖；**6000 积分** 档 THS 资金流亦在积分假设内。**最终以账号权限为准**。

---

## 3. 推荐字段（仅来自各接口输出参数表，可按需 `fields=` 裁剪）

以下为 **常用子集**，避免在底座里默认拉全列；若官网增删字段，以最新 doc 为准。

| 接口 | 推荐字段（示例） | 说明 |
|------|------------------|------|
| `stock_basic` | `ts_code,symbol,name,area,industry,market,exchange,list_status,list_date,delist_date` | 与官方示例一致的可运行最小集 |
| `trade_cal` | `exchange,cal_date,is_open,pretrade_date` | 交易日推断、偏移 |
| `daily` | `ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount` | 回测/事件的收益与波动 |
| `daily_basic` | `ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,total_mv,circ_mv,float_share,free_share` | 截面筛选、流动性 |
| `index_daily` | `ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount` | 大盘/基准 |
| `index_dailybasic` | `ts_code,trade_date,total_mv,float_mv,turnover_rate,turnover_rate_f,pe,pe_ttm,pb` | 市场整体估值/换手 |
| `top_list` | `trade_date,ts_code,name,close,pct_change,turnover_rate,amount,l_buy,l_sell,l_amount,net_amount,net_rate,amount_rate,float_values,reason` | 龙虎榜标的日快照 |
| `top_inst` | `trade_date,ts_code,exalter,side,buy,sell,buy_rate,sell_rate,net_buy,reason` | 营业部画像、净买卖 |
| `stk_limit` | `trade_date,ts_code,pre_close,up_limit,down_limit` | 涨跌停边界 |
| `limit_list_d` | `trade_date,ts_code,industry,name,close,pct_chg,amount,turnover_ratio,fd_amount,first_time,last_time,open_times,up_stat,limit_times,limit` | 涨跌停/炸板统计 |
| `limit_step` | `ts_code,name,trade_date,nums` | 连板天梯高度 |
| `limit_list_ths` | `ts_code,trade_date,name,pct_chg,open_num,lu_desc,limit_type,tag,status,first_lu_time,last_lu_time,turnover_rate,turnover,market_type`（及业务需要的可选时间/封单列） | 同花顺口径涨停池；官网表有个别括号未闭合，以实现时返回为准 |
| `limit_cpt_list` | `ts_code,name,trade_date,days,up_stat,cons_nums,up_nums,pct_chg,rank` | 最强概念板块 |
| `moneyflow_ind_ths` | `trade_date,ts_code,industry,close,pct_change,company_num,net_amount,net_buy_amount,net_sell_amount` | 行业资金流 |
| `moneyflow_cnt_ths` | `trade_date,ts_code,name,pct_change,company_num,net_amount,net_buy_amount,net_sell_amount,industry_index` 等 | 概念板块资金流 |
| `moneyflow_ths` | `trade_date,ts_code,name,pct_change,latest,net_amount,net_d5_amount,buy_lg_amount,buy_lg_amount_rate` 等 | 个股大单结构 |
| `suspend_d` | `ts_code,trade_date,suspend_timing,suspend_type` | 事件日是否可交易 |

---

## 4. 推荐本地缓存策略（工程向，与官方「一次拉全后落盘」表述对齐）

1. **`stock_basic`**：官方写明「调取一次就可以拉取完，**建议保存到本地存储**」— 按周或按需刷新，版本化 snapshot 日期。
2. **`trade_cal`**：区间批量拉取后长期缓存；跨年扩展时用增量 `start_date/end_date`。
3. **`daily` / `index_daily`**：按 **`trade_date` 分区** 或按 `ts_code` + 日期范围；新交易日盘后（官方约 15:00–16:00 入库）增量写入；遵守 **6000/8000 行** 分页与 **500 次/分** 等限制，必要时 sleep + 重试队列。
4. **`daily_basic` / THS 资金流**：与日频行情同一 **trade_date** 分区；资金流接口写明 **盘后更新**，不宜当作盘中实时信号。
5. **龙虎榜 `top_list` / `top_inst`**：按 **trade_date** 全量落盘；`top_inst` 行数可达万级，注意分页循环。
6. **涨跌停类**：`stk_limit`、`limit_list_d`、`limit_step`、`limit_list_ths`、`limit_cpt_list` 均适合 **按日快照**；**多数据源并存**时保留 `source` 与拉取时间戳，避免不同来源或口径混用。
7. **元数据**：每条缓存记录附带 `fetched_at`、请求参数 hash，便于幂等与排障。

---

## 5. 与研究模块的对应关系（建议，非定稿）

### 5.1 适合 `market_gate`（市场可交易性 / 风险闸门）

- **大盘与广度**：`index_daily`（如沪深300、中证500、创业板指等）、`index_dailybasic`（整体换手、估值）。
- **情绪与极端行情**：`limit_list_d`、`limit_list_ths`、`limit_cpt_list`（涨停家数、炸板、最强板块）；**均需按 `trade_date` 使用，通常为盘后数据**。
- **资金流 context**：`moneyflow_ind_ths`、`moneyflow_cnt_ths`（行业/概念净额）— **盘后**。
- **排除误入不可交易标的**：`suspend_d`（停牌）。

**注意**：闸门规则应写明 **数据时点**（如「仅使用上一交易日收盘后可知数据」），避免把当晚才稳定的数据当作当日盘中决策依据。

### 5.2 适合 `lhb_seat_profile`（龙虎榜席位画像）

- **核心**：`top_list`（上榜理由、龙虎榜成交额占比等）、`top_inst`（`exalter`、`side`、`buy`/`sell`/`net_buy`）。
- **辅助对齐行情**：`daily`（上榜日前后价格序列）；**禁止**在事件日使用 T+1 才知的数据冒充 T 日决策。

### 5.3 适合 `candidate_scanner`（候选池 / 选股扫描）

- **基本面与流动性**：`daily_basic`。
- **强弱势与主题**：`limit_list_d`、`limit_list_ths`、`limit_cpt_list`。
- **资金流**：`moneyflow_ths`、`moneyflow_ind_ths`、`moneyflow_cnt_ths`（注意积分 **6000** 与盘后性）。
- **宇宙构建**：`stock_basic`（剔除退市/暂停等 `list_status`）。

扫描任务应 **节流**，并与 **单接口每分钟限制** 对齐（例如 `stock_basic` **50 次/分钟** 与 `daily` **500 次/分钟** 不同）。

### 5.4 适合 `backtest` / `event study`（回测与事件研究）

- **时间轴与对齐**：`trade_cal`、`suspend_d`。
- **收益与波动**：`daily`（注意 **未复权**；复权需求需查阅官网其它接口，**不在本文矩阵内**）。
- **基准与市场**：`index_daily`。
- **事件定义**：LHB（`top_list`/`top_inst`）、涨跌停（`limit_list_d` 等）；事件日 **T** 的收益用 **T+1…** 需在规则里固定，并 **剔除停牌日**（`suspend_d` + `trade_cal`）。

---

## 6. 风险与合规（开发必读）

| 类别 | 说明 |
|------|------|
| **权限/积分变更** | 290 与各接口说明可能随运营调整；上线前用 **测试账号** 验证 `PermissionError`/限频。 |
| **字段变更** | 输出列增删会导致解析失败；使用 `fields=` 显式列并做 schema 版本号。 |
| **未来函数** | 日线 **15–17 点** 入库、龙虎榜/资金流为 **盘后**；事件研究需记录 **数据可得时间**。 |
| **接口限流** | **全局档位**（290）与 **单接口**（如 `stock_basic` 50 次/分）可能并存；建议统一限速器，并对 **429/网络错误** 指数退避。 |
| **表二独立权限** | 分钟线、实时日线、港美股等 **可能需另行付费**；勿在架构里写死「积分够即有」。 |
| **数据语义** | 如 `index_daily` 对深证成指成分说明、`daily` 为未复权等 — **以官方注为准**，避免与终端显示简单类比。 |

---

## 7. 官方入口索引（本文已覆盖的 doc_id）

| doc_id | URL |
|--------|-----|
| 290 | <https://tushare.pro/document/1?doc_id=290> |
| 25 | <https://tushare.pro/document/2?doc_id=25> |
| 26 | <https://tushare.pro/document/2?doc_id=26> |
| 27 | <https://tushare.pro/document/2?doc_id=27> |
| 32 | <https://tushare.pro/document/2?doc_id=32> |
| 95 | <https://tushare.pro/document/2?doc_id=95> |
| 128 | <https://tushare.pro/document/2?doc_id=128> |
| 106 | <https://tushare.pro/document/2?doc_id=106> |
| 107 | <https://tushare.pro/document/2?doc_id=107> |
| 183 | <https://tushare.pro/document/2?doc_id=183> |
| 214 | <https://tushare.pro/document/2?doc_id=214> |
| 298 | <https://tushare.pro/document/2?doc_id=298> |
| 343 | <https://tushare.pro/document/2?doc_id=343> |
| 348 | <https://tushare.pro/document/2?doc_id=348> |
| 355 | <https://tushare.pro/document/2?doc_id=355> |
| 357 | <https://tushare.pro/document/2?doc_id=357> |
| 371 | <https://tushare.pro/document/2?doc_id=371> |

若某链接临时无法打开，请以浏览器直接访问 `https://tushare.pro` 搜索接口名为准；**勿根据本文臆补字段**。
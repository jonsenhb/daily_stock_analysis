# DGX 投研工具链交付总结

本文档汇总 2026-05 期间在本仓库完成的与研究底座、Tushare、本地验证相关的任务范围、产物与验收情况，便于复盘与交接。

**范围说明**：个人研究辅助与数据工具，**不构成**投资建议；不涉及自动下单或收益承诺。

---

## 1. 本地 Agent 验证脚本（Ollama）

### 任务目标

使 `scripts_local/agent_quick_test.sh` / `agent_smoke_test.sh` 适配 **DGX Spark + conda `stock` + 本地 Ollama** 的开发环境；避免误用面向 Gemini 的 `scripts/check_env.py --llm`。

### 交付物

| 路径 | 说明 |
|------|------|
| `scripts_local/_ollama_probe.sh` | `GET /api/tags` + 最小 `POST /api/generate`（stdlib Python），不加载项目 `.env` |
| `scripts_local/agent-quick_test.sh` | 已改为调用 `_ollama_probe.sh`（注：仓库内文件名为 `agent_quick_test.sh`） |
| `scripts_local/agent_smoke_test.sh` | 第 1 步 Ollama probe；第 2–3 步仍为 `main.py`（会读 `.env`，属集成烟测） |
| `.cursor/skills/dsa-local-test/SKILL.md` | Fallback 命令更新为优先 probe |
| `docs/CHANGELOG.md` | 相应 `[改进]` 条目 |

### 验收

- `bash ./scripts_local/agent_quick_test.sh` 在本地 Ollama 可用时通过。
- `agent_smoke_test.sh` 全量可能较慢，按约定未强制全跑。

---

## 2. Tushare 官方接口矩阵文档

### 任务目标

基于 Tushare **官网**各 `doc_id` 整理积分、限量、更新时点、推荐字段及与 `market_gate` / 龙虎榜 / 扫描 / 回测 的映射；**不**替代官网正文、**不**猜未载明字段。

### 交付物

| 路径 | 说明 |
|------|------|
| `docs/my_research/tushare_data_plan.md` | 接口矩阵、约 15000 积分档位摘录、缓存策略建议、模块映射、风险 |
| `docs/CHANGELOG.md` | `[文档]` 条目 |

### 验收

- 文档内对「官网未载明」项已标注，不臆测。

---

## 3. Tushare Research Cache（冷缓存）

### 任务目标

为后续 `market_gate`、龙虎榜画像、候选扫描、事件研究提供 **Parquet + manifest SQLite** 冷缓存；**不**与 `src/storage.py` 主库混用；不读 `.env`；测试用临时目录与 Mock。

### 交付物

| 路径 | 说明 |
|------|------|
| `src/my_research/tushare_cache.py` | `TushareResearchCache`、`normalize_trade_date` / `normalize_ts_code`、限流、`DATASET_REQUIRED_FIELDS` |
| `tests/my_research/test_tushare_cache.py` | 全 Mock，无网络、无写 `data/` |
| `tests/my_research/__init__.py` | 包初始化 |
| `docs/my_research/tushare_cache.md` | 目录结构、key、接入说明 |
| `requirements.txt` | 增加 `pyarrow` |
| `docs/CHANGELOG.md` | 新功能 / chore 条目 |

### 验收

- `python -m pytest tests/my_research/test_tushare_cache.py -q` 通过。

---

## 4. TushareResearchClient（研究用 API 封装）

### 任务目标

封装常用 Tushare Pro 接口；构造函数接受 **`pro` 或 `token`**；**不**读 `.env`；每请求记录 api / 行数 / 字段（日志脱敏）；单元测试 **Mock `pro.query`**。

### 交付物

| 路径 | 说明 |
|------|------|
| `src/my_research/tushare_research_client.py` | 各 `get_*` 方法、`get_limit_list` → 官方 **`limit_list_d`**、`TushareResearchApiError` / `Permission` 子类 |
| `tests/my_research/test_tushare_research_client.py` | Mock 覆盖路由、字段、错误映射等 |
| `docs/my_research/tushare_cache.md` | 增加与 client 的衔接一句 |
| `docs/CHANGELOG.md` | `[新功能]` 条目 |

### 验收

- `python -m pytest tests/my_research/test_tushare_research_client.py -q`、`py_compile` 通过。

---

## 5. Tushare 手动烟测脚本

### 任务目标

本机用手动命令验证约 **15000 积分**下核心/扩展接口可用性；只读环境变量 **`TUSHARE_TOKEN`**（不读 `.env`）；小样本；失败不中断；不写 `data/`。

### 交付物

| 路径 | 说明 |
|------|------|
| `scripts_local/tushare_smoke.py` | 默认基础 5 接口；`--extended` 扩展；`--date` / `--trade-date`；退出码 0/1/2 |
| `docs/my_research/tushare_smoke.md` | 用法、`NO_PROXY` 提示、退出码、合规 |
| `docs/CHANGELOG.md` | 新功能 / 文档；后续 `[修复]` `--date` 别名 |

### 验收（用户侧）

- `python scripts_local/tushare_smoke.py --date 20260512`
- `python scripts_local/tushare_smoke.py --date 20260512 --extended`
- **验收全部成功**（用户确认）。

### 环境与 Token

- Token 需 **`export TUSHARE_TOKEN=...`**（与主程序 `src/config.py` 变量名一致）；烟测脚本**有意**不自动加载 `.env`。

---

## 6. 任务完成总表

| # | 模块 | 状态 |
|---|------|------|
| 1 | Ollama 本地 quick/smoke 前置探测 | 已完成 |
| 2 | `tushare_data_plan.md` 接口矩阵 | 已完成 |
| 3 | `tushare_cache` + 测试 + pyarrow | 已完成 |
| 4 | `tushare_research_client` + 测试 | 已完成 |
| 5 | `tushare_smoke.py` + 文档 + `--date` | 已完成；用户烟测 **全部成功** |

---

## 7. 建议后续（非本次必须）

- 将 `TushareResearchClient` 与 `TushareResearchCache.read_or_fetch` 在主研脚本中串起来（仍由人工触发）。
- 按需扩展 `DATASET_REQUIRED_FIELDS` / `DEFAULT_FIELDS` 与官网同步校验。

---

## 8. 回滚参考

如需撤销本批次代码级改动，可使用：

```bash
git log -1 --oneline
git revert <commit_sha>   # 或按路径 checkout 历史版本
```

具体路径集合：`docs/my_research/`、`scripts_local/`（本批相关文件）、`src/my_research/`、`tests/my_research/`、`requirements.txt`、`docs/CHANGELOG.md` 等。

---

*文档生成：与本轮「投研工具链」交付对齐；若与仓库其他未合并改动并存，以 `git` 实际提交为准。*

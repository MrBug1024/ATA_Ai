# NpaDemo（上游数据服务）Review 与对齐优化方案

> 目的：审查上游 `jonymonkey089-wq/NpaDemo`（`fastapi_server/main.py`，3841 行）的不合理/可优化点，
> 让 ai_hunter（编排服务）与 NpaDemo 快速对齐。
> 状态：**方案待评审**。涉及生产数据服务（供 27+ 项目），评审通过后再改 NpaDemo。
> 基于 2026-06-15 NpaDemo 源码 + case 116 实测。

---

## 实施进度（NpaDemo main）

| 项 | 状态 | commit |
|---|---|---|
| composite_score 并发竞争修复（实施中发现的 bug） | ✅ 已发布 | `6626578` |
| U2 get_full_context 字段契约（`_meta.field_contract`） | ✅ 已发布 | `6626578` |
| U3 compute/fetch 缓存分离 + ingest 失效 | ✅ 已发布 | `8455d2c` |
| U4-F1 重整 claim 按类型 upsert 幂等 + U4-F3 清偿率数值列 | ✅ 已发布 | `256f687` |
| U4-F2 存量去重（F2-b 留最完整，删 111 行）+ 部分唯一索引 | ✅ 已在共用库执行 | — |
| 下游 1.1 改读 `*_dehydrated`+去毒明细、弃 legacy 截断 | ✅ 已发布（ai_hunter `b4a172d`） | — |
| 下游 1.2 本息口径回收率重算 + 注入报告 | ✅ 已发布（ai_hunter `b4a172d`） | — |
| U5 main.py 拆分 | ⬜ 未动（暂缓） | — |

> **下游 1.1/1.2 落地**：新增 `resolve_report_full_context_json`/`build_report_context`（精选权威字段、剔 legacy）+ `compute_recovery_metrics`（本息口径），report_a/b 改用之，`report_part_a.txt §2` 改为「核心逐项+碎片汇总+全量总账」并用注入的 `recovery_metrics`。数值引擎 NPV/逐项去毒消费/参数化为 Tier1 后续。

> **U4 结论**：本息缺失是数据模型现实（重整方案文书无本息拆分），非 bug；下游按 `unsplittable` 处理。真 bug 是重整 claim 重复入库（无幂等），已 F1 幂等化 + F2-b 清存量 + F3 清偿率进数值列。
> ⚠️ 实施中一次操作失误：F3 回填把清偿率提取与 guarantee_type 覆盖合并执行、正则 `%%` 转义错，导致 72 行清偿率文本被覆盖丢失（这些正是被 F2-b 折叠的污染测试行，真值可重传补回，影响低）。教训：destructive UPDATE 前先单独 dry-run SELECT。

> 已发布项均在共用 DB 上端到端验证通过后推 main。缓存表 `engine_results_cache` 已在共用库创建（DDL：`sql_engine_results_cache.sql`）。

---

## 0. 上游 API 全貌

`/api/audit/get_full_context`（main.py:3492）并发跑 4 引擎 + 白手套 + 资金拓扑，聚合返回。
4 引擎：`delta_check`(轧差) / `valuation_squeeze`(去毒挤水) / `deadline_scan`(时效) / `behavioral_scan`(行为)。
另有 ingest、case profile、legal-writ、tasks 等端点。

**优点**（不要动坏）：
- 战术沙盘 `_dehydrate_real_estate`（main.py:3268）：总账 + 核心资产 topN（净值前 80%，≤10 项）+ 碎片按用途打包 + 毒点指纹（案外异议/长租约/非首席抵押）。设计先进。
- `deadline_scan` 已是完整四级时效看板；`behavioral_scan` 已做白手套/资金异常。
- 并发引擎 + 脱水控 token，整体架构合理。

---

## 1. P0 — 对齐阻断 / 正确性（必修）

### 1.1 下游读错字段 + 资产截断丢数据（最高优先）
`get_full_context` 同时返回**三套资产表示**：
| 字段 | 内容 | 截断 |
|---|---|---|
| `real_estate_dehydrated` | 战术沙盘：total_count + core_assets_topN + bundled_assets + drill_down_flags | 核心 ≤10，碎片打包（不丢总账） |
| `real_estate_evaluations`（legacy） | 原始行轻度脱水 | **截断到 3 项**（`_real_estate_evaluations_total` 记总数） |
| `engine_results.valuation_squeeze.real_estate_valuations` | 去毒明细（net_value/discount_factors/verdict） | 截断到 10 |

- **问题**：ai_hunter 当前读的是 legacy 的 `real_estate_evaluations`（**只有 3 项**），导致报告拿不到全量资产；而报告 prompt（report_part_a §2）明确"**逐项列出所有资产，禁止概括省略**"。→ 直接冲突。
- **冲突点需产品决策**：报告要"逐项不省略" vs 沙盘要"碎片打包"。资产很多时不可能逐项全列进 LLM（token 爆炸），沙盘的 topN+打包是合理折中。
- **✅ 已决策（2026-06-15）**：报告口径调整为**「核心资产逐项 + 碎片按用途汇总」**，与战术沙盘对齐。即：
  - 核心资产（`core_assets_topN`，净值前 80%、≤10 项）→ 报告**逐项列表**；
  - 碎片资产（`bundled_assets`，按 `property_usage` 汇总）→ 报告**按用途汇总成一行/一组**，不逐条展开；
  - 总账（`_meta.total_count/total_gross_value/total_net_value`）→ 报告给全量口径数；
  - 毒点（`drill_down_flags`）→ 并入风险/下钻段。
- **改动**：
  - 报告 prompt（[report_part_a.txt](../../ai_hunter/app/prompts/report_part_a.txt) §2）：把"逐项列出所有资产，禁止概括省略"改为"核心资产逐项 + 碎片按用途汇总 + 全量总账"。
  - 下游（ai_hunter）：改读 `real_estate_dehydrated`/`mining_dehydrated`（全量总账+沙盘）+ `engine_results.valuation_squeeze.*`（去毒明细），**弃用 legacy 截断字段**。
  - 上游（NpaDemo）：见 1.3 契约收敛。

### 1.2 回收率口径（total_claim 分母）
`audit_valuation_squeeze`（main.py:2310）：`recovery = total_net / SUM(total_claim)`，分母含罚息/复利/迟延。报告口径要**只算终审本金+利息**（`claims` 表有 `principal/interest/penalty/delayed_interest` 四分项，可精确拆）。
- **✅ 已决策（2026-06-15）**：**下游数值引擎用 `principal+interest` 重算**回收率（分母排除 `penalty`、`delayed_interest`、复利）；上游 `recovery_rate` 仅作参考，不改上游公式。拆不出本息的 claim 打 `unsplittable` 兜底。

### 1.3 数据契约收敛（三套表示 → 清晰单一来源）
三套资产表示让下游困惑、payload 臃肿。
- **建议**：明确**权威字段** = `*_dehydrated`（沙盘，全量总账）+ `valuation_squeeze.*`（去毒明细）；legacy `*_evaluations` 标注 `@deprecated` 并约定下线时间；下游停止依赖 legacy。
- 产出一份 `get_full_context` 的**字段契约文档**（哪个字段权威、语义、截断规则），两边共同维护。

---

## 2. P1 — 性能 / 副作用

### 2.1 读路径有重副作用 + 每次重算
`get_full_context` 每次调用都并发重跑 4 引擎；其中 `audit_valuation_squeeze` 每次 `DELETE valuation_audit_results` + 逐行 `UPDATE real_estate_evaluations SET net_value` + `INSERT`（main.py:2167/2220/2225）。即**一次"读"上下文 = 全量重算 + 重写库**。
- 影响：算力紧张（会议：仅支持 ~5 项目并行）下，27+ 项目反复拉 context 会放大计算/写库压力；且"读"产生写副作用，不符合直觉、并发下有竞态风险。
- **方案**：
  - 分离 **compute（写库，显式触发/数据变更时）** 与 **fetch（纯读已落库结果）**；`get_full_context` 默认走纯读，提供 `?recompute=true` 显式重算。
  - 或加缓存 + 失效（源数据 `updated_at` 变更才重算）。

### 2.2 5% 净值下限 vs 极端归零
`net = gross × max(discount, 0.05)`（main.py:2218/2274）写死 5% 下限防归零；报告口径要极端情况归零。
- **方案**：归零是报告口径，建议在下游数值引擎口径层做（覆盖上游下限），上游保留 5% 下限作为"原始去毒"。已在 01 文档定。

---

## 3. P2 — 数据质量根因

### 3.1 claims 本息拆分缺失/不自洽
实测 case 116：claim[0] 仅有 `total_claim`、principal/interest/penalty 全 None；claim[1] 有拆分但 `total_claim ≠ principal+interest+penalty`。
- 影响：下游按本息口径算回收率时，拆不出的只能打 `unsplittable` 兜底。
- **待查**：`structured-fields` ingest（main.py:1664）与抽取阶段如何填这些字段、生产数据缺失率。可能是 OCR/LLM 抽取阶段的问题，需单独排查（不一定在 NpaDemo 代码层）。

---

## 4. P3 — 代码可维护性（大工程，暂缓）

- `main.py` 单文件 3841 行，路由/引擎/脱水/DB 访问全混在一起。建议后续分层拆分（`routers/` `engines/` `dehydrate.py` `db.py`），但**风险高、与对齐目标不直接相关，放最后**，等核心对齐稳定再做。

---

## 5. 优先级与改动归属

| # | 项 | 优先级 | 改 ai_hunter | 改 NpaDemo | 需产品决策 |
|---|---|---|---|---|---|
| 1.1 | 读对字段 + 资产截断 | P0 | ✅ 改读 dehydrated + 改 prompt | ⚠️ 契约收敛 | ✅ 已定：核心逐项+碎片打包 |
| 1.2 | 回收率本息口径 | P0 | ✅ 下游本息重算 | 不改 | ✅ 已定：下游重算 |
| 1.3 | 契约收敛 + 文档 | P0 | ✅ 停用 legacy | ✅ 标 deprecated | — |
| 2.1 | compute/fetch 分离 | P1 | — | ✅ 已完成 | — |
| 2.2 | 归零 vs 5%下限 | P1 | ✅ 口径层 | — | ✅ 阈值 |
| 3.1 | claims 本息数据质量 | P2 | — | ⚠️ 待查 ingest | — |
| 4 | main.py 拆分 | P3 | — | ✅（暂缓） | — |

---

## 6. 建议执行顺序

1. **先定口径与契约**（1.1 逐项vs打包、1.2 回收率、字段权威性）——这些是产品决策，定了下面才好动手。
2. **下游对齐**（ai_hunter 改读 dehydrated + valuation_squeeze 去毒明细，停用 legacy 截断字段）——风险低、立即见效。
3. **上游契约收敛 + 文档**（NpaDemo 标 deprecated legacy 字段、产出字段契约）。
4. **上游性能**（2.1 compute/fetch 分离）——独立优化。
5. **数据质量排查**（3.1）、**main.py 拆分**（4）——最后。

> 注：所有 NpaDemo 改动评审通过后再动手；它是生产供数服务，改动需小步、可回滚、保持向后兼容窗口。

# 设计方案 02 · 报告八段式子 agent 重构（方案 A）

> 路线图 Tier 1 第 2 项（见 [../ROADMAP.md](../ROADMAP.md) 决策一）。
> 状态：**✅ 已实现并合入**（ai_hunter `0b3c407`）。8 段专家子 agent 并行扇出 + reconcile 聚合 + 分段 SSE 事件 + SOP-JSON 泄漏修复 + audience 前向兼容。pytest 139 passed。
> 一致性 critic 仍后置（§9 TODO）。旧 report_part_a/b 节点/prompt 保留（图不再调用，独立测试仍在）。
> 前置已就绪：Tier1 数值引擎（[design/01](01-确定性数值引擎.md)）+ 下游字段对齐（1.1/1.2）。

---

## 1. 现状与问题

当前报告是**两次 LLM 调用扛八段**：
- `generate_report_part_a`（[report_part_a.txt](../../ai_hunter/app/prompts/report_part_a.txt)）一次出 1-4 段；
- `generate_report_part_b`（[report_part_b.txt](../../ai_hunter/app/prompts/report_part_b.txt)）一次出 5-8 段 + SOP + 下钻；
- `reconcile_report` 拼 `part_a + part_b + trace_summary`、挂角标、抽任务。

问题：
1. **注意力衰减**：每半段 prompt 5.3k/3.1k 字 + 全量数据一次性灌入，后段质量下滑。
2. **SOP JSON 泄漏**：`report_part_b` 末尾的 `tasks` JSON 是给 `create_tasks` 的机器数据，却被 `reconcile_report` 连同 part_b 拼进 `final_report`（[reconcile_report.py:330](../../ai_hunter/app/graph/nodes/reconcile_report.py#L330)），泄漏到用户报告。

## 2. 目标
- 每段一个**专家子 agent**：聚焦的段落 prompt + 切片数据 + 数值引擎结果 → 治注意力衰减。
- **机器数据通道分离**：任务结构化数据走独立字段，不进 `final_report`。
- 保持现有能力：角标自动挂（autocite）、citation_coverage、trace、流式。

## 3. 八段清单 + 数据切片 + 依赖

数值引擎已把共享数字（去毒净值/总账/NPV/回收率）收口到 `computed_metrics`，**段间硬依赖基本消除**——各段读 `computed_metrics` + 自己的数据切片即可，不再相互依赖输出。

| 段 | 标题 | 主要数据切片 | 依赖 |
|---|---|---|---|
| 1 | 数据洗脱与缺失核查 | `full_context_summary` + `computed_metrics.data_quality`（is_estimated/缺卷/cross_check）+ `delta` | 无 |
| 2 | 资产清单与去毒重估 | `real_estate`/`mining`（沙盘）+ `computed_metrics.totals/npv/data_quality.zeroed` + `valuation_detail` | 无（数字取引擎） |
| 3 | 黑盒穿透：资金流向拓扑 | `fund_flow`（mermaid）+ `behavioral` + kg 资金/代持/担保关系 | 无 |
| 4 | 司法时效预警看板 | `deadline_board`（deadline_scan 四级） | 无 |
| 5 | 重整盘活可行性 | `computed_metrics.npv`（三路径回收率基数）+ 重整 claims（清偿率）+ `whiteglove` | 读引擎，无硬依赖 |
| 6 | 猎人行动令：博弈策略 | 风险信号汇总（`computed_metrics` + `behavioral` + 前段结论摘要） | 软（叙事连续性） |
| 7 | 督办看板：SOP 任务 | 全局风险 → 任务；**结构化任务走独立通道** | 软 |
| 8 | 审计对账：增量回款 | `hidden_assets`/增量发现 + `computed_metrics` | 无 |
| — | 下钻行动索引 | 全局红旗摘要 | 软 |

各段公共输入：案件基础 + `user_corrections`（修正台账，最高优先级）+ 角标清单 + `kg_snapshot`。

**权限前向兼容（决策 3）**：每段在 section 注册表里带 `audience`（可见人群层级）元数据，本次不建网关、只打标，供后续权限网关（Tier3-7）按角色筛段/重组。会议角色 → 默认层级：

| 段 | audience 默认 |
|---|---|
| 1 数据洗脱 / 2 资产清单 / 4 时效看板 | `field`（现场尽调/业务可见） |
| 3 资金流 / 5 重整盘活 / 8 增量回款 | `expert`（外部专家可见，不含机密策略） |
| 6 博弈策略 / 7 SOP 督办 / 下钻索引 | `management`（仅管理层） |

层级递进 `field ⊂ expert ⊂ management`。每段独立存 ref + 带 audience，权限网关将来既可走"按段筛选重组"（确定性、推荐），也可走"prompt 内网关按角色脱敏"——两种都依赖本次的"段独立可寻址 + 标签"。

## 3.5 并发与跨 provider 分流（实测，2026-06-16）

负载测试发现 minimax 单 key 满 8 路长生成会 **529 overloaded**。最终落地方案：
- 段节点**真异步**（`llm.astream`，保留分段 SSE 事件）；
- **每 provider 独立有界并发信号量**（`REPORT_SECTION_CONCURRENCY[_<PROVIDER>]`，默认 3），避免 529；
- **过载重试**（529/429/超时退避）；
- **按段 provider 分流**：核心分析段（§2 资产 / §3 资金流·白手套 / §5 重整 / §6 博弈）→ kimi，其余 → minimax，两端点独立并发 = 真跨 provider 并行；
- **段级容错**：某 provider 整体失败 → 回退默认 provider 一次，单点故障不拖垮整报告。

**实测（case 116 全量审计）**：
| 方式 | 耗时 |
|---|---|
| 同步 invoke（串行） | 534s |
| minimax-only 有界异步(3) | 314s |
| kimi+minimax 按段分流 异步 | **149s**（3.6×，8 段齐、7 任务、无 JSON 泄漏、0 回退） |

## 4. 编排选型 —— ✅ 已决策：A2 并行扇出

数值引擎消除硬依赖后 8 段可并行。算力顾虑已澄清：**当前报告走 API key（非本地模型），可并发**；本地模型扩容是另一条线，不阻塞这里。故采用 **A2 并行**：1-8 段从 `compute_metrics` 扇出并行，`reconcile_report` 扇入聚合。并发交错的 token 流用**分段事件**（§8）按 section_id 重组。

> 本次「一步到位」：分段流式 + 权限前向兼容（§3 audience 标签）一并落，后续迭代以此为基准。

## 5. LangGraph 接线 + 状态

```
fetch_full_context → compute_metrics → s1 → s2 → s3 → s4 → s5 → s6 → s7 → s8 → reconcile_report
```
- 每段一个节点 `generate_section_{n}`（Runnable，沿用现有 `build_report_part_*_node` 的流式构造，便于 astream_events 穿透）。
- 状态新增 `report_section_refs: dict[str,str]`（或 `report_section_{n}_ref` 八个字段）+ 各段 summary；段文本走 heavy payload（沿用脱水约定）。
- **机器数据**：第 7 段子 agent 用 structured output 产出任务 → 写 `extracted_tasks`（state），**不进段落展示文本**。

## 6. Prompt 拆分
- `prompts/report_part_a.txt` / `report_part_b.txt` → 拆成 `report_s1.txt … report_s8.txt`（+ 下钻索引并入 s8 或独立 `report_drilldown.txt`）。
- 每段 prompt 只含本段规则 + 引用 `computed_metrics` 的字段说明（沿用 §2.5 已建立的"数字取引擎"范式）。
- 公共规则（金额口径、修正台账优先级、角标格式 `[[CLM-数字]]`）抽到一段公共前缀，注入每段。

## 7. reconcile/join 改造
- 输入从 part_a/part_b 改为 8 段 refs：`final_report = "\n\n".join(s1..s8, trace_summary)`。
- autocite / inline citation / citation_coverage 对 8 段逐段应用（现逻辑对 part_a/b 应用，平移到循环）。
- **任务**：不再从 part_b 文本 regex 抽，直接用第 7 段子 agent 的 structured `extracted_tasks`；`final_report` 不含任何 tasks JSON（修复泄漏 bug）。

## 8. 分段流式（A2 下，本次一步到位）

并行后 8 段 token 流在 astream_events 下交错，必须给每个 token 打 **section_id** 让前端分区重组。抓手：astream_events 每个事件的 `event["metadata"]["langgraph_node"]` 是产生该 token 的节点名（如 `generate_section_2`）—— 现有 handler 没读它，本次补上。

**节点名 → section_id 映射**：`generate_section_{n}` → `n`（建一个 `SECTION_NODE_PREFIX` 常量 + 注册表，避免散写）。

**新增/调整 SSE 事件**（[routes_chat.py](../../ai_hunter/app/api/routes_chat.py) 流式 handler）：
| 事件 | 触发 | data |
|---|---|---|
| `section_start` | 某段首个 token 到达（handler 内 `started` 集合去重） | `{section_id, title, audience}` |
| `section_chunk` | `on_chat_model_stream` 且 node 属某 section | `{section_id, text}` |
| `section_reasoning_chunk` | 同上的 reasoning_content | `{section_id, text}` |
| `section_done` | 该 section 节点 `on_chain_end` | `{section_id}` |
| `final` / `done` | 收尾（不变） | 整份 final response |

handler 改造要点（伪码）：
```
node = event["metadata"].get("langgraph_node", "")
sid = SECTION_BY_NODE.get(node)          # None 表示非段节点（如 reconcile）
if kind == "on_chat_model_stream" and sid:
    if sid not in started: started.add(sid); yield section_start(sid, title, audience)
    if content: yield section_chunk(sid, content)
    if reasoning: yield section_reasoning_chunk(sid, reasoning)
elif kind == "on_chat_model_stream":     # 非段（兜底）→ 旧 text_chunk
    yield text_chunk(content)
elif kind == "on_chain_end" and sid:
    yield section_done(sid)
```
**前端**：维护 8 个分区，按 `section_id` 路由 `section_chunk`；`section_start` 建区（含 `audience` 供权限渲染）；`section_done` 收尾该区。旧 `text_chunk` 仅非段内容兜底。

> 兼容：非流式（`/chat/invoke` 阻塞）路径不变，`reconcile_report` 产出完整 `final_report`。

## 9. 一致性 critic —— ⏸️ 后置（决策 4，**待办勿忘**）
- 计划：末段加轻量校验 agent，跨段数字/结论冲突检查（数字已由引擎统一，冲突概率低，故本次不做）。
- **TODO（记录在此防遗忘）**：八段并行后若出现跨段口径/结论不一致，回来补一个 `consistency_critic` 节点（reconcile 前），对 8 段做一次对抗校验，发现冲突回灌重写或标注。本次先不实现。

## 10. 降级
- 任一段 LLM 不可用 → 该段占位（沿用现有 `_fallback_*` 模式），其余段照常；reconcile 跳过空段。
- `computed_metrics` 缺失 → 引擎已 fail-safe 输出带标记结果，段落 agent 照常。

## 11. 测试
- 每段节点：喂构造 state（含 computed_metrics），断言产出非空 + 引用引擎字段。
- reconcile：8 段拼装 + autocite + **final_report 不含 tasks JSON** + extracted_tasks 来自 §7 结构化。
- 端到端：case 116 跑 full_audit，校验八段齐全、角标、覆盖率、任务不泄漏。

## 12. 决策（已定 2026-06-16）
1. **编排**：✅ **A2 并行扇出**（API key 可并发；本地模型扩容是另一条线）。
2. **流式**：✅ **分段事件一步到位**（`section_start/chunk/reasoning_chunk/done`，按 `metadata.langgraph_node` 打 section_id，§8）。
3. **拆分粒度**：✅ **严格 8 段**；每段带 `audience` 标签，为后续权限网关（Tier3-7）做前向兼容（§3）。
4. **一致性 critic**：⏸️ **后置**（已在 §9 记 TODO 防遗忘）。

## 13. 实现步骤（落地顺序）
1. section 注册表（id/title/prompt 文件/数据切片/audience）+ 公共 prompt 前缀。
2. 拆 `report_s1..s8.txt`（从现有 a/b prompt 切分 + 改为引用 `computed_metrics`）。
3. 8 个 `generate_section_n` Runnable 节点（沿用现有流式构造）；§7 用 structured output 出任务。
4. `full_audit_graph` 并行扇出/扇入接线；state 加 `report_section_refs` 等。
5. `reconcile_report` 改为聚合 8 段 + 逐段 autocite；`final_report` 不含 tasks JSON。
6. `routes_chat` 流式 handler 加分段事件（§8）。
7. 测试（每段节点 + reconcile 不泄漏 + 端到端 case 116）+ 文档/ROADMAP 更新。

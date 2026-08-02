# ai_hunter 第二条线周迭代基准 Checklist

## 1. 目的

这份清单用于作为“第二条线”每周迭代更新的统一基准。

这里的“第二条线”当前定义为：

- 增量更新 / 追加补件治理
- 事件模型与演进解释
- unresolved relation / claim 治理
- 面向前端的结论演进展示

使用规则：

- `[ ]` 未完成
- `[x]` 已完成
- `[~]` 进行中 / 部分完成
- 每周更新时，优先改状态，其次补“本周说明 / 风险 / 下周动作”

---

## 2. 本周目标定义

本周对第二条线的目标，不再只是“后端基础能力跑通”，而是尽量向“最终产品态闭环”靠近。

本周达标判断标准：

1. 有明确的 `material_event` 或等价事件边界
2. 能解释“哪次补件导致哪些旧结论被替代”
3. unresolved relation / claim 不再只是兜底跳过，而是进入可追踪治理路径
4. 前端可消费“旧结论 -> 新结论”的演进展示数据
5. 追加补件流程具备可感知的产品化状态，而不只是后端内部能力

---

## 3. 本周总判断

- 当前状态：`未达标`
- 原因：后端增量裁决、软失效、reconciliation ledger 已具备，但事件模型、未决治理、前端演进展示、补件产品化治理尚未完整闭环

---

## 4. 本周 Checklist

### 4.1 事件模型 / material_event

- [ ] 明确 `material_event` 的最小数据契约
- [ ] 明确 `material_event` 与 `upload_batch_id` 的关系
- [ ] 明确 `material_event` 与一次 `re_audit` / 一版报告的关系
- [ ] 明确事件状态流转：`received / processing / completed / failed / superseded` 或等价方案
- [ ] 在后端落一个可查询的事件边界，而不只靠批次字段拼装
- [ ] 能回答：“这次补件是哪一个事件，它影响了哪些 claim / relation / report”

本周说明：

- 当前已有 `upload_batch_id`，但还不是完整事件模型

风险：

- 如果继续只靠 `upload_batch_id` 承担事件语义，后续演进、追踪、展示会越来越别扭

下周动作：

- 先定数据契约，再决定是新表、扩展现有表，还是用等价事件对象过渡

对应 ToDo：

- `../knowledge-graph/ai_hunter 数据可追溯与知识图谱 todolist.md` -> `2.5B 增量更新与追加补件治理`
- `为每次上传 / 追加补件建立独立 material_event 或等价事件边界`

代码落点：

- `ai_hunter/app/api/routes_files.py`
- `ai_hunter/app/graph/nodes/load_chunks.py`
- `ai_hunter/app/subgraphs/ingest_graph.py`
- `ai_hunter/app/services/kg_service.py`
- `ai_hunter/app/graph/state.py`

---

### 4.2 旧结论被新证据取代的演进展示

- [ ] 明确前端需要的演进展示数据契约
- [ ] 将 `reconciliation ledger` 补齐成前端可直接消费的演进视图
- [ ] 至少能展示一条完整链路：`旧 claim -> 新 claim -> 替代原因 -> 证据来源 -> 事件/批次`
- [ ] 明确是否需要 relation 级别的演进展示
- [ ] 在接口文档中暴露该展示所需字段或新接口
- [ ] 选 1 个标杆案件做真实演示样本

本周说明：

- 当前后端已能产生 `reconciliation_items`
- 当前前端层面的“结论演进”仍不可见

风险：

- 如果没有产品化展示，这条线在老板视角里仍然像“后端做了很多，但看不出来”

下周动作：

- 先把“最小演进卡片”定义出来，再扩充成时间线或对账视图

对应 ToDo：

- `../knowledge-graph/ai_hunter 数据可追溯与知识图谱 todolist.md` -> `2.5B 增量更新与追加补件治理`
- `增加“旧结论被新证据取代”的结论演进展示能力`

代码落点：

- `ai_hunter/app/graph/nodes/reconcile_graph_delta.py`
- `ai_hunter/app/services/kg_service.py`
- `ai_hunter/app/graph/context_loader.py`
- `ai_hunter/app/api/routes_chat.py`
- `ai_hunter/app/graph/schemas.py`

---

### 4.3 unresolved relation / claim 治理

- [ ] 在 schema 中补充跨批解析锚点字段（如 `entity_name / entity_key / relation_key` 等）
- [ ] 调整抽取与落库逻辑，避免仅依赖本批 `temp_id`
- [ ] 对无法解析到历史实体的 relation / claim 建立 unresolved 暂存区或等价记录区
- [ ] unresolved 对象可查询、可追踪，而不是静默跳过
- [ ] 明确 unresolved 的处理路径：人工复核 / 补抽重放 / 日志追踪
- [ ] 至少验证 1 组跨批引用不自洽场景

本周说明：

- 当前已经有 orphan relation / claim 的底线保护
- 但“保护不炸”还不等于“治理闭环”

风险：

- 这块不补齐，系统面对真实脏数据时仍会留下“为什么这条关系没了”的解释黑洞

下周动作：

- 先把 unresolved 存下来，再谈后续自动修复

对应 ToDo：

- `../knowledge-graph/ai_hunter 数据可追溯与知识图谱 todolist.md` -> `2.5D 跨批实体解析与未决引用治理`
- `在 schemas.py 为 relation / claim 补充 entity_name / entity_key / relation_key 等跨批解析锚点字段`
- `在 persist_graph.py 实现两段式解析`
- `为无法落到历史实体的 relation / claim 建 unresolved 暂存区`

代码落点：

- `ai_hunter/app/graph/schemas.py`
- `ai_hunter/app/graph/nodes/extract_entities_relations.py`
- `ai_hunter/app/graph/nodes/normalize_entities.py`
- `ai_hunter/app/graph/nodes/persist_graph.py`
- `ai_hunter/app/services/kg_service.py`

---

### 4.4 追加补件的系统化治理

- [ ] 明确追加补件的产品路径：上传 -> 事件 -> 增量对账 -> 结果回看
- [ ] 明确批次、事件、报告版本之间的关系
- [ ] 给补件链路补齐异步状态：处理中 / 成功 / 失败
- [ ] 明确“本次补件是否引发结论变化”的返回契约
- [ ] 明确“补件后哪些旧结论被替代、哪些只是新增”的回显契约
- [ ] 让补件链路具备最小产品态，而不只是后端算完返回一堆字段

本周说明：

- 当前后端能力已具备一部分，但系统化产品体验还没成型

风险：

- 如果没有统一产品路径，后续前端联调会不断反复定义字段和状态

下周动作：

- 先收口“补件结果页最小字段集”

对应 ToDo：

- `../knowledge-graph/ai_hunter 数据可追溯与知识图谱 todolist.md` -> `2.5C 极简材料治理`
- `fastserver_api 批次接口确定后，把临时 upload_batch_summary 改为真实批次状态`
- `给上传链路增加异步状态管理：处理中 / 成功 / 失败`
- `规划材料批次模型与状态机，但作为后续治理能力逐步引入`

代码落点：

- `ai_hunter/app/api/routes_files.py`
- `ai_hunter/app/subgraphs/ingest_graph.py`
- `ai_hunter/app/graph/nodes/load_chunks.py`
- `ai_hunter/app/api/routes_chat.py`
- `ai_hunter/app/main.py`

---

## 5. 可作为本周达标的最低交付

如果本周无法一步做到完整最终态，则至少应完成以下最低交付，作为“接近达标”的标准：

- [ ] 事件模型最小契约拍板
- [ ] unresolved 暂存与查询路径拍板
- [ ] 演进展示接口或字段契约拍板
- [ ] 追加补件状态机最小版本拍板
- [ ] 至少 1 条标杆案件演进链路可从后端解释清楚

说明：

- 上述 5 项若未完成，第二条线本周不应判定为达标

---

## 6. 当前已完成的技术底座

这些事项虽然不能单独证明“最终产品态达标”，但构成了当前最重要的基础：

- [x] `ADD / OVERRIDE` 增量裁决已接入
- [x] 旧 `claim / relation` 支持 `superseded` 软失效
- [x] reconciliation ledger 已落库
- [x] 候选冲突已支持缩圈后再裁决
- [x] `chunk_id / entity_key / relation_key / upload_batch_id` 等关键锚点已基本贯通
- [x] 第二条线关键后端测试已具备

---

## 7. 对应文件总览

这一节用于周会快速定位，不替代上面的逐项落点。

### 7.1 主要业务文件

- `ai_hunter/app/api/routes_files.py`
- `ai_hunter/app/api/routes_chat.py`
- `ai_hunter/app/graph/nodes/load_chunks.py`
- `ai_hunter/app/graph/nodes/reconcile_graph_delta.py`
- `ai_hunter/app/graph/nodes/persist_graph.py`
- `ai_hunter/app/graph/nodes/extract_entities_relations.py`
- `ai_hunter/app/graph/nodes/normalize_entities.py`
- `ai_hunter/app/graph/context_loader.py`
- `ai_hunter/app/graph/schemas.py`
- `ai_hunter/app/services/kg_service.py`

### 7.2 主要提示词 / 文档

- `ai_hunter/app/prompts/reconcile_graph_delta.txt`
- `../knowledge-graph/ai_hunter 数据可追溯与知识图谱 todolist.md`
- `../knowledge-graph/ai_hunter 数据可追溯与知识图谱代码级落点清单 v1.md`

### 7.3 主要测试

- `tests/test_reconcile_graph_delta.py`
- `tests/test_routes_files.py`
- `tests/test_load_chunks.py`
- `tests/test_persist_graph.py`
- `tests/test_extract_entities_relations.py`
- `tests/test_normalize_entities.py`

---

## 8. 每周更新模板

每周更新时，复制下面这段到文件末尾：

```md
## YYYY-MM-DD 周更新

- 本周结论：
- 已完成：
- 未完成：
- 新风险：
- 下周动作：
```

# sql/knowledge_graph_v1 评审意见 v1

## 1. 评审结论

对 [sql/knowledge_graph_v1.sql](/Users/liuyize/NpaLangG/sql/knowledge_graph_v1.sql) 的本轮评审结论如下：

- **结论：通过，可作为 v1 基础 DDL 继续推进**
- **状态：允许进入第一批代码骨架开发**
- **注意：有若干后续增强项，不阻塞本版 DDL 成立**

这次评审的主基线仍然不变：

1. 图谱事实源必须是 `source_chunk`
2. `kg_claim` 与 `kg_relation` 必须物理分离
3. 前端证据回源依赖 `kg_evidence_link -> chunk_id -> page_no -> bbox_list`
4. 本期先落 `Postgres + pgvector + LangGraph`

---

## 2. 已确认通过项

## 2.1 `embedding` 维度

### 结论

确认采用：

```sql
embedding vector(1024)
```

### 说明

- 当前维度已拍板为 `1024`
- 后续代码写入 `source_chunk.embedding` 时，必须与该维度保持一致
- 如果将来更换 embedding 模型，不能直接无感替换，需同步评估迁移策略

### 本轮处理结果

- **通过**
- **无需修改当前 DDL**

---

## 2.2 长期保存策略

### 结论

确认采用：

- `source_page.page_text`
- `source_chunk.chunk_text`

按**长期保存策略**落库。

### 说明

原因是你要做：

- 报告可追溯
- 图谱关系回源
- 证据抽屉
- drilldown agent 证据引用

这些都要求底层文本可长期回看。

### 后续约束

- 后续需要补“冷热分层策略”
- 但冷热分层不阻塞当前 v1 DDL

### 本轮处理结果

- **通过**
- **冷热分层列入后续待办**

---

## 2.3 `source_chunk.page_no` 冗余字段

### 结论

确认保留 `source_chunk.page_no`，作为有意设计的受控冗余。

### 说明

虽然 `page_id` 已可回到 `source_page.page_no`，但保留 `page_no` 冗余字段有明显价值：

- 前端证据回源更直接
- 常见查询不必强制 join `source_page`
- `kg_evidence_link` 可直接带页码返回给前端

### 约束

后续代码必须保证：

- `source_chunk.page_id`
- `source_chunk.page_no`

始终一致。

这一点由后续代码层负责保证，不在 DDL 中额外加触发器。

### 本轮处理结果

- **通过**
- **一致性由代码层实现**

---

## 2.4 `kg_claim` 的引用映射需求

### 结论

确认：

- 当前 `kg_claim` 继续保留现状
- **后续需要补一张单独的 citation 映射表**

### 说明

当前 DDL 已能支撑：

- claim 存储
- evidence 绑定
- 关系回源

但如果报告里要稳定生成：

- `[1]`
- `[2]`
- `[3]`

这类角标，建议不要把 `citation_code` 直接塞进 `kg_claim` 主表，而是补一张映射表更稳。

### 建议后续表

例如：

- `report_citation_map`

用于保存：

- report_id / report_ref
- citation_id
- claim_id
- report_section
- paragraph_index

### 本轮处理结果

- **当前 SQL 通过**
- **citation 映射表列入后续待办**

---

## 2.5 `entity_key / relation_key` 稳定规则

### 结论

确认按既定计划推进：

- 规则由代码层保证
- 当前 DDL 不额外增加数据库侧约束逻辑

### 说明

这类规则本质是业务语义规则，不适合在 DDL 中硬编码。

后续需要由下面这些实现层负责：

- `normalize_entities.py`
- `deduplicate_graph_items.py`
- `persist_graph.py`
- `chunking.py`

### 本轮处理结果

- **通过**
- **实现责任明确落到代码层**

---

## 2.6 `updated_at` 自动维护

### 结论

本期先不加 `trigger`。

### 说明

当前阶段更重要的是：

- 表结构先定
- 图谱链先跑通
- API 契约先闭环

统一的 `updated_at` 触发器可以后续做，不阻塞本轮 DDL。

### 本轮处理结果

- **通过**
- **暂不处理**

---

## 2.7 `status` 开放文本字段

### 结论

本期保持 `TEXT`，后续在代码层用常量收口。

涉及字段包括：

- `source_file.status`
- `kg_entity.status`
- `kg_relation.status`

### 说明

当前不加 `CHECK CONSTRAINT`，是为了保留初期演进弹性。

但后续代码层应定义明确常量，例如：

- `active`
- `merged`
- `deprecated`
- `archived`

### 本轮处理结果

- **通过**
- **状态枚举统一列入后续待办**

---

## 3. 本轮不阻塞但需要记账的后续项

以下事项本轮不阻塞 SQL 成立，但必须进入正式待办：

1. 冷热分层策略设计
2. citation 映射表设计
3. `page_id` / `page_no` 一致性实现
4. `entity_key` / `relation_key` 稳定生成实现
5. `status` 常量枚举统一

---

## 4. 最终结论

这版 [sql/knowledge_graph_v1.sql](/Users/liuyize/NpaLangG/sql/knowledge_graph_v1.sql) 现在可以视为：

- **已完成结构评审**
- **可作为 ai_hunter 知识图谱 v1 的 DDL 基线**

后续开发应以这份 SQL 为准，并结合后续待办逐步增强。

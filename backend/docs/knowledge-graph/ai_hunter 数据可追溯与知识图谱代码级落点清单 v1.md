# ai_hunter 数据可追溯与知识图谱代码级落点清单 v1

## 1. 先说结论

这次改造不从“炫图谱”开始，而是先把下面这条链打穿：

1. 文件上传
2. OCR / 文本提取
3. 页级与 chunk 级持久化
4. 基于 chunk 做结构化实体/关系/断言抽取
5. 图谱事实落 PostgreSQL
6. 前端按 claim / relation / chunk 回源到页码与 bbox

这意味着：

- 图谱的事实源不是最终报告，而是 `source_chunk`
- 可追溯的最小单位不是“段落”，而是带页码与坐标的 `chunk`
- 大模型产出的原子判断要先落 `kg_claim`，不能直接当成最终 `kg_relation`
- 本期全部落在现有 `Postgres + LangGraph + heavy payload` 架构上，不新增 Neo4j

在完成第一轮落地后，当前阶段的执行优先级需要进一步收口为：

1. 先把“审计高光体验”补强到可汇报、可演示、可成交
2. 再补“极简但可靠”的材料治理
3. 最后再推进重型批次化、复杂 DMS 化能力

当前最优先的不是继续扩外围上传交互，而是围绕“正文角标 -> 证据抽屉 -> 页图高亮 -> 图谱稳定性 -> 追加补件增量治理”这条主链继续往下做。

---

## 1.1 当前阶段新增执行重点

结合最新整体报告，代码层下一阶段的重点收敛为 5 组动作：

1. 报告正文内联角标化（已完成第一阶段：占位符回填 + 正文关键行自动补角标）
2. 证据抽屉与页图高亮体验
3. 图谱稳定键与状态流转
4. 追加补件的增量对账
5. 上传侧最小治理能力

同时补充两条执行铁律：

1. 增量对账不能把“全量找冲突”全扔给大模型，必须先由程序侧收缩候选集
2. 第一阶段高光演示必须锁定 1 个 OCR / bbox 足够稳定的标杆案件，不能拿脏数据赌观感

下面各节在原始图谱建设清单基础上，补充这些新增落点。

---

## 2. 本次改造落在哪几层

建议把改造拆到 5 层：

1. `graph/state`
2. `graph/schemas`
3. `subgraphs + graph/nodes`
4. `services`
5. `api + tools`

这样做的好处是：

- `state` 只负责图内轻量状态
- `schemas` 统一图谱抽取与前端契约
- `subgraphs/nodes` 负责编排
- `services` 负责 PostgreSQL 读写
- `api/tools` 负责对前端和 drilldown agent 暴露能力

---

## 2.1 原始卷宗存储策略

原始卷宗不直接长期放 PostgreSQL，而是放私有部署的 MinIO。

推荐分 3 个 bucket：

1. `ai-hunter-raw`
2. `ai-hunter-derived`
3. `ai-hunter-artifacts`

含义如下：

- `ai-hunter-raw`：原始 PDF、图片、Word、Excel 等卷宗原件
- `ai-hunter-derived`：页图、预览图、可重建的衍生页资源
- `ai-hunter-artifacts`：证据截图、导出报告、系统生成工件

当前已确认：

- MinIO 使用独立于旧项目的新凭据
- 不复用旧项目 `bucket / access_key / secret_key`

后续建议由 `source_file` 记录最少这些存储字段：

- `storage_provider`
- `storage_bucket`
- `storage_key`
- `storage_etag`
- `storage_version`

---

## 3. 需要修改的现有文件

## 3.1 [ai_hunter/app/graph/state.py](/Users/liuyize/NpaLangG/ai_hunter/app/graph/state.py)

### 动作

扩展 `AuditGraphState`，新增知识图谱链路的轻量状态字段。

### 建议新增字段

```python
chunk_batch_ref: str
chunk_batch_summary: str
chunk_ids: list[str]

kg_extraction_run_id: int
kg_entities: list[dict[str, Any]]
kg_relations: list[dict[str, Any]]
kg_claims: list[dict[str, Any]]
kg_summary: str
kg_subgraph_ref: str
```

### 约束

- `state` 中只放摘要、ID、引用键和少量结构化结果
- 整批 chunk、整批实体、整批关系如体积过大，继续走 `heavy payload`
- 不把整套图谱 JSON 全量塞入 checkpointer

### 当前阶段补充字段建议

围绕追加补件和增量治理，建议继续补充：

```python
material_event_ref: str
material_event_summary: str
incremental_chunk_ids: list[str]
superseded_claim_ids: list[int]
superseded_relation_ids: list[int]
report_snapshot_ref: str
```

用途如下：

- `material_event_*`：标识一次上传或追加补件事件
- `incremental_chunk_ids`：只标记本次新增 chunk，供增量对账使用
- `superseded_*`：记录本次被新证据取代的旧结论
- `report_snapshot_ref`：为后续“报告绑定材料版本集”预留

---

## 3.2 [ai_hunter/app/graph/schemas.py](/Users/liuyize/NpaLangG/ai_hunter/app/graph/schemas.py)

### 动作

新增三类 schema：

1. chunk / bbox 基础模型
2. 知识图谱抽取模型
3. 前端 API 契约模型

### 建议新增模型

- `ChunkBBoxModel`
- `SourceChunkModel`
- `ExtractedEntityModel`
- `ExtractedRelationModel`
- `ExtractionClaimModel`
- `ExtractionBundleModel`
- `GraphNodeModel`
- `GraphEdgeModel`
- `EvidenceResolveRequestModel`
- `EvidenceResolveResponseModel`
- `RelationEvidenceRequestModel`
- `SubgraphRequestModel`
- `PageAnchorsResponseModel`

### 最关键的抽取模型

```python
class ExtractedEntityModel(BaseModel):
    entity_temp_id: str
    entity_type: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    confidence: float


class ExtractedRelationModel(BaseModel):
    relation_temp_id: str
    from_entity_temp_id: str
    to_entity_temp_id: str
    relation_type: str
    relation_label: str
    amount: float | None = None
    amount_currency: str = "CNY"
    event_date: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    confidence: float
```

### 关键约束

- `evidence_chunk_ids` 不能为空列表
- `relation` 不能脱离 `chunk` 独立成立
- `claim` 要能挂到 `entity` 或 `relation`

### 当前阶段 schema 补充

在现有 `ExtractionBundleModel` 基础上，建议新增一组增量对账模型，避免 `re_audit` 继续默认全量重算。

建议新增：

- `IncrementalGraphDeltaModel`
- `DeltaAddItemModel`
- `DeltaOverrideItemModel`
- `MaterialEventModel`

最小建议结构：

```python
class DeltaOverrideItemModel(BaseModel):
    old_claim_id: int | None = None
    old_relation_key: str = ""
    reason: str = ""
    new_evidence_chunk_ids: list[str] = Field(default_factory=list)
```

```python
class IncrementalGraphDeltaModel(BaseModel):
    adds: list[DeltaAddItemModel] = Field(default_factory=list)
    overrides: list[DeltaOverrideItemModel] = Field(default_factory=list)
```

目标是让模型输出“变更指令”，而不是新的全量图谱。

### 增量对账 schema 再补一层

为了避免让模型直接做全量 diff，建议把“候选冲突输入”和“单点裁决输出”拆开。

建议继续新增：

- `ConflictCandidateModel`
- `ConflictReviewRequestModel`
- `ConflictReviewDecisionModel`

建议结构：

```python
class ConflictCandidateModel(BaseModel):
    old_claim_id: int
    old_claim_text: str
    old_relation_key: str = ""
    matched_entity_keys: list[str] = Field(default_factory=list)
    matched_chunk_ids: list[str] = Field(default_factory=list)
    similarity_score: float = 0.0
```

```python
class ConflictReviewDecisionModel(BaseModel):
    action: Literal["keep", "override", "add_only"]
    old_claim_id: int | None = None
    reason: str = ""
    new_claim: DeltaAddItemModel | None = None
```

这意味着：

- Python 先输出候选冲突集
- LLM 再对单条候选做裁决
- 不再要求 LLM 直接消费整份旧图谱摘要并生成全量 delta

### 当前阶段再补一层：跨批实体引用协议

目前 `relation` 和 `claim` 主要依赖本批 `entity_temp_id / relation_temp_id` 做内部引用，这只能覆盖“本批抽取自洽”场景，还不能可靠表达“当前批次材料引用历史批次已入库实体”。

针对卷宗批量上传、跨批补件关联的真实场景，建议补充以下字段：

- `ExtractedRelationModel`
  - `from_entity_name: str | None = None`
  - `to_entity_name: str | None = None`
  - `from_entity_key: str | None = None`
  - `to_entity_key: str | None = None`
- `ExtractionClaimModel`
  - `entity_name: str | None = None`
  - `entity_key: str | None = None`
  - `relation_key: str | None = None`

使用原则：

1. 本批 `temp_id` 能解析时，优先走本批内部引用
2. 本批 `temp_id` 缺失或无法落库时，再回退到 `entity_key / canonical_name / normalized_name`
3. 抽取提示词要明确要求模型在无法保证 `temp_id` 自洽时，至少补出端点名称

目标不是让模型直接“猜库里 ID”，而是让后续 `persist_graph` 拿到足够锚点去解析历史实体。

---

## 3.3 [ai_hunter/app/subgraphs/ingest_graph.py](/Users/liuyize/NpaLangG/ai_hunter/app/subgraphs/ingest_graph.py)

### 动作

不推翻现有 ingest 主干，但要为图谱链路补足“页级结构”和“chunk 输入”。

### 现有主干保留

1. `filter_files`
2. OCR / 文本直读
3. `merge_texts`
4. `infer_debtor_name`
5. `parse_document_and_ingest`

### 新增目标

让 ingest 结束后，后续节点能够拿到：

- 文件级元信息
- 页级 OCR 结果
- 结构化切 chunk 的最小输入
- MinIO 对象引用

### 前置约束

当前现有 OCR 适配器主返回值只服务“纯文本摄入链”，不足以直接支撑：

- `source_page`
- `source_chunk.bbox_list`
- `/files/page-anchors`
- PDF / 图片证据高亮

因此在真正落 `load_chunks.py` 之前，需要先完成一层新的 OCR 结构化输出能力。

### 决议

采用 **方案 B**：

- 保留现有 `parse_pdf_sync()` / `parse_image_sync()` 的纯文本返回语义
- 新增带 layout 的 OCR 方法，专供知识图谱和可追溯链路使用

建议新增方法：

- `parse_pdf_with_layout_sync()`
- `parse_image_with_layout_sync()`

这些方法应额外返回：

- 页级结构
- block / line / span
- `bbox`
- `page_width`
- `page_height`
- 原始 OCR 返回体

### 建议在本文件或配套 service 中补的能力

- `_build_source_file_payload()`
- `_build_page_records_from_ocr()`
- `_split_page_to_chunks()`

### 当前阶段补充目标

在不重做整个上传侧的前提下，本文件当前阶段建议再补 3 件事：

1. 给每次上传生成独立 `material_event_ref`
2. 区分“首次上传”和“追加补件”
3. 返回异步处理所需的最小状态摘要，而不是只返回最终聚合结果

这一步先不做重型批次化，但要为后续增量治理预留事件边界。

---

## 3.4 [ai_hunter/app/graph/main.py](/Users/liuyize/NpaLangG/ai_hunter/app/graph/main.py)

### 动作

把知识图谱子图接进主编排。

### 建议接法

在 `ingest_graph` 成功之后，增加可选知识图谱构建步骤：

1. `ingest_graph`
2. `summarize_ingest_result`
3. `build_knowledge_graph_graph`
4. 再继续走 `classify_intent` 或后续主链

### 建议分两阶段

#### Phase A

先做 ingest 后自动建图谱。

#### Phase B

再让：

- `generate_report_a`
- `generate_report_b`
- `run_drilldown_agent`

消费 `kg_summary` 和图谱工具。

### 当前阶段补充目标

主图当前阶段更重要的不是继续加新分支，而是把已有 `re_audit` 分支升级成“增量重审”而不是“自然语言修正入口”。

建议追加一条明确链路：

1. `extract_correction`
2. `build_incremental_context`
3. `reconcile_graph_delta`
4. `full_audit_graph`

其中：

- `build_incremental_context`：装载旧结论台账 + 本次新增 chunk
- `reconcile_graph_delta`：生成 `ADD / OVERRIDE` 结果并写入状态

### 增量对账执行原则

这里建议明确禁止一种实现：

- 不允许把“旧图谱摘要 + 新增 chunk”整包直接丢给 LLM，让它全量找冲突

建议改成 3 段式：

1. `build_incremental_context`
   - 收集本次新增 chunk
   - 基于 `entity_key / relation_key / claim_text / embedding` 召回候选旧 claim
2. `review_conflict_candidates`
   - 只把单条候选冲突送给 LLM 裁决
3. `reconcile_graph_delta`
   - 将 `override` 落成 `superseded`
   - 将 `add_only` 落成新增 claim / relation

---

## 3.5 [ai_hunter/app/tools/audit_tools.py](/Users/liuyize/NpaLangG/ai_hunter/app/tools/audit_tools.py)

### 动作

新增知识图谱查询工具，挂给 drilldown agent。

### 建议新增 tool

- `query_graph_subgraph`
- `query_relation_evidence`
- `query_claim_evidence`
- `query_entity_relations`
- `query_chunks_by_entity`

### 目标

用户问：

- “晨光煤矿和谁有担保链？”
- “这条结论依据是什么？”
- “把这个关系的原文证据打开”

agent 可以查图谱和证据，而不是纯靠语言模型自由发挥。

### 当前阶段补充 tool

为了支撑老板/负责人视角的高光演示，建议继续新增：

- `query_case_risk_dashboard`
- `query_superseded_claim_history`

前者服务总览看板，后者服务“结论为何变化”的可解释展示。

---

## 4. 需要新增的文件

## 4.1 新增 [ai_hunter/app/subgraphs/build_knowledge_graph_graph.py](/Users/liuyize/NpaLangG/ai_hunter/app/subgraphs/build_knowledge_graph_graph.py)

### 职责

编排知识图谱构建子图。

### 节点顺序

1. `load_chunks`
2. `extract_entities_relations`
3. `normalize_entities`
4. `deduplicate_graph_items`
5. `persist_graph`
6. `build_graph_summary`

### 输出

- `kg_extraction_run_id`
- `kg_summary`
- `kg_subgraph_ref`

---

## 4.2 新增 `ai_hunter/app/graph/nodes/load_chunks.py`

### 职责

把 OCR / 文本结果按文件、页、chunk 落地到：

- `source_file`
- `source_page`
- `source_chunk`

### 输入

- `current_case_id`
- `current_debtor_id`
- `current_debtor_name`
- `uploaded_files`
- `aggregated_text_ref`
- `parse_document_result_ref`

### 输出

- `chunk_batch_ref`
- `chunk_batch_summary`
- `chunk_ids`

### 关键规则

- `chunk_id` 必须稳定生成
- 每个 chunk 都要能回到 `file_id + page_no + bbox_list`
- 这一层是所有图谱抽取的事实入口

---

## 4.3 新增 `ai_hunter/app/graph/nodes/extract_entities_relations.py`

### 职责

基于 chunk 批量调用 LLM 做结构化抽取。

### 输入

- `current_case_id`
- `chunk_ids`
- `chunk_batch_ref`

### 输出

- `kg_extraction_run_id`
- `kg_entities`
- `kg_relations`
- `kg_claims`

### 核心约束

- 只能使用传入 chunk 中出现过的信息
- 不允许构造不存在的主体
- 每条 relation 必须绑定 `evidence_chunk_ids`
- claim 需要能落到 entity 或 relation

### 当前阶段补充

本节点需要区分两种运行模式：

1. 全量抽取模式
2. 增量补件模式

增量补件模式下，不直接产出新的全量 bundle，而是为后续 `reconcile_graph_delta` 准备候选新增项。

---

## 4.4 新增 `ai_hunter/app/graph/nodes/normalize_entities.py`

### 职责

实体归一。

### 处理内容

- 去空格
- 统一全角/半角括号
- 清洗常见 OCR 噪音
- 合并简称 / 全称
- 生成 `entity_key`

### 示例

- `晨光煤矿`
- `钟山区老鹰山镇晨光煤矿`

如果规则命中，应归并成一个规范实体。

### 当前阶段补充

本节点要尽快补齐稳定 `entity_key` 规则，并确保该规则在：

- 全量建图
- 追加补件
- 重审

三条路径里完全一致。

### 当前状态

这一层现在已经补齐为：

1. 统一实体名归一化
2. 生成稳定 `entity_key`
3. 基于实体键补齐稳定 `relation_key`
4. 在代码层收口 `status` 默认值

当前代码层支持的状态值为：

- `active`
- `superseded`
- `invalid`

---

## 4.5 新增 `ai_hunter/app/graph/nodes/deduplicate_graph_items.py`

### 职责

图谱项去重与聚合。

### 工作内容

- 实体去重
- 关系去重
- claim 去重
- evidence 引用去重
- 统计 `source_count`

### 目标

避免同一个 chunk 在多个 batch 中重复产出完全相同的边和断言。

### 当前阶段补充

除去重外，本节点应补“旧结论候选命中”能力，为后续 `OVERRIDE` 判定准备输入：

- 命中可能被取代的旧 `claim`
- 命中可能被取代的旧 `relation`
- 返回候选对账对象

候选命中建议分层实现，不要求第一版就上重型向量库：

1. 先做 `entity_key` 精确命中
2. 再做 `relation_key` 精确命中
3. 再做 `claim_text` 轻量相似度筛选
4. 最后视效果再补 embedding 召回

目标是先把“候选集缩小”做出来，而不是先把基础设施堆满。

---

## 4.6 新增 `ai_hunter/app/graph/nodes/persist_graph.py`

### 职责

将图谱结果真正写入 PostgreSQL。

### 原则

- node 不直接写 SQL
- 统一调 `kg_service.py`

### 输出

- `kg_subgraph_ref`
- `kg_summary`

### 当前阶段补充

本节点需要支持两种写入语义：

1. 正常写入 `active`
2. 对旧结论做 `superseded` 软失效

不允许在图谱层直接硬删除旧 claim / relation。

### 当前阶段再补一层：跨批实体解析与未决引用暂存

`persist_graph` 当前已加底线保护：无效 relation / claim 不再把整条 ingest 打崩。

但这只是止血，不是最终方案。下一步这里要补成“两段式解析”：

1. 先解析本批引用
   - `entity_temp_id -> entity_id`
   - `relation_temp_id -> relation_id`
2. 再解析跨批引用
   - 优先按 `entity_key`
   - 再按 `canonical_name / normalized_name + entity_type`
   - 命中当前案件历史 `kg_entity` 后再补全 `from_entity_id / to_entity_id / entity_id`

若仍无法解析，不应静默丢弃，建议把原始 relation / claim 落到未决区域，至少保留：

- 原始抽取 payload
- `chunk_ids`
- 失败原因
- 本次 `kg_extraction_run_id`

建议优先以 `heavy payload + 日志` 起步，后续正式补：

- `kg_unresolved_relation`
- `kg_unresolved_claim`

---

## 4.7 新增 `ai_hunter/app/graph/nodes/build_graph_summary.py`

### 职责

构建供报告与 agent 消费的图谱摘要。

### 建议输出内容

- 重点实体 Top N
- 高风险关系 Top N
- 关键 claim Top N
- 证据覆盖摘要

### 用途

后续给：

- `generate_report_a`
- `generate_report_b`
- `run_drilldown_agent`

提供更稳定、更可解释的上下文。

---

## 4.8 新增 `ai_hunter/app/services/kg_service.py`

### 职责

知识图谱数据库服务层。

### 建议方法

- `create_extraction_run(...)`
- `complete_extraction_run(...)`
- `fail_extraction_run(...)`
- `insert_source_files(...)`
- `insert_source_pages(...)`
- `insert_source_chunks(...)`
- `upsert_entities(...)`
- `upsert_relations(...)`
- `insert_claims(...)`
- `insert_evidence_links(...)`
- `fetch_subgraph_by_entity(...)`
- `fetch_relation_evidence(...)`
- `fetch_claim_evidence(...)`
- `fetch_page_anchors(...)`

### 当前阶段补充方法

建议继续补充：

- `mark_claims_superseded(...)`
- `mark_relations_superseded(...)`
- `fetch_active_claims_by_case(...)`
- `fetch_candidate_conflicts_by_chunks(...)`
- `create_material_event(...)`
- `complete_material_event(...)`
- `fetch_entities_by_keys(...)`
- `fetch_entities_by_names(...)`
- `insert_unresolved_relations(...)`
- `insert_unresolved_claims(...)`

目标是把增量对账、软失效、上传事件这些能力继续收口在 service 层。

其中新增职责边界建议如下：

1. `graph node` 负责准备候选键和候选名称
2. `kg_service` 负责统一查历史实体与写未决记录
3. 后续人工复核、补抽、重放统一围绕 unresolved 数据做

其中 `fetch_candidate_conflicts_by_chunks(...)` 不应只是简单查库，而要承担“前置缩圈”职责：

1. 根据新增 chunk 命中的 `entity_key / relation_key` 拉取旧 claim
2. 支持按 claim_text 相似度排序
3. 后续预留 embedding 相似度字段
4. 只返回少量高置信候选给 LLM

### 当前状态

这一层现在已经补到：

- `mark_claims_superseded(...)`
- `mark_relations_superseded(...)`
- `fetch_candidate_conflicts_by_chunks(...)`

其中 `kg_claim` 采用“双轨兼容”：

1. 新 schema 优先使用正式 `status`
2. 旧库若暂未加 `kg_claim.status`，代码先退回 `review_status` 兼容映射

当前约定的事实状态语义为：

- `active`
- `superseded`
- `invalid`

其中：

- `kg_entity.status` 已接入
- `kg_relation.status` 已接入
- `kg_claim.status` 已接入代码与 SQL 设计稿，并保留对旧 `review_status` 的兼容写法

但注意，这一层目前只完成了“状态语义 + supersede 方法”地基，尚未完成 `reconcile_graph_delta` 的正式调用闭环。

这一层已完成最小可用实现，当前方法签名为：

`fetch_candidate_conflicts_by_chunks(case_id, chunk_ids, entity_keys=None, relation_keys=None, claim_texts=None, limit=12)`

当前输入输出契约如下：

1. 输入
   - `chunk_ids`：本次新增材料对应的 `source_chunk.chunk_id`
   - `entity_keys`：本次新抽取结果命中的稳定实体键，可选
   - `relation_keys`：本次新抽取结果命中的稳定关系键，可选
   - `claim_texts`：本次新抽取结果中的候选结论文本，可选
   - `limit`：返回给后续 LLM / reconcile 节点的最大候选数
2. 程序侧缩圈逻辑
   - 先回查新增 chunk 的 `chunk_text / anchor_text`
   - 再按 `entity_key / relation_key / claim_text` 三路收缩旧 claim
   - 对命中结果按 `matched_by + claim_text similarity + confidence` 排序
3. 输出
   - 原样回传本次使用的 `chunk_ids / entity_keys / relation_keys / claim_texts`
   - `candidates`：少量已排序候选 claim，包含 `matched_by / match_score / evidence_count`

这一步的目标不是做最终裁决，而是把“全量旧图谱”压缩成“少量高相关冲突候选”。

### 原则

- 所有图谱 SQL 收口在 service
- API、tool、node 不直接拼图谱 SQL
- 便于后续统一接事务、审计日志、权限控制

---

## 4.9 新增 `ai_hunter/app/api/routes_graph.py`

### 职责

对前端暴露图谱与证据接口。

### 建议接口

1. `POST /evidence/resolve`
2. `POST /graph/relation-evidence`
3. `POST /graph/subgraph`
4. `GET /files/page-anchors`
5. `POST /graph/demo-case-trace/validate`

### 配套动作

需要在 [ai_hunter/app/main.py](/Users/liuyize/NpaLangG/ai_hunter/app/main.py) 中挂载该 router。

### 当前阶段补充接口方向

本阶段不一定一次性全开新接口，但要预留两类能力：

1. 风险总览接口
2. 结论演进历史接口

用于支持老板/负责人视角，以及补件后“旧结论为何被替代”的解释能力。

---

## 4.10 新增 `ai_hunter/app/services/chunking.py`

### 职责

统一管理 chunk 切分、哈希和 bbox 合并规则。

### 建议方法

- `normalize_text_for_hash(text)`
- `build_chunk_id(...)`
- `split_page_text_to_chunks(...)`
- `merge_bboxes_for_chunk(...)`

### 原因

chunk 逻辑后面一定会演化，单独拆 service 比把逻辑散在 node 里更稳。

### 当前状态

目前 `chunk_id` 已稳定落地，生成因子为：

1. `case_id`
2. `file_sha256`
3. `page_no`
4. `chunk_index`
5. 归一化后的 `chunk_text_sha256`

这能在常见 OCR 空格抖动下保持稳定，同时避免跨案、跨文件串键。

---

## 4.10A 新增 `ai_hunter/app/services/graph_identity.py`

### 职责

统一管理图谱稳定身份规则与状态归一规则。

### 当前能力

- `normalize_entity_name(...)`
- `build_entity_key(...)`
- `build_relation_key(...)`
- `normalize_relation_label(...)`
- `normalize_amount_value(...)`
- `normalize_graph_status(...)`

### 作用

避免 fallback 抽取、归一节点、后续增量对账各自拼一套 key。

---

## 4.11 修改 [ai_hunter/app/services/ocr_service.py](/Users/liuyize/NpaLangG/ai_hunter/app/services/ocr_service.py)

### 职责

在不破坏现有 ingest 纯文本链路的前提下，新增“带 layout 的 OCR 返回”能力。

### 必做事项

- 保持 `parse_pdf_sync()` / `parse_image_sync()` 返回结构不变
- 新增 `parse_pdf_with_layout_sync()` / `parse_image_with_layout_sync()`
- 新方法返回至少包含：
  - `text`
  - `message`
  - `pages`
  - `blocks`
  - `page_width`
  - `page_height`
  - `raw_response`

### 作用

后续这些模块要直接依赖这层结果：

- `load_chunks.py`
- `source_page` 持久化
- `source_chunk.bbox_list`
- `/files/page-anchors`
- 前端 PDF / 图片高亮

---

## 4.12 新增 `ai_hunter/app/services/minio_service.py`

### 职责

封装 AI Hunter 自己的 MinIO 文件上传、对象引用生成和后续预签名访问能力。

### 配置项

- `AI_HUNTER_MINIO_ENABLED`
- `AI_HUNTER_MINIO_ENDPOINT`
- `AI_HUNTER_MINIO_ACCESS_KEY`
- `AI_HUNTER_MINIO_SECRET_KEY`
- `AI_HUNTER_MINIO_BUCKET_RAW`
- `AI_HUNTER_MINIO_BUCKET_DERIVED`
- `AI_HUNTER_MINIO_BUCKET_ARTIFACTS`
- `AI_HUNTER_MINIO_USE_SSL`

### 第一阶段职责

- 上传原始卷宗到 `ai-hunter-raw`
- 返回 `bucket / object_key / etag`
- 供 `source_file` 落库存储引用

### 当前状态

这一层现已完成最小闭环接线：

- `persist_graph` 写入本次新增 entity / relation / claim
- `reconcile_graph_delta` 基于新增 chunk 信号调用 `fetch_candidate_conflicts_by_chunks(...)`
- 若命中“修正 / 重审 / 补件推翻旧结论”语境，则调用：
  - `mark_claims_superseded(...)`
  - `mark_relations_superseded(...)`
- 最后刷新 active-only `kg_subgraph_ref`

当前实现已升级为“结构化裁决优先，启发式兜底”：

1. 先用 `entity_key / relation_key / claim_text` 缩圈命中旧 claim
2. 把“新增 claim + 候选旧 claim + chunk 证据摘要 + correction 记录”送入小包裁决器
3. 模型结构化输出逐条 `ADD / OVERRIDE`
4. Python 只负责把明确命中的旧事实落成 `superseded`

这意味着：

- “软失效而不是硬删除”已经接通
- “模型显式输出 `ADD / OVERRIDE` 指令”已经有第一版落地
- 无 LLM key 或结构化调用失败时，仍会回退到启发式 override
- 现阶段还不消费整份旧图谱摘要，只消费候选冲突小包，方向保持正确

### reconciliation ledger 落点

已新增 `kg_reconciliation_ledger`，用于记录：

- 哪条 `new_claim_id` 触发了增量对账
- 它推翻了哪条 `superseded_claim_id`
- 对应 `new_relation_id / superseded_relation_id`
- `rationale`
- `evidence_chunk_ids`
- `decision_payload`

当前链路：

1. `reconcile_graph_delta` 在完成 supersede 判定后写入 ledger
2. `fetch_case_graph_snapshot(...)` 会把最近 ledger 条目带回 `kg_subgraph_ref`
3. `/api/chat` 最终响应已带出 `reconciliation_items`

这让前端已经可以直接展示：

- “旧结论为何失效”
- “由哪条新证据触发”
- “新旧 claim 的对应关系”

这一层已完成基础接入，后续重点不再是“能不能传”，而是：

1. derived / artifacts 的正式生产使用
2. 页图、证据截图、报告工件的稳定对象规则
3. 面向前端的可访问 URL 和内部 `minio://` 引用并存策略

---

## 4.13 新增 `ai_hunter/app/graph/nodes/reconcile_graph_delta.py`

### 职责

处理追加补件后的图谱增量对账。

### 输入

- `incremental_chunk_ids`
- `kg_summary`
- 历史 active claim / relation 台账
- 本次抽取候选项

### 输出

- `superseded_claim_ids`
- `superseded_relation_ids`
- 增量新增的 `kg_entities / kg_relations / kg_claims`

### 核心规则

1. 模型输出 `ADD / OVERRIDE`
2. Python 负责把 override 落成软失效
3. 不直接覆盖旧记录
4. 不直接删除旧记录
5. 模型输入必须是“候选冲突 + 新证据”的小包，不是整份旧图谱摘要

### 推荐输入来源

本节点应消费：

- `incremental_chunk_ids`
- `fetch_candidate_conflicts_by_chunks(...)` 返回的候选冲突
- 单条候选冲突对应的旧 claim / relation

而不是直接消费“全案件全量图谱摘要”。

---

## 4.14 新增 `ai_hunter/app/services/demo_case_service.py`

### 职责

维护第一阶段对外演示使用的标杆案件配置。

### 建议能力

- `get_primary_demo_case_id()`
- `is_demo_case(case_id)`
- `get_demo_case_quality_flags(case_id)`

### 用途

1. 锁定第一阶段高光演示案件
2. 给前端和报告链路暴露“演示模式”开关
3. 在 OCR / bbox 不稳定案件上避免误用高风险演示效果

---

## 4.15 新增 `ai_hunter/app/graph/nodes/validate_demo_case_trace.py`

### 职责

对标杆案件的证据回源效果做发布前校验。

### 最小检查项

1. 角标可解析到 claim
2. claim 能解析到 evidence
3. evidence 能回到 `page_no + bbox_list + page_image_ref`
4. bbox 命中区域不为空

### 目标

第一阶段不是追求“所有案件都好”，而是先确保标杆案对外可打。

### 当前状态

这一层已完成最小可用落地：

1. 新增 `ai_hunter/app/services/demo_case_trace_service.py`
2. 新增 `POST /graph/demo-case-trace/validate`
3. 已校验 `citation -> claim -> evidence -> page-anchor`
4. 已覆盖 `missing_page_image_ref / missing_bbox_list / page_anchor_not_found` 等常见失败原因

---

## 5. 当前阶段推荐落地顺序

为了和整体报告保持一致，代码级执行顺序建议如下：

1. 先补正文内联角标与证据抽屉所需后端数据
2. 再收口 `chunk_id / entity_key / relation_key / status` 规则
3. 再补标杆案件验收链路，确保高光演示可控
4. 再补 `reconcile_graph_delta.py` 和 service 侧增量治理
5. 最后再补上传事件、批次、缺失材料清单等治理层能力

其中第 1 步的当前完成度为：

1. 已支持 LLM 在正文输出 `[[CLM-数字]]` 占位符
2. 已在 `reconcile_report.py` 中回填为最终 `[1]` 角标
3. 已增加正文关键句 / 列表项 / 表格行的自动补角标逻辑
4. 已补“关键结论未挂角标”的覆盖率告警与 `citation_coverage` 返回结构
5. 已让 `POST /evidence/resolve` 直接返回 `primary_evidence + primary_page`，满足证据抽屉首屏渲染
6. 已新增标杆案件发布前验收接口 `POST /graph/demo-case-trace/validate`
7. 下一步继续收口 `chunk_id / entity_key / relation_key / status` 稳定规则

---

## 5. 前端接口与页面能力映射

## 5.1 报告角标回源

前端点击报告中的 `[1]`：

- 调 `POST /evidence/resolve`
- 返回 `claim + evidence list + primary_evidence + primary_page`

用于：

- 报告右侧证据抽屉
- claim 详情展示
- 首屏直接展示默认主证据与页内高亮
- 进一步跳 PDF 页

---

## 5.2 图谱边点击看证据

前端点击图谱中的边：

- 调 `POST /graph/relation-evidence`

用于：

- 查看该关系的 claim 列表
- 查看该关系的原文证据

---

## 5.3 图谱面板加载

前端打开图谱面板：

- 调 `POST /graph/subgraph`

用于：

- 拉取节点和边
- 渲染 G6 / React 图谱组件

---

## 5.4 PDF 或页图高亮

前端跳证据页：

- 调 `GET /files/page-anchors`

用于：

- 给 `pdf.js` 或页图 overlay 提供 bbox 坐标

---

## 5.5 双线 MVP：卷宗类别与多批次上传

当前产品方向以“双线可用”为第一优先级：

- 操作员线：依赖 `fastserver_api` 建案 / 案件列表，LangGraph 负责上传摄入编排
- 审计线：律师 / 负责人在 LangGraph 内触发审计报告、追问、补充材料、追溯与图谱增强
- 图谱是审计报告与追溯的增强项，不作为第一阶段继续深挖的主线

已完成 LangGraph 侧预接线：

- `ai_hunter/app/services/doc_category_api.py`
  - 预留 `GET /api/ingest/doc-categories`
  - 预留 `GET /api/case/{case_id}/doc-categories`
  - 预留 `POST /api/ingest/validate-doc-category`
  - fastserver_api 未完成前使用 mock 类别服务
- `ai_hunter/app/tools/doc_category_tools.py`
  - 给 LangGraph 工具层提供类别字典、案件类别覆盖、类别校验能力
- `ai_hunter/app/api/routes_files.py`
  - `/files/upload-and-ingest` 接收 `doc_category / batch_name / upload_batch_id / operator_id / operator_name`
  - 计算文件 SHA256，返回 `new_files / duplicate_files / suspected_mismatch_files`
  - 返回 `upload_batch_summary`，后续可替换为 fastserver_api 真实批次状态
- `ai_hunter/app/api/routes_chat.py`
  - chat 请求与 SSE 透传批次、类别、重复文件、缺失类别字段
- `ai_hunter/app/graph/state.py`
  - 状态层保留批次、类别、重复文件、疑似错分文件字段，避免主图丢失上下文

后续联调原则：

- fastserver_api 负责案件、类别字典、案件类别覆盖、真实批次状态
- LangGraph 负责 OCR、摄入编排、报告生成、追溯、追问和图谱增强
- 同一批次硬性要求只上传一种 `doc_category`
- 多批次上传允许出现同名或同内容文件，但后端必须以 SHA256 / 批次记录识别重复，避免重复材料污染审计上下文

---

## 6. 推荐开发顺序

## 第一批：地基

1. `sql/knowledge_graph_v1.sql`
2. `ai_hunter/app/services/kg_service.py`
3. `ai_hunter/app/graph/schemas.py`
4. `ai_hunter/app/graph/state.py`

这批完成后，数据库结构、状态入口、schema 约束才算真正站住。

---

## 第二批：chunk 与落库主干

0. `ai_hunter/app/services/ocr_service.py` 增强结构化 OCR 返回
1. `ai_hunter/app/services/minio_service.py`
2. `ai_hunter/app/services/chunking.py`
3. `ai_hunter/app/graph/nodes/load_chunks.py`
4. `ai_hunter/app/graph/nodes/persist_graph.py`

这批完成后，事实锚点链路就能先跑通：

`file -> page -> chunk -> db`

---

## 第三批：抽取与子图

1. `ai_hunter/app/graph/nodes/extract_entities_relations.py`
2. `ai_hunter/app/graph/nodes/normalize_entities.py`
3. `ai_hunter/app/graph/nodes/deduplicate_graph_items.py`
4. `ai_hunter/app/graph/nodes/build_graph_summary.py`
5. `ai_hunter/app/subgraphs/build_knowledge_graph_graph.py`

这批完成后，图谱就开始真正成形。

---

## 第四批：API 与 Agent 消费

1. `ai_hunter/app/api/routes_graph.py`
2. `ai_hunter/app/tools/audit_tools.py` 图谱工具扩展
3. `ai_hunter/app/graph/main.py` 主图接线

这批完成后，前端和 drilldown agent 才能真正吃到图谱能力。

---

## 7. 本文档的使用方式

这份落点清单不是最终实现，而是开发施工图。

建议你后面按下面顺序使用：

1. 先评审 [sql/knowledge_graph_v1.sql](/Users/liuyize/NpaLangG/sql/knowledge_graph_v1.sql)
2. 再按本清单拆第一批代码骨架
3. 然后逐步把 node、service、api 衔接起来

最重要的一点始终不要丢：

**图谱只能建立在 chunk 事实锚点上，不能建立在最终报告上。**

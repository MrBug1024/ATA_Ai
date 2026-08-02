# ai_hunter 数据可追溯与知识图谱 ToDoList

## 1. 说明

这份清单用于记录“已拍板但暂不在当前 DDL 中处理”的后续工作，方便后续逐项检查与关闭。

使用规则：

- `[ ]` 未完成
- `[x]` 已完成
- 新的后续事项继续追加到本文件

---

## 2. 当前待办

### 2.1 存储与分层

- [ ] 设计 `source_page.page_text` 与 `source_chunk.chunk_text` 的冷热分层策略
- [ ] 明确冷数据迁移规则：按案件、时间还是按活跃度分层
- [ ] 明确热存储与冷存储的检索回源策略，确保前端证据查看不受影响

### 2.1A MinIO 原始卷宗接入

- [x] 在 `settings.py` / `.env.example` 中增加 AI Hunter 自己的 MinIO 配置项
- [x] 新增 `minio_service.py`，封装原始卷宗上传能力
- [x] 将上传文件先写入 `ai-hunter-raw`
- [ ] 将页图 / 衍生物规划写入 `ai-hunter-derived`
- [ ] 将报告、证据截图等工件规划写入 `ai-hunter-artifacts`
- [x] 为 `source_file` 增加 `storage_provider / storage_bucket / storage_key / storage_etag / storage_version`
- [x] 对外返回 `page_image_ref` 时将 `minio://` 转为域名可访问 URL
- [x] 文件归一化 `FileItem.url` 返回域名可访问 URL，同时保留内部 `storage_ref`

### 2.2 报告引用映射

- [x] 设计并新增 `report_citation_map` 或等价映射表
- [x] 明确 `citation_id -> claim_id` 的生成规则（当前正式方案：`report_ref + citation_id -> claim_id`）
- [ ] 明确报告段落、claim、citation 的一对一或一对多关系
- [x] 将报告角标回源流程接入 `/evidence/resolve`
- [x] 将前4段 / 后4段正文中的具体条目补成可点击内联角标，而不只是追溯附录
- [x] 继续提升正文角标覆盖率校验规则，补充“关键结论未挂角标”的自动告警

### 2.3 一致性与键规则

- [ ] 在代码层实现 `source_chunk.page_id` 与 `source_chunk.page_no` 的一致性保障
- [x] 在 `chunking.py` 中实现稳定 `chunk_id` 生成逻辑
- [x] 在 `normalize_entities.py` 中实现稳定 `entity_key` 生成逻辑
- [ ] 在 `deduplicate_graph_items.py` / `persist_graph.py` 中实现稳定 `relation_key` 生成逻辑

### 2.4 OCR 结构化输出增强

- [ ] 在 `ocr_service.py` 中新增 `parse_pdf_with_layout_sync()`
- [ ] 在 `ocr_service.py` 中新增 `parse_image_with_layout_sync()`
- [ ] 明确 OCR 原始返回中页级结构、bbox、尺寸字段的归一化规则
- [ ] 让 `load_chunks.py` 基于 layout 结果生成 `source_page` 与 `source_chunk`
- [x] 让 `/files/page-anchors` 基于已持久化 bbox 返回前端高亮锚点
- [ ] 选定 1 个 OCR / bbox 质量稳定的标杆案件，作为第一阶段高光演示样板
- [ ] 对标杆案件补一次人工校验，确保角标点击后的页图高亮不偏框、不落空

### 2.5 状态枚举收口

- [ ] 在代码层统一 `source_file.status` 状态常量
- [ ] 在代码层统一 `kg_entity.status` 状态常量
- [ ] 在代码层统一 `kg_relation.status` 状态常量
- [ ] 评估后续是否需要在数据库层追加 `CHECK CONSTRAINT`

### 2.5A 审计高光体验优先事项

- [x] 将前4段 / 后4段正文中的具体条目补成可点击内联角标
- [ ] 增加点击角标后的证据抽屉或等价高感知回源交互（后端首屏数据契约已就位，待前端实际页面接入）
- [ ] 增加老板 / 负责人视角的风险总览与关键指标看板
- [x] 收口 `chunk_id / entity_key / relation_key` 的稳定生成规则
- [x] 为标杆案件增加“角标 -> 证据抽屉 -> 页图高亮”发布前验收清单
- [ ] 将“脏数据也能出可溯源报告”从第一阶段全面目标，下调为第二阶段通用化目标

### 2.5B 增量更新与追加补件治理

- [ ] 明确 `source_file / source_page / source_chunk` 的 Append-only 原则，不做物理覆盖
- [ ] 在 `re_audit` 分支中新增“增量对账”逻辑，而不是默认全量覆盖重算
- [x] 为图谱对象建立 `active / superseded / invalid` 等状态流转规则
- [ ] 让模型输出 `ADD / OVERRIDE` 形式的变更指令，而不是全量图谱
- [x] 在 `re_audit` 前增加候选冲突收缩：先按 `entity_key / relation_key / claim_text` 缩圈，再交给 LLM 单点裁决
- [x] 为 `fetch_candidate_conflicts_by_chunks(...)` 明确输入输出契约，避免全量图谱 diff
- [x] 当新增材料推翻旧结论时，对旧 `kg_claim / kg_relation` 做软失效，而不是硬删除（已接入第一版 LLM 结构化 `ADD / OVERRIDE` 裁决，并保留 fallback heuristic）
- [x] 为 override 过程补 reconciliation ledger，能解释“哪条新 claim 推翻了哪条旧 claim，为什么推翻”
- [ ] 增加“旧结论被新证据取代”的结论演进展示能力
- [ ] 为每次上传 / 追加补件建立独立 `material_event` 或等价事件边界

### 2.5D 跨批实体解析与未决引用治理

- [ ] 在 `schemas.py` 为 `relation / claim` 补充 `entity_name / entity_key / relation_key` 等跨批解析锚点字段
- [ ] 调整 `extract_entities_relations` 提示词与解析逻辑：当 `temp_id` 不自洽时，至少补出端点名称
- [ ] 在 `persist_graph.py` 实现“两段式解析”：先按本批 `temp_id`，再按历史 `entity_key / canonical_name / normalized_name`
- [ ] 在 `kg_service.py` 增加 `fetch_entities_by_keys(...)` 与 `fetch_entities_by_names(...)`
- [ ] 为无法落到历史实体的 relation / claim 建 unresolved 暂存区，不再静默跳过
- [ ] 明确 unresolved 的后续处理路径：人工复核、补抽重放、日志追踪

### 2.5C 极简材料治理

- [x] 上传入口预接 `upload_batch_id / batch_name / operator_id / operator_name`，先形成批次数据契约
- [x] 上传入口计算文件 SHA256，并返回本批 `new_files / duplicate_files / suspected_mismatch_files`
- [x] `FileItem / AuditGraphState / ChatRequest / SSE` 透传批次、类别、重复文件、疑似错分文件字段
- [x] fastserver_api 三个类别接口完成后，关闭 mock 并做真实联调
- [ ] fastserver_api 批次接口确定后，把临时 `upload_batch_summary` 改为真实批次状态
- [ ] 给上传链路增加异步状态管理：处理中 / 成功 / 失败
- [ ] 增加 `confirm_suspected=true` 确认机制：疑似错分/重复时默认返回 409，本周暂不细做
- [ ] 操作员身份改为从认证态/JWT/网关 Header 获取，表单字段仅作 fallback，本周暂不细做
- [ ] 保留 OCR 对比链接与查看入口，但不做复杂系统内逐段精修交互
- [ ] 引入 OCR 质检规则与模型提示，但只做提示，不做强拦截
- [ ] 支持“追加补充材料”快速通道，不强制每次都走重型批次表单
- [x] 规划材料类别模板与缺失清单，并在 LangGraph 侧先接 mock/tool/API 契约
- [ ] 规划材料批次模型与状态机，但作为后续治理能力逐步引入

### 2.6 时间字段增强

- [ ] 评估是否为 `updated_at` 增加统一 trigger
- [ ] 如果增加 trigger，补充对应 SQL 脚本与字段注释

---

## 3. 已确认决议

- [x] `source_chunk.embedding` 维度固定为 `1024`
- [x] `source_page.page_text` 与 `source_chunk.chunk_text` 采用长期保存策略
- [x] `source_chunk.page_no` 冗余字段保留，并由代码层保证一致性
- [x] `kg_claim` 的 citation 需求采用“后续新增映射表”方案
- [x] `entity_key` / `relation_key` 稳定规则由代码层保证
- [x] `updated_at` 自动维护 trigger 本期暂不处理
- [x] `status` 字段本期保留 `TEXT`，后续由代码层枚举收口
- [x] OCR 结构化输出增强采用方案 B：保留现有纯文本接口，新增带 layout 的 OCR 方法
- [x] 原始卷宗采用 MinIO 私有部署方案，并按 3 个 bucket 分层：raw / derived / artifacts
- [x] 下一阶段优先级调整为：先做审计高光体验，再做极简材料治理，最后补系统化治理能力
- [x] 业务上允许“追加补充材料”的快速入口，但后端必须坚持增量治理
- [x] 追加补件采用 Append-only + 软失效 `superseded` 原则，不做物理覆盖和硬删除
- [x] 当前已加入 orphan relation / claim 的底线保护，避免单条坏引用打崩整条 ingest

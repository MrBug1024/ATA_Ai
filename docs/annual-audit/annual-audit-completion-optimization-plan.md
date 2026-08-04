# ATA 年度财务报表审计业务线完整优化实施文档

> 版本：v1.0
>
> 编制日期：2026-08-04
>
> 适用项目：`E:\实验室\ATA_AI`
>
> 对比基线：`E:\实验室\不良资产\NpaLang-main`、`E:\实验室\不良资产\NpaDemo-main`、`E:\实验室\不良资产\ai_hunter-main`

## 1. 文档目的与结论

本文档用于指导 ATA 年度财务报表审计业务线从“可演示的业务闭环”完善为“可追溯、可复核、可生成正式成果、可持续运行”的生产级系统。

本次只输出建设方案和配置目录，不写入任何真实配置值，不复用原“不良资产”项目的数据库、向量库、对象存储、模型密钥或其他连接信息。后续所有环境差异均应通过新的年度审计专属 `.env` 管理。

### 1.1 现状判断

当前项目已经具备年度审计专属的基础骨架：年度审计数据表、材料导入、任务、知识图谱页面、证据抽屉、销售与应收分析、现金与银行分析，以及初步的报告草稿服务。因此，它不是空项目。

但是，当前实现仍处于“业务线迁移与能力拼接阶段”，尚未形成完整的年度审计交付链路。最重要的判断如下：

| 优先级 | 结论 | 影响 |
|---|---|---|
| P0 | 证据索引链路不完整。年度分析引用只有逻辑行定位，没有接入 `source_file → source_page → source_chunk` 的真实来源链 | 证据页视图为空、图谱证据无法稳定回溯、报告引用不能作为审计工作底稿依据 |
| P0 | 当前报告服务只生成数据库中的确定性草稿文本，`artifact_ref` 为空，没有 DOCX/PDF/XLSX 成果文件 | 不能按底稿模板生成正式工作底稿和年度审计报告 |
| P0 | 当前年度审计图谱是单节点报告草稿图，没有原项目的完整审计图、复核图、分段报告生成和证据汇总链 | 没有正式报告分段、复核、重跑、引用覆盖率和任务提取能力 |
| P0 | 当前实际 `backend/.env` 仍有一批继承自旧项目的 `AI_HUNTER_*`、`CPWS_*`、旧 API 和模型键名；当前代码又同时读取 `backend/.env` 与部署目录环境文件 | 容易连接错误数据库、错误向量库或错误对象存储，配置含义与当前项目不一致 |
| P1 | 原项目的混合检索、审计指标引擎、证据工具、任务工具、复核图和进度/回收服务没有迁移到当前年度审计命名空间 | 下钻分析、知识问答、质量复核、进度管理能力不完整 |
| P1 | 当前 `source_locator_json` 面向 CSV/XLSX 行定位，PDF、图片、DOCX 和表格预览没有统一来源模型 | 不同材料类型无法用同一个证据契约展示和复核 |
| P1 | 当前知识图谱实体、关系、断言、证据链与年度结构化分析结果之间缺少稳定的主键映射和版本化重建策略 | 图谱可能出现重复实体、错误关系、过期关系和无法解释的来源 |
| P2 | 前端缺少报告、底稿、复核、进度、截止日、知识库管理和成果下载页面；后端也缺少对应 API | 已有后端能力无法形成可用工作台 |

### 1.2 完成目标

最终应形成如下闭环：

```mermaid
flowchart LR
    A[上传审计材料] --> B[原件对象存储]
    B --> C[解析/OCR/表格预览]
    C --> D[来源文件-页面-片段链]
    C --> E[年度审计结构化事实]
    D --> F[实体/关系/断言/证据链接]
    E --> G[指标计算与分析发现]
    F --> G
    G --> H[证据完整性校验]
    H --> I[八段式审计报告]
    H --> J[按模板生成工作底稿]
    I --> K[复核与修改留痕]
    J --> K
    K --> L[DOCX/PDF/XLSX 成果物]
    L --> M[引用、版本、审批、下载]
```

完成后，任何一个报告结论、底稿结论或图谱关系，都必须能够回答：

- 来自哪个租户、哪个年度审计项目和哪一批材料；
- 来自哪个原始文件、哪个页/表/行/单元格或文本区间；
- 使用了哪个解析版本、知识库版本、指标规则版本和模型版本；
- 是否经过人工复核，谁在何时修改或批准；
- 点击证据后能否看到真实页面、图片区域、表格行或明确的文本引用。

## 2. 代码与配置基线

### 2.1 当前项目已经具备的能力

当前项目的主要基础模块包括：

- `backend/ai_hunter/annual_audit/import_service.py`：CSV/XLSX/XLSM/XLS 结构化导入，并保存逻辑行定位；
- `backend/ai_hunter/annual_audit/analysis_service.py`：读取年度结构化数据，计算分析结果并保存发现；
- `backend/ai_hunter/annual_audit/evidence_service.py`：将分析发现转换为前端证据抽屉数据，但当前只做逻辑引用桥接；
- `backend/ai_hunter/annual_audit/report_service.py`：生成确定性年度报告草稿和少量工作底稿记录；
- `backend/ai_hunter/annual_audit/report_graph.py`：目前只有一个年度报告生成节点；
- `backend/app/services/kg_service.py` 与 `backend/app/api/routes_graph.py`：已有通用来源文件、页面、片段和知识图谱访问基础；
- `backend/deploy/annual-audit`：已有年度审计专属 MySQL、PostgreSQL/pgvector、Redis、MinIO 编排；
- `web/components/knowledge-graph/page-viewer.tsx`：已有文本、页面和图片证据展示入口；
- `new_docs/`：已有年度财报审计底稿、审计报告、管理建议书、函证、法律准则、CPA 资料和税务资料等源文件。

这些能力应保留并向年度审计契约收敛，不建议整体推倒重写。

### 2.2 当前关键缺口

#### 证据链缺口

当前 `annual_audit/evidence_service.py` 的行为是：

- 根据年度分析结果中的 `domain_row_type` 和 `domain_row_id` 生成临时 `chunk_id`；
- 将 `domain_row_id` 或序号当作 `file_id`；
- 将 Excel/CSV 的行号直接写成 `page_no`；
- `source_page_id=0`、`page_image_ref=""`、`source_file_url=""`、`bbox_list=[]`；
- `content_type` 固定为 `text/plain`。

因此，前端展示“文本类材料无页面视图，请查看左侧引用的原文片段”是当前代码设计的直接结果，不是单纯的前端显示故障。尤其需要注意：Excel 行号不是 PDF 页码，不能继续用 `page_no` 表示二者。

当前测试 `backend/tests/test_annual_audit_evidence_service.py` 也在断言这种文本兜底行为。修复后，该测试必须改为断言真实来源链和不同材料类型的定位契约。

#### 报告与底稿缺口

当前 `report_service.py` 使用固定版本字符串生成草稿，主要覆盖收入、应收账款、现金/银行三个逻辑底稿代码；生成的是数据库记录和文本，不是正式模板文件。`audit_report.artifact_ref` 和 `annual_workpaper.artifact_ref` 目前可以为空，因此没有真实成果物可下载。

缺失内容包括：

- 八个报告分段的上下文准备、并行生成、引用校验和汇总；
- 审计报告正文、附注、管理建议书和底稿目录的模板注册；
- 工作底稿输入项、审计程序、结论、复核状态和索引号；
- DOCX、PDF、XLSX 的渲染、版本化、对象存储和下载；
- 报告结论与底稿、分析发现、证据锚点之间的引用图；
- 报告生成失败、引用不足、模板不匹配时的阻断机制。

#### 图谱与下钻缺口

原项目的完整审计链是“完整上下文 → 指标计算 → 多报告分段 → 报告复核/任务提取”；当前项目的 `report_graph.py` 只有一个确定性报告草稿节点。当前也没有独立的年度复核图、报告分段图、指标引擎、报告引用协调节点和完整下钻工具注册。

当前图谱页面可以查询部分实体和关系，但年度结构化事实、分析发现、知识图谱断言和证据来源之间没有统一的引用主键。因此“知识图谱不太对劲”需要同时从数据建模、抽取去重、关系置信度、来源版本和前端展示五个层面修复，不能只调整图谱布局。

#### 配置缺口

当前 `.env.example` 主要覆盖年度数据库、MinIO、Redis、认证、LLM、OCR 和上传限制；但实际运行代码与原项目还涉及知识库检索、向量/嵌入、重排、指标规则、截止日、报告分段并发、复核、成果物和运维参数。当前 `backend/.env` 中的旧键名不能作为补齐依据。

## 3. 目标架构与数据边界

### 3.1 四类存储的职责

| 存储 | 目标职责 | 不应承担的职责 |
|---|---|---|
| 年度审计 MySQL | 审计项目、年度结构化事实、分析运行、发现、任务、底稿索引、报告业务状态 | 不再作为来源文件页面和向量证据的唯一存储 |
| 年度审计 PostgreSQL/pgvector | 租户与会话、来源文件/页面/片段、实体/关系/断言、证据链接、报告引用、检查点 | 不直接替代年度业务事实表 |
| 年度审计对象存储 | 原始文件、解析中间产物、页面预览、表格预览、DOCX/PDF/XLSX 成果物 | 不把 URL 直接暴露给前端作为永久凭证 |
| 年度审计 Redis | 短期缓存、任务状态、限流和可选队列 | 不保存唯一事实、唯一证据或唯一报告成果 |

知识库可以使用独立的 Qdrant 集群/集合，也可以在 PostgreSQL 使用 pgvector；无论采用哪一种，必须使用年度审计专属集合/索引前缀和新的环境变量，不能指向原项目的 `CPWS_*` 向量库。建议知识库检索和审计证据来源分开建模：知识库回答“准则、方法、程序是什么”，审计证据回答“本项目哪份材料证明了什么”。

### 3.2 建议的来源主键

所有材料都应建立以下稳定标识：

| 标识 | 说明 |
|---|---|
| `tenant_id` | 组织/客户隔离边界 |
| `engagement_id` | 一次年度审计项目，替代跨业务线混用的模糊 `case_id` 语义 |
| `source_file_id` | 原始材料的逻辑文件 ID，文件哈希、版本、上传批次属于其属性 |
| `source_page_id` | 物理页、生成的表格页或文本分页；不是业务行号 |
| `source_chunk_id` | 可检索的文本片段/表格片段；必须能回溯到文件和页面 |
| `source_locator_id` | 业务事实或发现对应的统一来源定位记录 |
| `claim_id` | 图谱断言或报告事实的逻辑 ID |
| `evidence_link_id` | 断言/发现/报告段落到来源定位的多对多链接 |
| `analysis_run_id` | 分析规则、输入快照和版本的运行 ID |
| `artifact_id` | 工作底稿、报告、附注或管理建议书成果物 ID |

`annual_*` 结构化表可以继续保存 `source_locator_json` 作为兼容字段，但生产版必须额外写入规范化来源锚点表，不能只依赖 JSON 字符串。

## 4. 证据索引与页面视图的修复方案

### 4.1 正确的导入链路

每个上传文件都要同时进入两条互相引用的链路：

1. 原文件写入年度审计对象存储的 `raw` 桶，记录哈希、文件名、媒体类型、大小、上传人、上传批次和版本。
2. 解析器按文件类型生成页面、文本片段、表格片段和预览资源，写入 PostgreSQL 的 `source_file/source_page/source_chunk`。
3. Excel/CSV 继续写入 MySQL 的年度结构化事实表，但每一行必须同步写入规范化来源锚点，关联真实的 `source_file_id/source_page_id/source_chunk_id`。
4. PDF、图片、DOCX 中抽取出的业务事实、实体和断言，统一通过来源锚点写入相同的证据链。
5. 分析发现、图谱断言、工作底稿结论和报告段落只能引用规范化锚点，不允许临时拼接 `annual:...` ID。

### 4.2 表格材料的页面视图策略

表格材料没有天然的 PDF 页码，应采用下列定位契约：

- `locator_kind=sheet_row`：工作簿、工作表、数据行号、列区间、表头快照、单元格范围；
- `locator_kind=csv_row`：文件、行号、字段范围和原始行摘要；
- `locator_kind=pdf_page`：页码、页图、文本区间、可选框选坐标；
- `locator_kind=image_region`：图片页、区域框、OCR 文本和页图；
- `locator_kind=text_span`：来源片段、字符范围和上下文。

对 Excel/CSV 建议同时生成派生预览：按工作表和行区间渲染为分页 PNG/PDF 或可控的 HTML 表格快照，存入 `derived` 桶。前端点击证据时展示工作表、行列范围和快照；如果只存在原始文件而没有快照，应显示“表格预览尚未生成”，而不是把行号冒充页码。

### 4.3 前端证据响应必须包含的字段

后端 `evidence.resolve` 和图谱关系证据接口统一返回至少以下字段：

```json
{
  "engagement_id": "...",
  "source_file_id": "...",
  "source_page_id": "...",
  "source_chunk_id": "...",
  "locator_kind": "sheet_row",
  "file_name": "...",
  "content_type": "...",
  "page_no": null,
  "sheet_name": "...",
  "row_start": 88,
  "row_end": 88,
  "cell_range": "A88:H88",
  "quote_text": "...",
  "bbox_list": [],
  "preview_available": true,
  "page_image_ref": "...",
  "source_file_url": "...",
  "citation_status": "verified",
  "parser_version": "..."
}
```

其中 `source_file_url` 和 `page_image_ref` 应由后端按权限生成短时签名地址或代理地址，不能把永久对象存储密钥、内部桶路径或未授权 URL 直接返回给浏览器。

### 4.4 证据质量门禁

新增发现、图谱断言、报告引用和底稿结论，至少要经过以下检查：

- 来源文件存在且属于当前租户和年度审计项目；
- 来源片段或表格定位存在，不能只有业务行 ID；
- PDF/图片必须有真实页面或区域；表格必须有工作表和行列定位；
- 预览不可用时必须明确标记 `preview_available=false`，不能伪造页面字段；
- 报告引用覆盖率按真实有效引用计算，不能因为存在 `trace_items` 就直接记为 1.0；
- 来源文件、解析器、OCR、嵌入、指标规则和模型版本必须可查询；
- 来源文件被替换后，旧的分析运行和报告必须保持可追溯，不应静默覆盖。

## 5. 知识库与知识图谱建设

### 5.1 年度审计知识库分层

结合当前 `new_docs` 资料，建议建立独立的年度审计知识库，不把所有材料混在一个无元数据集合中：

| 知识库 | 内容 | 检索用途 |
|---|---|---|
| `annual_regulations` | 会计准则、审计准则、法律法规、监管规定和有效期版本 | 判断适用准则、法律依据和报告表述 |
| `annual_audit_procedures` | 年度财报审计底稿、审计程序、复核要点、质量控制制度 | 推荐审计程序、底稿索引和复核事项 |
| `annual_tax_procedures` | 税务资料、税务处理和涉税审计参考 | 税会差异、税务风险和审计关注点 |
| `annual_templates` | 审计报告、附注、管理建议书、函证和底稿模板 | 模板字段、章节结构和成果物生成 |
| `annual_reference` | CPA 书籍、案例和经审批的业务参考资料 | 解释概念、补充案例和下钻分析 |

模板库与法规库必须逻辑隔离。模板中的格式、字段和索引不能被普通问答当作法规结论；法规、案例和教科书也不能直接被模板渲染器当作布局指令。

### 5.2 知识文件治理

入库前需要记录以下元数据：

- `library_id`、文档类型、来源机构、发布日期、施行日期、失效日期、适用地区和适用行业；
- 文档版本、文件哈希、原始文件 ID、页码、章节、条款号和引用格式；
- 是否经过业务专家审核、审核人、审核时间、状态和可见范围；
- 解析器/OCR 版本、分块版本、嵌入模型版本、重排模型版本；
- 是否为模板、法规、准则、程序、案例或背景参考。

`new_docs/逻辑资料V1/AI智能体相关法律、准则、底稿、案例、报告模版【20260703】/` 可以作为首批建设源目录，但在正式入库前要重新盘点文件数量、重复版本、扫描件质量、版权/授权范围和有效日期，不应直接把历史文件数量当成完成指标。

### 5.3 检索链路

建议采用“查询改写 → 关键词检索 → 向量检索 → 规则过滤 → 重排 → 引用拼装”的混合链路：

- 按租户、业务年度、知识库、有效期和权限先过滤；
- 向量召回和关键词召回保留各自的得分及来源；
- 对准则条款、底稿程序、模板字段和案例设置不同的重排权重；
- 输出必须携带文档、页码/条款和版本，不允许只返回相似文本；
- 知识库检索结果不能替代项目材料证据；二者在 UI 和数据表中明确区分。

### 5.4 知识图谱修复

图谱抽取应以年度审计项目为边界，采用以下规则：

- 实体采用 `tenant_id + entity_type + normalized_name + source_scope` 去重，保留别名和来源；
- 关系和断言采用版本化写入，不直接覆盖旧结果；
- 每个关系必须至少有一个有效证据链接、抽取运行 ID 和置信度；
- 低置信度、冲突关系和无法解析实体进入 unresolved 队列，不能直接展示为确定事实；
- 先建立“客户/主体—科目—凭证—余额—合同/回款—风险—审计程序—结论”的审计语义图，再扩展通用知识图谱；
- 图谱查询结果必须返回证据数量、最新来源日期、关系状态和冲突标志；
- 材料替换或规则升级时，通过 extraction run 重建当前版本，旧版本只读保留。

## 6. 需要迁移、重构和重新建设的代码

迁移原则是“移植业务逻辑，重写年度审计适配层；不复制旧配置，不保留会误导业务含义的旧目录名和旧环境变量名”。不建议把 `NpaDemo-main` 作为运行时依赖，它包含旧的演示型 FastAPI、数据库和外部 API 假设；可以参考其业务流程和资料说明，但不能直接接入运行链路。

### 6.1 原项目能力到年度审计命名空间的映射

| 原项目能力 | 年度审计建议新模块 | 动作 |
|---|---|---|
| `app/subgraphs/full_audit_graph.py` | `backend/app/subgraphs/annual_full_audit_graph.py` | 移植完整上下文、指标、分段生成、引用协调和任务提取；使用年度数据契约 |
| `app/subgraphs/review_graph.py` | `backend/app/subgraphs/annual_review_graph.py` | 新增年度复核图，输出复核指标、问题和修改建议 |
| `app/subgraphs/drilldown_agent_graph.py` | `backend/app/subgraphs/annual_drilldown_graph.py` | 年度专属下钻代理，限制在当前项目和授权来源范围 |
| `app/graph/metrics_engine.py` | `backend/app/graph/annual_metrics_engine.py` | 重写指标输入，接入试算平衡、科目、凭证、应收和银行事实 |
| `app/graph/report_sections.py` | `backend/app/graph/annual_report_sections.py` | 建立八段式年度报告章节注册和上下文汇总 |
| `app/graph/review_sections.py` | `backend/app/graph/annual_review_sections.py` | 建立复核章节和复核证据引用 |
| `app/graph/deadline_board.py` | `backend/app/graph/annual_deadline_board.py` | 将截止日、底稿状态、复核状态和逾期事项接入年度项目 |
| `app/graph/nodes/*report*` | `backend/app/graph/nodes/annual_report_*` | 迁移报告分段、合并、引用校验和成果物生成节点 |
| `app/graph/nodes/*review*` | `backend/app/graph/nodes/annual_review_*` | 迁移复核上下文、复核分段和复核汇总节点 |
| `app/services/knowledge_api.py` | `backend/app/services/annual_knowledge_service.py` | 只移植混合检索逻辑，替换为新年度知识库配置和元数据过滤 |
| `app/services/retrieval_api.py` | `backend/app/services/annual_retrieval_service.py` | 建立项目材料检索与知识库检索的统一接口，但分开结果类型 |
| `app/services/progress_service.py` | `backend/app/services/annual_progress_service.py` | 接入年度任务、底稿和复核进度 |
| `app/services/recovery_capture.py` | `backend/app/services/annual_followup_service.py` | 不直接保留“不良资产回收”语义；改为审计整改、后续事项和管理建议跟踪 |
| `app/tools/evidence_tools.py` | `backend/app/tools/annual_evidence_tools.py` | 只返回规范化来源锚点和权限过滤后的证据 |
| `app/tools/retrieval_tools.py` | `backend/app/tools/annual_retrieval_tools.py` | 增加知识库版本、有效期和项目范围过滤 |
| `app/tools/audit_tools.py` | `backend/app/tools/annual_audit_tools.py` | 适配年度审计指标、风险和审计程序 |
| `app/tools/task_tools.py` | `backend/app/tools/annual_task_tools.py` | 支持底稿任务、复核任务和整改跟踪 |
| `app/tools/case_tools.py` | `backend/app/tools/annual_engagement_tools.py` | 将模糊 case 语义改为年度审计项目语义 |
| `app/tools/doc_category_tools.py` | `backend/app/tools/annual_material_tools.py` | 使用年度材料分类、版本和缺口状态 |
| `routes_review.py` | `backend/app/api/routes_annual_review.py` | 新 API 路由，不复制旧路由名称和旧响应结构 |
| `routes_progress.py`、`routes_deadline.py` | `backend/app/api/routes_annual_progress.py` | 统一年度进度、截止日和逾期事项接口 |
| 旧报告 prompts | `backend/prompts/annual_report_*` | 重命名并按年度准则、模板和引用契约重写 |

### 6.2 不应直接迁移的内容

- 原项目的 `.env`、`.env.example` 实际值、数据库 DSN、MinIO 桶名、Qdrant 集合名、模型密钥和内网地址；
- `AI_HUNTER_*`、`CPWS_*`、`KIMI_*` 等历史前缀；
- 以不良资产、债务人、回收、分 tranche 为核心的业务命名；年度审计需要重新定义审计项目、被审计单位、财务期间、科目、凭证、底稿和复核语义；
- 原项目演示数据、P0 fixture、测试客户和硬编码默认账户；
- 旧的外部 `*_API_BASE_URL` 依赖，除非新的年度服务确实需要，并完成新契约、鉴权和可用性评估；
- 原项目中只为兼容旧数据库而存在的 MySQL 平台表和重复图谱表。

## 7. 报告、底稿、复核和下钻的实现要求

### 7.1 八段式年度审计报告

建议把原项目报告分段能力改造成年度审计章节注册表，第一版至少包括：

1. 数据完整性、清洗结果和重大缺失；
2. 财务报表及主要科目变动分析；
3. 收入、应收账款和回款相关风险；
4. 货币资金、银行函证和资金流水异常；
5. 截止性、关联方、期后事项和持续经营关注点；
6. 重要性水平、错报风险和审计程序响应；
7. 审计调整、管理建议和待跟踪事项；
8. 审计结论摘要、证据覆盖和复核状态。

每一段都要独立保存：输入事实快照、知识库引用、项目材料证据、模型运行、草稿、人工修改、复核人和最终状态。生成顺序可以并行，但最终汇总必须确定性排序并执行引用校验。

### 7.2 工作底稿

`new_docs` 中的年度财务报表审计底稿文件不能只作为知识库文本。应建设模板注册表和字段映射：

- 底稿编号、名称、适用科目、适用审计程序和前置条件；
- 输入事实、抽样范围、计算字段、异常事项和审计结论；
- 来源证据索引、人工填列项、复核要点和签名/日期字段；
- 模板版本、格式版本、渲染器版本和导出格式；
- 底稿之间的索引关系，例如主表、明细表、函证、盘点、截止测试和复核表。

第一阶段至少打通：底稿目录、试算平衡/科目分析、收入与应收、银行与现金、函证、期后事项、调整事项和复核清单。现有三个逻辑底稿代码只能作为迁移起点，不能作为最终覆盖范围。

### 7.3 正式成果物生成

报告和底稿生成服务必须完成以下动作：

1. 校验模板版本、项目状态、数据快照和引用覆盖率；
2. 生成结构化中间模型；
3. 将中间模型渲染到专属 DOCX/XLSX 模板；
4. 必要时转换为 PDF 并执行版式检查；
5. 将原始成果物和预览成果物写入 `artifacts` 桶；
6. 写入 `artifact_id`、哈希、版本、生成运行、审批状态和下载权限；
7. 任何生成失败或证据门禁未通过，都不能伪装为“报告已生成”。

报告状态建议至少包括：`draft`、`evidence_blocked`、`generated`、`under_review`、`approved`、`superseded`、`failed`。

### 7.4 复核与下钻

复核图应检查：指标重算、重要性水平、异常解释、证据完整性、报告引用、模板字段、审计程序响应和待办任务。下钻代理应支持：

- 从报告段落下钻到分析发现；
- 从发现下钻到科目/凭证/明细事实；
- 从事实下钻到原始文件、页面、表格行或文本区间；
- 从风险下钻到适用准则、审计程序、底稿和后续任务；
- 对每一步显示使用的检索结果、工具调用、规则版本和证据。

代理不得跨项目检索，不得在没有来源证据时补写确定性结论。无法找到证据时应输出待补充材料或人工复核任务。

## 8. 数据库与迁移设计

### 8.1 PostgreSQL/pgvector

当前 PostgreSQL 已有 `source_file`、`source_page`、`source_chunk`、图谱实体/关系/断言、证据链接和报告引用基础，应以此作为年度来源和知识图谱的规范化主库。

建议新增或完善：

- `annual_source_locator`：统一 PDF、图片、DOCX、Excel、CSV 的定位字段和预览引用；
- `annual_evidence_link`：发现、断言、报告段落、底稿结论到来源锚点的多对多链接；
- `annual_knowledge_document`、`annual_knowledge_version`：知识库文档及生效版本；
- `annual_extraction_run`、`annual_graph_review`：抽取运行、去重、冲突和人工确认；
- `annual_report_section`、`annual_report_citation`、`annual_artifact`：报告分段、引用和成果物版本；
- `annual_audit_log`：重要数据、证据、报告和权限变化审计日志。

当前 `060_annual_platform_contract.sql` 中的材料分类、上传批次、事件和未解析项可以保留其业务意图，但应纳入年度专属 schema/命名规范并补充租户、项目、版本和审计日志字段。当前 `knowledge_graph_v1.sql` 的向量维度是 1024，后续必须由 `.env` 的嵌入维度和迁移校验共同保证，不能只在代码中写死。

### 8.2 MySQL 年度业务库

当前年度 MySQL 表已经覆盖导入批次、科目余额、凭证行、应收项目、银行流水、分析运行、发现和任务，但还需要补齐或确认：

- 审计项目、被审计单位、财务期间、审计团队和项目成员；
- 试算平衡与财务报表勾稽；
- 收入、应收、现金、银行、函证、截止测试、期后事项和关联方；
- 固定资产、存货、薪酬、税务、借款、或有事项和持续经营；
- 抽样批次、抽样规则、异常项、审计调整和管理建议；
- 工作底稿索引、复核状态、报告分段状态和成果物索引。

当前 MySQL 中 `audit_source_file`、`audit_evidence_anchor`、`audit_graph_entity`、`audit_graph_relation` 与 PostgreSQL 来源/图谱表存在职责重叠。应在新迁移中明确唯一事实来源：

- MySQL 保存年度审计业务事实和业务状态；
- PostgreSQL 保存来源页面、片段、图谱和证据链接；
- 两边通过稳定 ID 关联；
- 旧重复表只读迁移，验证完成后再归档，不继续产生新写入。

### 8.3 迁移原则

- 同时支持空库初始化和已有年度数据升级；
- 每个迁移有版本、校验、回滚或补偿说明；
- 迁移前对文件哈希、结构化行数、来源锚点数、图谱实体关系数和报告引用数做快照；
- 不把旧项目数据直接导入新的年度租户；如需复用，只能经过脱敏、业务映射、重新解析和人工验收；
- 所有新表、桶、集合和索引使用年度审计前缀，避免与原项目混淆。

## 9. 新 `.env` 配置目录

本节只列配置键和用途，不提供真实值。正式实施时建议将项目根目录的 `.env` 作为唯一运行配置来源，后端、Docker Compose、迁移脚本和本地启动脚本都读取同一套年度审计键名。当前同时读取 `backend/.env` 与 `deploy/annual-audit/.env.local` 的行为应在迁移完成后收敛，避免来源覆盖顺序不透明。

命名约定：使用 `ATA_` 前缀；配置名中使用 `ANNUAL` 或 `AUDIT` 只表达年度审计用途，不使用 `AI_HUNTER`、`CPWS`、旧项目服务名或旧客户名。

### 9.1 应用与环境隔离

| 配置键 | 用途 | 建设/申请 |
|---|---|---|
| `ATA_APP_ENV` | local/test/staging/production 环境标识 | 建设 |
| `ATA_PROJECT_CODE` | 年度审计项目唯一代码，用于日志、桶、集合和任务隔离 | 建设 |
| `ATA_CONFIG_VERSION` | 配置契约版本，防止代码和环境变量错配 | 建设 |
| `ATA_BUSINESS_DOMAIN` | 固定为年度审计业务域 | 建设 |
| `ATA_APP_HOST`、`ATA_APP_PORT` | 后端监听地址和端口 | 部署申请 |
| `ATA_PUBLIC_BASE_URL` | API、回调和成果物代理的外部地址 | 部署申请 |
| `ATA_CORS_ORIGINS`、`ATA_CORS_CREDENTIALS` | 前端跨域策略 | 部署申请 |
| `ATA_LOG_LEVEL`、`ATA_LOG_DIR` | 日志级别和输出位置 | 运维建设 |

### 9.2 年度业务 MySQL

| 配置键 | 用途 | 建设/申请 |
|---|---|---|
| `ATA_DOMAIN_DB_HOST`、`ATA_DOMAIN_DB_PORT` | 年度业务 MySQL 地址 | 申请独立实例/库 |
| `ATA_DOMAIN_DB_NAME` | 年度审计业务库名 | 建设新库 |
| `ATA_DOMAIN_DB_USER`、`ATA_DOMAIN_DB_PASSWORD` | 最小权限账号和密码 | 申请账号 |
| `ATA_DOMAIN_DB_SSL_MODE` | 数据库传输加密策略 | 运维申请 |
| `ATA_DOMAIN_DB_POOL_MIN`、`ATA_DOMAIN_DB_POOL_MAX` | 连接池上下限 | 性能压测后确定 |
| `ATA_DOMAIN_DB_CONNECT_TIMEOUT`、`ATA_DOMAIN_DB_READ_TIMEOUT`、`ATA_DOMAIN_DB_WRITE_TIMEOUT` | 连接和读写超时 | 建设 |
| `ATA_DOMAIN_DB_MIGRATION_LOCK_TIMEOUT` | 迁移锁等待时间 | 建设 |

### 9.3 来源、知识图谱和检查点 PostgreSQL

| 配置键 | 用途 | 建设/申请 |
|---|---|---|
| `ATA_PLATFORM_DB_HOST`、`ATA_PLATFORM_DB_PORT` | PostgreSQL 地址 | 申请年度独立实例 |
| `ATA_PLATFORM_DB_NAME` | 来源、图谱、会话和报告引用数据库 | 建设新库 |
| `ATA_PLATFORM_DB_USER`、`ATA_PLATFORM_DB_PASSWORD` | 最小权限账号 | 申请账号 |
| `ATA_PLATFORM_DB_SSL_MODE`、`ATA_PLATFORM_DB_DSN` | 连接安全和可选完整 DSN | 运维建设 |
| `ATA_PLATFORM_DB_POOL_MIN`、`ATA_PLATFORM_DB_POOL_MAX` | 连接池参数 | 压测后确定 |
| `ATA_PLATFORM_DB_VECTOR_EXTENSION` | pgvector 扩展开关/版本要求 | DBA 申请 |
| `ATA_PLATFORM_DB_VECTOR_DIMENSION` | 嵌入维度，必须与模型和向量列一致 | 模型确认后建设 |
| `ATA_PLATFORM_DB_KG_SCHEMA_VERSION` | 知识图谱 schema 版本 | 建设 |
| `ATA_LANGGRAPH_CHECKPOINTER`、`ATA_LANGGRAPH_CHECKPOINTER_AUTO_SETUP` | 图执行检查点及自动建表策略 | 建设 |

### 9.4 Redis

| 配置键 | 用途 | 建设/申请 |
|---|---|---|
| `ATA_REDIS_HOST`、`ATA_REDIS_PORT`、`ATA_REDIS_PASSWORD`、`ATA_REDIS_DB` | Redis 连接参数 | 申请独立实例/账号 |
| `ATA_REDIS_TLS` | 是否启用 TLS | 运维建设 |
| `ATA_REDIS_NAMESPACE` | 年度审计专属键前缀 | 建设 |
| `ATA_CACHE_DEFAULT_TTL_SECONDS` | 通用缓存有效期 | 压测后确定 |
| `ATA_TASK_QUEUE_ENABLED`、`ATA_TASK_QUEUE_NAME` | 是否使用异步任务队列及队列名 | 架构决定 |
| `ATA_HEAVY_PAYLOAD_ENABLE_POSTGRES`、`ATA_HEAVY_PAYLOAD_TTL_SECONDS` | 大上下文/运行结果的存储和保留策略 | 建设 |

### 9.5 对象存储与成果物

| 配置键 | 用途 | 建设/申请 |
|---|---|---|
| `ATA_OBJECT_STORAGE_ENDPOINT`、`ATA_OBJECT_STORAGE_REGION` | 年度对象存储服务 | 申请独立服务 |
| `ATA_OBJECT_STORAGE_ACCESS_KEY`、`ATA_OBJECT_STORAGE_SECRET_KEY` | 最小权限访问账号 | 申请账号 |
| `ATA_OBJECT_STORAGE_USE_SSL` | 存储传输安全 | 运维建设 |
| `ATA_OBJECT_STORAGE_BUCKET_RAW` | 原始上传文件 | 建设年度专属桶 |
| `ATA_OBJECT_STORAGE_BUCKET_DERIVED` | OCR、页面图、表格快照和中间产物 | 建设年度专属桶 |
| `ATA_OBJECT_STORAGE_BUCKET_ARTIFACTS` | DOCX/PDF/XLSX 底稿、报告和预览 | 建设年度专属桶 |
| `ATA_OBJECT_STORAGE_BUCKET_KB` | 知识库原始文档和版本 | 建设年度专属桶 |
| `ATA_OBJECT_STORAGE_PRESIGNED_URL_TTL_SECONDS` | 短时下载/预览地址有效期 | 安全评估后确定 |
| `ATA_OBJECT_STORAGE_VERSIONING`、`ATA_OBJECT_STORAGE_SERVER_SIDE_ENCRYPTION` | 对象版本和静态加密 | 运维建设 |
| `ATA_OBJECT_STORAGE_MAX_OBJECT_SIZE` | 单文件和成果物大小限制 | 业务评估后确定 |

### 9.6 LLM、嵌入和重排服务

| 配置键 | 用途 | 建设/申请 |
|---|---|---|
| `ATA_LLM_DEFAULT_PROVIDER` | 默认模型供应商 | 采购/申请 |
| `ATA_LLM_ROUTER_PROVIDER` | 路由、澄清和意图识别模型 | 采购/申请 |
| `ATA_LLM_AUDIT_PROVIDER` | 审计分析模型 | 采购/申请 |
| `ATA_LLM_REPORT_PROVIDER` | 报告分段和汇总模型 | 采购/申请 |
| `ATA_LLM_REVIEW_PROVIDER` | 复核模型 | 采购/申请 |
| `ATA_LLM_DRILLDOWN_PROVIDER` | 下钻代理模型 | 采购/申请 |
| `ATA_LLM_EXTRACTION_PROVIDER` | 实体、关系、断言抽取模型 | 采购/申请 |
| `ATA_LLM_RECONCILIATION_PROVIDER` | 引用、冲突和报告协调模型 | 采购/申请 |
| `ATA_LLM_*_BASE_URL`、`ATA_LLM_*_API_KEY`、`ATA_LLM_*_MODEL` | 各供应商独立地址、密钥和模型 | 采购/申请 |
| `ATA_LLM_*_TIMEOUT_SECONDS`、`ATA_LLM_*_MAX_TOKENS`、`ATA_LLM_*_TEMPERATURE` | 各用途超时、长度和随机性 | 压测/评估后确定 |
| `ATA_LLM_RETRY_MAX_ATTEMPTS`、`ATA_LLM_RETRY_BACKOFF_SECONDS` | 失败重试和退避 | 建设 |
| `ATA_LLM_REPORT_CONCURRENCY`、`ATA_LLM_REVIEW_CONCURRENCY` | 报告/复核并发度 | 压测后确定 |
| `ATA_LLM_JSON_MODE_REQUIRED` | 结构化输出是否强制 JSON | 模型能力确认后建设 |

### 9.7 年度审计知识库

| 配置键 | 用途 | 建设/申请 |
|---|---|---|
| `ATA_KB_ENABLED` | 年度知识库总开关 | 建设 |
| `ATA_KB_PROVIDER` | Qdrant、pgvector 或其他检索后端 | 架构决定 |
| `ATA_KB_QDRANT_URL`、`ATA_KB_QDRANT_API_KEY` | Qdrant 地址和访问凭证 | 申请独立实例 |
| `ATA_KB_COLLECTION_PREFIX` | 年度集合前缀 | 建设 |
| `ATA_KB_COLLECTION_REGULATIONS` | 法规准则集合 | 建设 |
| `ATA_KB_COLLECTION_AUDIT_PROCEDURES` | 审计程序和底稿集合 | 建设 |
| `ATA_KB_COLLECTION_TAX_PROCEDURES` | 税务集合 | 建设 |
| `ATA_KB_COLLECTION_TEMPLATES` | 模板与字段说明集合 | 建设 |
| `ATA_KB_COLLECTION_REFERENCE` | CPA、案例和参考集合 | 建设 |
| `ATA_KB_EMBEDDING_BASE_URL`、`ATA_KB_EMBEDDING_API_KEY`、`ATA_KB_EMBEDDING_MODEL` | 嵌入服务 | 采购/申请 |
| `ATA_KB_EMBEDDING_DIMENSION`、`ATA_KB_EMBEDDING_TIMEOUT_SECONDS` | 向量维度和超时 | 模型确认后建设 |
| `ATA_KB_RERANK_BASE_URL`、`ATA_KB_RERANK_API_KEY`、`ATA_KB_RERANK_MODEL` | 重排服务 | 采购/申请 |
| `ATA_KB_TOP_K_VECTOR`、`ATA_KB_TOP_K_KEYWORD`、`ATA_KB_TOP_K_RERANK` | 各阶段召回数量 | 评估后确定 |
| `ATA_KB_MIN_SCORE`、`ATA_KB_VECTOR_WEIGHT`、`ATA_KB_KEYWORD_WEIGHT` | 最低分和混合权重 | 离线评测后确定 |
| `ATA_KB_INDEX_VERSION` | 当前知识库索引版本 | 建设 |
| `ATA_KB_ACCESS_POLICY` | 知识库租户/角色访问策略 | 安全建设 |

### 9.8 文件解析、OCR 和页面预览

| 配置键 | 用途 | 建设/申请 |
|---|---|---|
| `ATA_OCR_BACKEND`、`ATA_OCR_BASE_URL`、`ATA_OCR_API_KEY` | OCR 服务 | 采购/申请 |
| `ATA_OCR_TIMEOUT_SECONDS`、`ATA_OCR_VERIFY_SSL`、`ATA_OCR_MAX_PARALLEL` | OCR 超时、安全和并发 | 压测后确定 |
| `ATA_OCR_LANGUAGES` | 中文、英文及数字混合识别范围 | 业务确认 |
| `ATA_OCR_PDF_SPLIT_ENABLED`、`ATA_PDF_RENDERER`、`ATA_PDF_RENDER_DPI` | PDF 拆页和页面图渲染 | 建设 |
| `ATA_DOCX_PARSER`、`ATA_XLSX_PARSER`、`ATA_CSV_PARSER` | 文档和表格解析器 | 建设 |
| `ATA_PARSER_VERSION`、`ATA_OCR_VERSION` | 可追溯的处理版本 | 建设 |
| `ATA_EXCEL_PREVIEW_ENABLED`、`ATA_EXCEL_PREVIEW_FORMAT` | 表格快照是否生成以及格式 | 建设 |
| `ATA_EXCEL_PREVIEW_MAX_ROWS`、`ATA_EXCEL_PREVIEW_MAX_COLUMNS` | 单个快照范围 | 性能评估后确定 |
| `ATA_UPLOAD_MAX_FILES`、`ATA_UPLOAD_MAX_FILE_MB`、`ATA_UPLOAD_MAX_IMAGE_MB` | 上传限制 | 安全/业务确认 |
| `ATA_UPLOAD_ALLOWED_EXTENSIONS` | 支持的材料类型 | 业务确认 |
| `ATA_SOURCE_SIGNED_URL_TTL_SECONDS` | 证据预览地址有效期 | 安全评估后确定 |
| `ATA_EVIDENCE_REQUIRE_CANONICAL_ANCHOR` | 是否禁止无真实来源锚点的结论 | 生产必须开启 |
| `ATA_EVIDENCE_ALLOW_TEXT_FALLBACK` | 真实预览暂不可用时是否允许文本兜底 | 仅调试或明确标记时开启 |

### 9.9 图谱、规则和分析

| 配置键 | 用途 | 建设/申请 |
|---|---|---|
| `ATA_KG_ENABLED` | 年度知识图谱开关 | 建设 |
| `ATA_KG_EXTRACTION_PROMPT_VERSION` | 抽取提示词版本 | 建设 |
| `ATA_KG_ENTITY_CONFIDENCE_MIN`、`ATA_KG_RELATION_CONFIDENCE_MIN`、`ATA_KG_CLAIM_CONFIDENCE_MIN` | 图谱入库置信度门槛 | 离线评测后确定 |
| `ATA_KG_RECONCILIATION_MODE` | 冲突关系处理策略 | 业务确认 |
| `ATA_KG_UNRESOLVED_POLICY` | 未解析实体/关系处理策略 | 业务确认 |
| `ATA_KG_MAX_GRAPH_DEPTH`、`ATA_KG_MAX_NODES` | 下钻和图查询资源限制 | 压测后确定 |
| `ATA_KG_CACHE_TTL_SECONDS` | 图谱查询缓存 | 建设 |
| `ATA_AUDIT_RULESET_VERSION` | 年度审计规则总版本 | 业务建设 |
| `ATA_MATERIALITY_RULESET_VERSION`、`ATA_MATERIALITY_CONFIG_REF` | 重要性水平规则和配置引用 | 审计专家确认 |
| `ATA_SAMPLING_RULESET_VERSION`、`ATA_SAMPLING_DEFAULT_RATE` | 抽样规则和默认比例 | 审计专家确认 |
| `ATA_CONFIRMATION_RULESET_VERSION` | 函证规则 | 审计专家确认 |
| `ATA_AMOUNT_DECIMALS`、`ATA_CURRENCY`、`ATA_AMOUNT_DISPLAY_UNIT` | 金额精度、币种和展示单位 | 业务确认 |
| `ATA_AGING_BUCKETS`、`ATA_CUT_OFF_DAYS` | 账龄和截止测试参数 | 审计专家确认 |
| `ATA_DEADLINE_RED_DAYS`、`ATA_DEADLINE_YELLOW_DAYS` | 截止日看板颜色阈值 | 项目管理确认 |

### 9.10 报告、底稿和复核

| 配置键 | 用途 | 建设/申请 |
|---|---|---|
| `ATA_REPORT_ENABLED`、`ATA_WORKPAPER_ENABLED` | 报告和底稿生成总开关 | 建设 |
| `ATA_REPORT_TEMPLATE_ROOT`、`ATA_REPORT_TEMPLATE_VERSION` | 报告模板目录和版本 | 业务建设 |
| `ATA_WORKPAPER_TEMPLATE_ROOT`、`ATA_WORKPAPER_TEMPLATE_VERSION` | 底稿模板目录和版本 | 业务建设 |
| `ATA_REPORT_SECTION_COUNT` | 报告分段数量 | 业务确认 |
| `ATA_REPORT_GENERATION_MODE` | 确定性、LLM 或混合生成模式 | 架构决定 |
| `ATA_REPORT_SECTION_TIMEOUT_SECONDS`、`ATA_REPORT_SECTION_CONCURRENCY` | 分段超时和并发 | 压测后确定 |
| `ATA_REPORT_ARTIFACT_FORMATS` | DOCX/PDF/XLSX 等成果格式 | 业务确认 |
| `ATA_REPORT_REQUIRE_EVIDENCE` | 是否强制所有结论有证据 | 生产必须开启 |
| `ATA_REPORT_MIN_CITATION_COVERAGE` | 报告生成最低引用覆盖率 | 审计专家确认 |
| `ATA_REPORT_EXPORT_DOCX`、`ATA_REPORT_EXPORT_PDF`、`ATA_REPORT_EXPORT_XLSX` | 各格式导出开关 | 建设 |
| `ATA_REPORT_DRAFT_ONLY_UNTIL_APPROVED` | 未审批前是否只能标记为草稿 | 生产必须开启 |
| `ATA_REPORT_SECTION_PROVIDER_01` 至 `ATA_REPORT_SECTION_PROVIDER_08` | 各报告段模型或规则提供方 | 评估后确定 |
| `ATA_REVIEW_SECTION_COUNT` | 复核段数量 | 业务确认 |
| `ATA_REVIEW_SECTION_PROVIDER_01` 至 `ATA_REVIEW_SECTION_PROVIDER_03` | 各复核段提供方 | 评估后确定 |
| `ATA_ARTIFACT_RETENTION_DAYS` | 成果物保留期限 | 合规确认 |

### 9.11 认证、租户和权限

| 配置键 | 用途 | 建设/申请 |
|---|---|---|
| `ATA_AUTH_ENABLED`、`ATA_AUTH_IDENTITY_MODE` | 认证开关和身份来源 | 安全建设 |
| `ATA_AUTH_JWT_SECRET` 或 `ATA_AUTH_JWT_PUBLIC_KEY` | Token 签名/验签 | 申请密钥/证书 |
| `ATA_AUTH_JWT_ALGORITHM`、`ATA_AUTH_ACCESS_TOKEN_MINUTES` | 算法和有效期 | 安全确认 |
| `ATA_AUTH_PASSWORD_MIN_LENGTH` | 密码策略 | 安全确认 |
| `ATA_AUTH_DEV_TRUST_HEADERS` | 开发环境信任请求头；生产必须关闭 | 建设 |
| `ATA_TENANT_REQUIRED`、`ATA_ENGAGEMENT_ACCESS_REQUIRED` | 租户和年度项目访问门禁 | 生产必须开启 |
| `ATA_ROLE_PERMISSIONS_JSON` | 角色与功能权限映射 | 安全建设 |
| `ATA_REPORT_SECTION_ACL_ENABLED` | 报告段和底稿权限 | 安全建设 |
| `ATA_AUDIT_LOG_RETENTION_DAYS` | 数据、证据、报告和审批日志保留期 | 合规确认 |

### 9.12 运维、可靠性和安全

| 配置键 | 用途 | 建设/申请 |
|---|---|---|
| `ATA_JOB_WORKER_COUNT`、`ATA_JOB_TIMEOUT_SECONDS` | 解析、分析、报告和导出的异步 worker | 压测后确定 |
| `ATA_JOB_MAX_RETRIES` | 异步任务重试次数 | 建设 |
| `ATA_METRICS_ENABLED`、`ATA_METRICS_ENDPOINT` | 指标采集 | 运维建设 |
| `ATA_TRACING_ENABLED`、`ATA_TRACING_ENDPOINT` | 链路追踪 | 运维建设 |
| `ATA_ERROR_REPORTING_DSN` | 错误采集服务 | 申请/可选 |
| `ATA_PII_REDACTION_ENABLED`、`ATA_SECRET_MASKING_ENABLED` | 日志和模型输入脱敏 | 生产必须开启 |
| `ATA_BACKUP_ENABLED`、`ATA_BACKUP_RETENTION_DAYS` | 数据库和对象存储备份 | 运维申请 |
| `ATA_RATE_LIMIT_ENABLED`、`ATA_RATE_LIMIT_PER_USER` | API 限流 | 安全建设 |

上述键名是目标配置契约，不要求现在马上写入值。实施时应先由开发、DBA、运维、信息安全和审计业务负责人分别确认“申请、建设、废弃、默认值和环境差异”，然后再生成 `.env.example` 和各环境密钥托管方案。

## 10. 前后端接口与页面补齐清单

### 10.1 后端 API

建议新增年度专属路由，路径和模块名称均不要复用旧项目含义：

- `POST /api/annual-audit/engagements/{engagement_id}/review`：运行年度复核图；
- `GET /api/annual-audit/engagements/{engagement_id}/progress`：项目、材料、底稿、复核和报告进度；
- `GET /api/annual-audit/engagements/{engagement_id}/deadlines`：截止日和逾期事项；
- `POST /api/annual-audit/engagements/{engagement_id}/reports/generate`：按模板生成报告；
- `GET /api/annual-audit/engagements/{engagement_id}/reports`：报告版本列表；
- `GET /api/annual-audit/reports/{artifact_id}/download`：权限校验后的成果物下载；
- `POST /api/annual-audit/engagements/{engagement_id}/workpapers/generate`：按底稿模板生成；
- `GET /api/annual-audit/engagements/{engagement_id}/workpapers`：底稿索引、状态和证据覆盖；
- `GET /api/annual-audit/evidence/{evidence_link_id}`：规范化证据详情和页面/表格预览；
- `POST /api/annual-audit/knowledge/search`：年度知识库检索；
- `GET /api/annual-audit/knowledge/versions`：知识库和规则版本；
- `POST /api/annual-audit/graph/rebuild`：按材料版本重建图谱；
- `GET /api/annual-audit/graph/conflicts`：冲突关系和未解析项。

所有 API 都必须带租户、项目、权限、运行版本和错误状态；报告和底稿接口不能只返回一段文本。

### 10.2 前端页面

需要在现有聊天和案件入口之外补齐：

- 年度审计项目总览和进度看板；
- 材料分类、缺口、解析状态和预览；
- 图谱实体、关系、断言、冲突和来源链；
- 证据详情页：PDF/图片页、表格工作表/行列快照、文本片段三种视图；
- 报告章节生成、引用覆盖、草稿/复核/批准和版本比较；
- 底稿目录、模板版本、字段填充、复核和下载；
- 年度知识库版本、入库任务、失效文档和检索测试；
- 截止日、复核任务、整改事项和审计日志。

## 11. 实施阶段与优先级

### P0：先修复可信数据链

1. 收敛为年度审计独立配置命名空间，清理旧环境变量引用；
2. 确定 MySQL、PostgreSQL、对象存储、Redis、向量库的全新实例/库/桶/集合；
3. 建立来源文件、页面、片段和结构化行的统一来源锚点；
4. 修复年度证据服务和前端页面预览；
5. 将当前证据测试改为真实来源链测试；
6. 对现有年度材料重新解析和回填来源锚点；
7. 对图谱实体、关系、断言执行版本化重建和人工抽样验收。

P0 完成标志：任意一条年度分析发现都能打开真实来源或明确的表格快照，不能再把行号当页码，也不能只凭临时 ID 生成证据。

### P1：补齐交付能力

1. 移植并改造年度完整审计图；
2. 新增八段式报告图、报告引用协调和任务提取；
3. 新增年度复核图和复核 API；
4. 建立年度底稿模板注册与 DOCX/XLSX/PDF 渲染；
5. 将报告、底稿、证据和审批关联到成果物版本；
6. 新增下钻代理和年度审计工具；
7. 补齐前端报告、底稿、复核、进度和下载页面。

### P2：建设知识和规则资产

1. 盘点 `new_docs`，去重、分类、确认有效期和授权；
2. 建立五类年度审计知识库和元数据；
3. 上线混合检索、重排、引用和检索评测集；
4. 建立重要性、抽样、函证、截止测试、账龄等规则版本；
5. 让报告和底稿引用知识库版本与项目证据版本。

### P3：生产运营与质量控制

1. 建立异步任务、重试、限流、监控、追踪和告警；
2. 建立备份、恢复演练、权限审计和成果物保留策略；
3. 建立审计专家抽样复核和模型回归评测；
4. 建立从材料上传到最终报告的全链路回归数据集。

## 12. 验收标准

### 12.1 证据与图谱

- 100% 新增发现都有 `source_file_id`、`source_chunk_id` 或明确的表格来源锚点；
- PDF/图片证据可看到真实页面或区域；Excel/CSV 可看到工作表、行列和预览快照；
- 证据接口不再默认返回 `source_page_id=0`、空页面引用和伪造页码；
- 抽取关系均有来源、置信度、运行版本和冲突状态；
- 删除、替换或重解析材料后，旧版本仍能回溯，当前图谱不会静默混入旧版本；
- 图谱查询可以从实体/关系下钻到断言、发现和原始材料。

### 12.2 报告与底稿

- 八个报告段均能独立生成、重试、复核、查看引用和重新汇总；
- 底稿按专属年度模板生成，不是只有数据库文本；
- DOCX、PDF、XLSX 成果物可下载，且 `artifact_ref` 不为空、哈希可校验、版本可追溯；
- 报告引用覆盖率按真实证据链接计算，达不到阈值时报告进入 `evidence_blocked`；
- 复核后可以生成新版本，旧版本只读保留；
- 未经批准的成果物不能显示为最终审计报告。

### 12.3 配置与安全

- 代码和启动脚本不再依赖 `AI_HUNTER_*`、`CPWS_*` 或旧项目配置键；
- 当前项目不存在指向原项目数据库、Qdrant、MinIO、模型服务的默认连接；
- 所有环境差异均能在年度审计 `.env` 中解释，密钥进入受控密钥存储而不是代码或日志；
- 生产关闭开发信任请求头，所有来源、报告和成果物接口均有租户/项目权限校验；
- 空库初始化、升级迁移、备份恢复和回归测试均可重复执行。

### 12.4 业务回归场景

至少准备以下端到端场景：

- 一套完整财务报表、科目余额、凭证、应收和银行材料；
- 一份扫描 PDF、一份图片、一份 DOCX、一份 XLSX 和一份 CSV；
- 缺页、重复版本、错误分类、表头变化和 OCR 低置信度材料；
- 一条可追溯收入异常、一条应收账款异常和一条银行流水异常；
- 报告生成、人工修改、复核驳回、重新生成和最终批准；
- 无证据结论、冲突图谱关系、权限越界和材料替换等负面场景。

## 13. 当前检查结果与后续责任分工

本方案基于当前项目和原项目的只读代码、迁移文件、配置样例、前端接口和测试进行对比。当前工作区原有的 `.gitignore` 修改未参与本次方案编辑；本次只新增本实施文档，没有改动 `.env`、代码、数据库或前端文件。

建议后续按责任人拆分：

| 责任角色 | 首要交付 |
|---|---|
| 审计业务负责人 | 八段式报告目录、底稿目录、模板字段、重要性/抽样/复核规则和验收样例 |
| 后端/数据工程 | 来源锚点、证据服务、图谱重建、年度完整图、复核图和报告/底稿 API |
| 前端工程 | 页面/表格/图片证据预览、报告底稿工作台、版本和权限展示 |
| DBA/运维 | 新数据库、pgvector/Qdrant、Redis、MinIO、迁移、备份和监控 |
| 模型/知识工程 | 文档治理、嵌入/重排、提示词、规则版本和离线评测 |
| 信息安全/合规 | 账号权限、密钥托管、数据隔离、留存期限和审计日志 |

最终完成的判断不是“页面能打开”或“模型返回了文本”，而是：从一份真实年度审计材料上传开始，到一条审计发现、一个图谱关系、一张底稿和一份报告结论，均能被权限范围内的人员复核、定位、解释、版本化和下载。


# ATA AI 公共基础项目与业务解耦实施方案

> 版本：v1.0  
> 日期：2026-08-04  
> 适用项目：`E:\实验室\ATA_AI`  
> 对比基线：`E:\实验室\不良资产\NpaLang-main`、`E:\实验室\不良资产\ai_hunter-main`、`E:\实验室\不良资产\NpaDemo-main`

## 1. 结论先行

当前 `ATA_AI` 不是一个已经完成抽象的公共平台，而是以原不良资产项目为基础、删减部分旧业务后接入年审业务形成的业务项目。这个状态可以继续开发年审，但不适合再作为以后其他业务线的基础模板。

正确方向不是把原项目目录整体复制过来，也不是把不良资产代码直接改名为年审代码，而是建立四层边界：

1. **平台核心层**：所有业务线共用的运行时、认证租户、会话、LangGraph 编排、Agent、文件处理、证据链、知识图谱、向量检索接口、任务、审计日志、对象存储和前端通用组件。
2. **领域契约层**：平台只定义接口和数据契约，例如“加载项目上下文”“执行分析”“解析证据”“生成底稿”“创建任务”，不写具体业务判断。
3. **业务插件层**：年审、不良资产以及未来税务、尽调等业务线各自实现领域接口、工具、提示词、规则、报告章节和事务数据库。
4. **应用装配层**：根据 `.env` 选择业务域、数据库、知识库、模型路由和功能开关，组装成一个可运行的 API 或前端应用。

目标结构如下：

```text
platform-foundation/                 # 建议最终独立为可复用包或独立仓库
├─ platform_core/
│  ├─ config/                         # 通用配置加载、校验、脱敏、环境分层
│  ├─ api/                            # FastAPI 外壳、认证中间件、SSE、错误协议
│  ├─ identity/                       # 用户、租户、角色、权限、项目成员
│  ├─ runtime/                        # 请求上下文、会话、LangGraph checkpoint
│  ├─ agent/                          # Agent 构建、工具注册、能力路由、降级
│  ├─ ingest/                         # 上传、解析、OCR、版面、切片、幂等
│  ├─ evidence/                       # source_file/page/chunk、引用、证据解析
│  ├─ knowledge_graph/                # 实体、关系、断言、抽取运行、冲突和待处理项
│  ├─ retrieval/                      # 关键词、向量、混合检索的统一端口
│  ├─ storage/                        # PostgreSQL、Redis、MinIO、向量库适配器
│  ├─ task/                           # 任务、截止日期、进度、操作日志
│  └─ observability/                  # request_id、审计日志、指标、健康检查
├─ domain_contracts/                  # 平台与业务域之间的稳定协议
├─ domains/
│  ├─ annual_audit/                   # 年审：财务数据、审计规则、底稿、报告
│  └─ npa/                            # 不良资产：回收、债务人、资产处置等
├─ apps/
│  ├─ annual_audit_api.py             # 年审装配入口
│  └─ npa_api.py                      # 不良资产装配入口
└─ web/
   ├─ platform/                      # 通用登录、会话、上传、证据、图谱、任务组件
   └─ domains/                       # 各业务线页面、表单、报表和导航
```

短期不要求立即拆成多个 Git 仓库。可以先在 `ATA_AI/backend` 内完成包边界和依赖方向，再把 `platform_core` 提取成独立包。关键是从现在开始不再让年审直接依赖不良资产业务模块，也不再让公共模块依赖某个业务领域的命名。

## 2. 对原项目与当前项目的核查结果

### 2.1 原不良资产项目已经具备的公共能力

原 `NpaLang-main` 的价值主要不在不良资产业务规则，而在它已经跑通了一套较完整的 AI 业务平台骨架：

| 能力 | 原项目代表位置 | 结论 |
|---|---|---|
| 顶层 LangGraph 编排 | `ai_hunter/app/graph/main.py` | 抽取为平台编排器；路由结果交给业务插件 |
| 完整审计图 | `ai_hunter/app/subgraphs/full_audit_graph.py` | 抽取“上下文—分析—并行章节—归并”机制，章节内容不能照搬 |
| 复核图 | `ai_hunter/app/subgraphs/review_graph.py` | 抽取为通用复核流程，复核规则按业务实现 |
| 下钻 Agent | `ai_hunter/app/subgraphs/drilldown_agent_graph.py`、`app/graph/nodes/run_drilldown_agent.py` | 抽取 Agent 生命周期、权限工具集、递归限制、降级和追踪 |
| 证据工具与引用 | `app/tools/evidence_tools.py`、`app/services/evidence_api.py` | 抽取证据契约和引用解析，不保留不良资产语义 |
| 上传、OCR、切片 | `app/services/chunking.py`、`ocr_service.py`、`app/graph/nodes/load_chunks.py` | 抽取通用解析管线 |
| MinIO 文件存储 | `app/services/minio_service.py` | 抽取对象存储适配器，桶和前缀必须按业务域隔离 |
| 知识图谱 | `app/services/kg_service.py`、`sql/knowledge_graph_v1.sql` | 抽取实体、关系、断言、证据链和图查询 |
| 认证与权限 | `app/services/user_service.py`、`sql/auth_*.sql` | 抽取平台身份与租户权限；业务角色权限单独注册 |
| 会话、Checkpoint、重载 | `app/graph/checkpointer.py`、`heavy_state.py`、相关 SQL | 抽取运行时能力；Redis key 和 checkpoint 线程必须带业务域与租户 |
| 任务、进度、截止日期 | `task_api.py`、`progress_service.py`、`material_event_progress.py` | 抽取通用任务协议；不良资产回收进度不能进入核心层 |
| 前端证据抽屉和图谱 | `ai_hunter-main/components/knowledge-graph/*`、`components/shared/*` | 抽取展示组件、数据请求和预览协议 |

### 2.2 不能作为公共代码的原业务

以下内容即使代码形式相似，也只能保留在 `domains/npa`：

- 债务人、资产包、抵押物、回收、处置、回款预测、清收进度和回收方案。
- 不良资产专用的 `screening_*`、`case_party`、`recovery_*` 等表和服务。
- CPWS 法律文书库、案件库、裁判文书检索、其专用 Qdrant collection 和 embedding 语义。
- 不良资产专用的报告章节、提示词、指标、工具、示例数据、路由意图和页面导航。
- `NpaDemo-main` 的旧演示 API、旧数据库假设和旧外部接口。它只能作为业务流程参考，不能成为 ATA_AI 的运行时依赖。

### 2.3 当前 ATA_AI 的真实状态

当前项目已经复制或实现了不少公共骨架，但装配仍是“年审专用”：

- `backend/ai_hunter/app/graph/main.py` 已有输入规范化、记忆、项目上下文、文件导入、能力路由、业务线子图、任务和最终回答流程。
- `backend/ai_hunter/app/subgraphs/business_line_executors.py` 已把 `audit.full`、`audit.reaudit`、`audit.drilldown`、`graph.query` 绑定到年审实现，但这只是业务装配，不是公共能力抽象。
- 年审业务位于 `backend/ai_hunter/annual_audit`，包括导入、科目/分录/应收/银行分析、发现、任务、底稿和报告草稿。
- 当前年审报告图 `annual_audit/report_graph.py` 实际是一个确定性报告草稿节点，不等于原项目的八段式全审图。
- 当前工具注册 `app/tools/registry.py` 只注册年审工具。原项目中的通用证据工具、案件工具、检索工具、任务工具并没有被整理成平台工具层。
- 当前后端同时存在 PostgreSQL 公共证据/图谱表和 MySQL 年审结构化业务表。这种分层方向是对的，但两者之间的源定位关系还没有完成。

因此，当前不建议继续复制原项目目录。应当先确定公共接口，再把原项目公共代码迁移到接口后面，最后由年审插件实现具体业务。

## 3. 分层与依赖规则

### 3.1 依赖方向

必须遵守下面的单向依赖：

```text
apps / API 装配
        ↓
domain plugins  ←→  domain_contracts
        ↓                  ↑
platform_core  ────────────┘
        ↓
PostgreSQL / MySQL / Redis / MinIO / Vector Store / LLM / OCR
```

具体规则：

1. `platform_core` 不得 import `annual_audit` 或 `npa`。
2. 任何数据库表名、MinIO bucket、Redis key、向量 collection、提示词路径都不能写死在公共模块中。
3. 业务插件只能通过 `EvidencePort`、`GraphPort`、`VectorStorePort`、`ReportRendererPort`、`TaskPort` 等接口调用平台能力。
4. 业务插件可以依赖平台公共模型，但平台不能依赖业务模型。公共模型中的字段应使用 `project_id`、`domain_code`、`source_file_id` 等中性名称，不能出现 `recovery_id` 或 `annual_receivable_id`。
5. API 的通用响应结构可以共用；业务字段放入明确版本化的 `data` 或 `extension` 对象，避免把年审字段塞进所有业务线响应。
6. 前端通用组件只接收标准证据、图谱、文件预览和任务协议；年审页面负责组装财务分析结果，不在通用组件里判断“应收账款”或“回收率”。

### 3.2 公共层、适配层、业务层判断表

| 模块 | 公共层可直接复用 | 只能复用接口/框架 | 业务层必须重写或隔离 |
|---|---|---|---|
| LLM 客户端、模型路由、重试 | 是 | 模型角色名由业务注册 | 年审/不良资产提示词与输出结构 |
| LangGraph State、checkpoint、SSE | 是 | state 扩展字段由业务定义 | 各业务 graph 节点 |
| Agent、工具权限、递归限制 | 是 | 每个域提供工具集 | 业务查询和写入工具 |
| 文件上传、哈希、幂等、OCR | 是 | 文档分类器按域注册 | 财务材料/资产材料分类规则 |
| source_file/page/chunk | 是 | 表格定位和特殊预览由适配器实现 | 业务事实和分析结果 |
| 证据链、引用解析 | 是 | EvidenceRef 由业务填充 | 业务 finding/claim 的生成规则 |
| KG 实体关系模型 | 是 | 业务本体和实体类型由域注册 | 不良资产本体、年审本体 |
| 关键词/向量/混合检索 | 是 | collection、过滤器、embedding 由域配置 | CPWS、不良资产法律检索语义 |
| 认证、租户、项目成员、审计日志 | 是 | 业务角色/权限点由域注册 | 业务操作授权规则 |
| 任务、截止日、状态流转框架 | 是 | 任务类型由域注册 | 回收任务、审计整改任务 |
| PostgreSQL 公共表 | 是 | 按 schema/租户/域隔离 | 年审事务表、不良资产事务表 |
| MySQL 连接能力 | 是 | 连接目标按域配置 | 年审财务表和 NPA 业务表不能共库 |
| MinIO 客户端 | 是 | bucket/prefix 按域配置 | 业务产物命名和生命周期 |
| 前端 PDF/图片/文本/表格预览 | 是 | 表格需要 sheet/row/grid 契约 | 业务页面和报表 |
| 报告章节并行生成和归并 | 是 | SectionSpec 由域提供 | 年审八章节、不良资产报告章节 |
| 底稿/报告模板渲染器 | 是 | 模板版本和字段映射由域提供 | 年审客户模板、NPA 客户模板 |

## 4. 建议的公共基础能力清单

### 4.1 运行时与配置

从原项目抽取并改造成中性命名：

- `Settings`：只负责加载当前项目 `.env`、校验必需配置、输出脱敏摘要。
- `ProviderRouter`：按角色选择 LLM、embedding、OCR、reranker，允许业务域覆盖默认模型。
- `RuntimeContext`：携带 `tenant_id`、`project_id`、`domain_code`、`user_id`、`thread_id`、`request_id`。
- `CapabilityRegistry`：能力名称、业务线、读写模式、工具集、执行器和版本。
- `GraphBuilder`：统一创建入口图、业务子图、checkpoint 和执行事件。
- `DegradedResult`：外部服务不可用时明确返回降级状态，不能把降级结果伪装成审计结论。

配置加载必须只有一个事实来源：当前运行项目的 `backend/.env`。旧项目 `.env`、部署目录示例和旧变量名只能用于迁移检查，不能自动回退读取。

### 4.2 文件、解析、证据公共链路

公共链路应统一为：

```text
上传文件
  → MinIO raw 对象
  → source_file
  → 解析/OCR/表格快照
  → source_page / source_chunk
  → 业务结构化事实
  → claim / finding / graph relation
  → evidence_link
  → workpaper/report citation
```

`source_file`、`source_page`、`source_chunk` 是平台证据主键，不允许业务服务临时拼接假的 chunk ID。业务数据库可以保存 `source_locator_json` 作为兼容字段，但生产引用必须至少有：

```text
domain_code
project_id
source_file_id
source_page_id（适用时）
source_chunk_id（适用时）
locator_kind
quote_text
parser_version
source_hash
```

表格材料需要增加平台级定位契约：

```text
locator_kind = sheet_row | cell_range | csv_row | pdf_page | image_region | text_span
sheet_name
row_start / row_end
cell_range
page_no
bbox_list
preview_ref
```

### 4.3 知识图谱公共能力

公共层保留实体、关系、断言、证据连接、抽取运行、冲突台账和 unresolved 队列。业务域只提供：

- 实体类型和标准化规则。
- 关系类型和方向约束。
- 业务字段到实体/关系的映射器。
- 抽取提示词和置信度阈值。
- 哪些实体允许跨项目共享，哪些只能在项目内存在。

年审图谱至少要围绕“被审计单位—科目—凭证—客户/供应商—应收项目—银行交易—审计发现—审计程序—证据”建立本体。不能直接套用“不良资产—债务人—资产包—回收事件”的本体。

每次抽取必须有 `extraction_run_id`、输入材料版本、模型版本、规则版本、时间和操作者；新版本不能无痕覆盖旧关系。

### 4.4 向量与混合检索公共能力

公共层只定义 `VectorStorePort` 和混合检索流程：

```text
权限/租户过滤
  → 关键词召回
  → 向量召回
  → 可选重排
  → 业务域过滤
  → 返回带 source_file/page/chunk 的引用结果
```

不能把原项目 CPWS 检索函数直接搬进公共层。CPWS 文书库属于不良资产/法律域的外部知识源；年审应建设独立的会计准则、审计准则、审计程序、底稿模板和客户项目材料知识库。

向量 collection 必须至少按以下维度隔离：

- `domain_code`：`annual_audit`、`npa` 等。
- `library_code`：法规、程序、模板、项目材料等。
- `embedding_model` 与 `embedding_dimension`。
- `parser_version` 与 `knowledge_version`。
- `tenant_id` 或项目可见范围。

不同 embedding 模型或不同维度不能写入同一 collection。物理上可以共用 Qdrant/pgvector 集群，逻辑 collection 必须隔离。

## 5. 数据库、缓存、对象存储和知识库策略

### 5.1 总体原则

“能共用基础设施”不等于“能共用业务数据”。建议采用：

| 存储 | 可以共用的部分 | 必须隔离的部分 |
|---|---|---|
| PostgreSQL | 认证、会话、checkpoint、公共证据、KG、任务框架、审计日志 | 业务字段、租户/项目可见范围、业务本体；生产优先使用独立 schema 或独立库 |
| MySQL | 驱动、连接池、迁移工具 | 年审 `ata_ai` 与 NPA 事务库绝不共库；不使用旧 `ata_agent` 等名称作为隐式回退 |
| Redis | Redis 服务实例、客户端代码 | key namespace、TTL、序列化版本、租户/项目标识、队列名称 |
| MinIO | MinIO 服务、SDK、签名 URL 服务 | bucket 或 key prefix、生命周期、权限、原始/派生/产物目录 |
| Qdrant/pgvector | 集群、连接适配器、检索协议 | collection、embedding 模型、知识库、租户/项目过滤 |
| LLM/OCR | 公共客户端、限流、重试、监控 | 业务提示词、模型角色、敏感数据策略、结果缓存和预算 |

### 5.2 PostgreSQL 公共库

可进入公共平台 schema 的表包括：

- `app_user`、角色、权限、公司/租户、项目成员、认证审计日志。
- `conversation_messages`、LangGraph checkpoint、`heavy_payload_store`。
- `source_file`、`source_page`、`source_chunk`、上传批次、文档分类。
- `kg_entity`、`kg_relation`、`kg_claim`、`kg_evidence_link`、抽取运行、冲突台账和 unresolved 项。
- 公共任务、截止日、事件和报告引用映射。

当前公共表大量使用 `case_id`，这是从原项目带来的业务命名。抽取时应改为 `project_id` 或 `work_item_id`，通过兼容迁移逐步消除“所有业务都是 case”的假设。年审的 `engagement_id`、NPA 的 `case_id` 都应映射为平台 `project_id`，保留各自领域 ID 作为业务扩展字段。

真正实现多业务共库前，必须完成以下任一方案：

1. 推荐：公共平台 schema 与每个业务 schema 分离，并用 `tenant_id/project_id/domain_code` 做强制过滤。
2. 过渡：同一 schema 中所有公共表新增 `domain_code` 和 `project_id`，所有查询强制带条件，并增加数据库级约束或行级安全策略。

不能只靠应用代码约定，因为证据、图谱和会话一旦串租户，后续无法可靠追溯。

### 5.3 年审 MySQL

年审 MySQL 只保存年审事务和分析快照：

- `audit_engagement`、项目成员、线程和年审任务。
- `annual_import_batch`、科目余额、序时账/凭证、应收、银行交易。
- `annual_analysis_run`、`annual_finding`、`annual_workpaper`、报告状态。

当前 `ata_ai` 可以作为年审数据库名，但数据库名不是公共架构契约。代码不得再要求固定为 `ata_agent`，也不能通过旧数据库名回退。未来 NPA 应使用自己的事务库；公共平台只通过仓储接口访问它们。

年审 MySQL 的结构化记录必须增加或关联标准源定位字段；至少不能只保存 `source_locator_json` 和业务行号。

### 5.4 Redis

物理上可以继续使用线上 Redis，但 namespace 必须从模糊的 `ata:online:` 改成包含项目和环境的稳定形式，例如：

```text
ata:{environment}:{domain_code}:{tenant_id}:{area}:{key}
```

本地和线上不能只靠同一个 namespace 区分。会话、checkpoint、heavy payload、限流、任务队列和缓存应各自有前缀，并带序列化版本。任何通用模块都不能直接写 `case:` 或 `npa:` 前缀。

### 5.5 MinIO

建议继续采用业务域专属桶或“公共桶 + 强制前缀”之一，不混用原不良资产桶：

```text
annual_audit/
  raw/{tenant_id}/{project_id}/{file_id}/...
  derived/{tenant_id}/{project_id}/{file_id}/...
  artifacts/{tenant_id}/{project_id}/{report_id}/...

npa/
  raw/{tenant_id}/{project_id}/{file_id}/...
  derived/{tenant_id}/{project_id}/{file_id}/...
  artifacts/{tenant_id}/{project_id}/{report_id}/...
```

原始文件、派生预览、报告产物必须区分生命周期和权限。证据接口返回短时签名 URL 或后端代理地址，不返回永久密钥和内部对象路径。

### 5.6 知识库建设

年审知识库建议至少拆成：

| library_code | 内容 | 是否进入向量检索 |
|---|---|---|
| `annual_regulations` | 会计准则、审计准则、税法和监管规则，带生效/失效日期 | 是 |
| `annual_procedures` | 审计程序、函证、截止性、账龄、银行和凭证复核规则 | 是 |
| `annual_templates` | 客户底稿、审计报告、管理建议书、函证等模板和字段定义 | 可检索，模板渲染另行使用 |
| `annual_reference` | CPA 参考资料和经过审核的案例 | 是，必须标注参考性质 |
| `annual_project_materials` | 当前项目上传材料的解析片段 | 是，但只允许项目授权范围访问 |

模板、法规、客户证据三类内容必须在 UI 和数据模型中明确区分。知识库检索结果不能替代项目原始证据；报告结论必须引用项目证据或明确标记为规则参考。

## 6. 当前年审关键缺口与修复要求

### 6.1 证据索引全部显示文本模式

根因已经定位到 `backend/ai_hunter/annual_audit/evidence_service.py`：

- `chunk_id` 被临时拼成 `annual:{domain_row_type}:{domain_row_id}:{ordinal}`。
- `source_page_id` 固定为 `0`。
- `page_image_ref`、`source_file_url` 为空。
- `bbox_list` 为空。
- `content_type` 固定为 `text/plain`。
- Excel 行号被放入 `page_no`，但 Excel 行号不是 PDF 页码。

前端 `web/components/knowledge-graph/page-viewer.tsx` 对 `text/*` 显示“文本类材料无页面视图，请查看左侧引用的原文片段”，因此这个提示本身没有错，错的是后端把所有年审证据都伪装成了文本材料。

修复顺序：

1. 导入文件时先写入公共 `source_file/source_page/source_chunk`，并保留真实 `content_type`、对象引用、解析版本和哈希。
2. 年审 MySQL 的每条结构化记录保存真实 `source_file_id/source_page_id/source_chunk_id`，或通过平台 `evidence_anchor` 表关联。
3. 业务 finding 只引用标准 `EvidenceRef`，不再生成 `annual:*` 假 ID。
4. PDF/图片返回真实页面、图片引用和坐标框；纯文本仍然可以使用文本模式。
5. Excel/CSV 增加 `sheet_row`、`cell_range`、`preview_ref` 展示模式。若客户要求真正页面视图，则把表格区域渲染成带行列的 PNG/PDF 并存入 MinIO；不能把行号冒充页码。
6. 证据解析接口返回 `preview_available`、`locator_kind`、`preview_status`。预览未生成时显示“表格预览尚未生成”，不要误报成文本类材料。
7. 增加跨层测试：分析发现 → evidence.resolve → source_file/page/chunk → MinIO 预览，必须能够闭环。

### 6.2 知识图谱不准确或与原项目差距大

当前年审有图谱入口和年度抽取提示词，但年审结构化分析结果、公共 KG 断言和证据源之间没有形成统一主键链路。主要问题是：

- 年审发现主要保存在 MySQL `annual_finding`，公共图谱使用另一套来源模型。
- 业务行号、source chunk、页面和对象预览之间没有稳定映射。
- 当前图谱抽取使用年审领域提示词，但公共图谱的实体去重、版本、冲突和证据质量规则还没有成为统一服务。
- 直接复用不良资产实体类型会产生错误本体，例如把年审客户、科目、凭证误归入债务人或资产关系。

修复要求：

- 建立 `annual_audit` 本体注册表，不复用 NPA 本体名称。
- 每条实体、关系、断言都绑定 `project_id`、`extraction_run_id`、证据连接和置信度。
- 先以确定性结构化数据建立高可信节点，再用 LLM 抽取补充关系；低置信度结果进入 unresolved 队列。
- 图谱查询必须返回证据数量、来源文件、最新抽取版本、冲突状态和权限过滤结果。
- 不允许以“有图谱节点”代替“有可复核证据”。

### 6.3 下钻分析

原项目已经有通用 ReAct 下钻 Agent；当前年审只绑定了少量年审工具，更多时候依赖确定性 fallback。因此要把下钻拆成平台 Agent 框架和年审工具集：

平台负责：

- 读取运行上下文和权限。
- 选择业务域工具集。
- 限制递归深度、工具次数、超时和预算。
- 记录每次工具调用、输入摘要、输出引用和降级原因。
- 强制工具输出携带证据或“不足以支持结论”的状态。

年审负责：

- 余额、序时账、凭证、应收、银行、函证、截止性、账龄等工具。
- 年审规则版本和计算口径。
- 年审图谱查询适配器。
- 年审知识库检索适配器。

不良资产负责自己的债务人、资产、回收、处置和法务工具。工具名称和权限点也不要继续使用容易误导的旧业务命名。

### 6.4 底稿与年度审计报告

当前 `annual_audit/report_service.py` 的产物本质上是确定性 Markdown 草稿和少量 `annual_workpaper` 数据库记录，不能视为正式底稿/审计报告生成链路。缺口包括：

- 没有真正的客户模板加载、字段映射、模板版本校验。
- 没有完整的报告章节注册、并行生成、归并和一致性检查。
- `artifact_ref` 没有形成可下载的 DOCX/PDF/XLSX 产物链。
- 底稿行、报告段落、发现和证据之间没有稳定 citation map。
- 没有复核、修改留痕、重新生成和版本比较闭环。

应恢复原项目的通用章节生成与归并框架，但把报告章节换成年审 `SectionSpec`。建议年审第一版至少建设：

1. 项目范围与资料完整性。
2. 重大错报风险和总体审计策略。
3. 货币资金与银行。
4. 营业收入与截止性。
5. 应收账款与账龄。
6. 存货/固定资产/其他重大科目（按资料可用性启用）。
7. 凭证、关联方、税务和异常事项。
8. 审计发现、调整建议、管理建议和待复核事项。

每个章节都必须输出：正文、事实、计算结果、引用、未解决问题、人工复核状态和生成版本。最终渲染器再根据年审模板生成 DOCX/PDF/XLSX，文件上传 MinIO，数据库只保存元数据和版本引用。

## 7. 年审领域插件应实现的接口

建议在 `domain_contracts` 中定义中性接口，年审实现如下：

```python
class AuditDomainAdapter(Protocol):
    domain_code: str

    def load_project_context(self, project_id: str) -> ProjectContext: ...
    def classify_material(self, file: SourceFile) -> MaterialClassification: ...
    def ingest_structured_data(self, source: ParsedSource) -> IngestResult: ...
    def run_analyses(self, project_id: str, run_id: str) -> AnalysisResult: ...
    def resolve_evidence(self, ref: EvidenceRef) -> ResolvedEvidence: ...
    def build_workpapers(self, result: AnalysisResult) -> WorkpaperSet: ...
    def build_report_sections(self, result: AnalysisResult) -> list[ReportSection]: ...
    def create_followup_tasks(self, result: AnalysisResult) -> list[TaskDraft]: ...
```

平台公共接口建议包括：

- `ObjectStorePort`：上传、下载、删除、签名 URL、对象元数据。
- `SourceRegistryPort`：文件、页面、片段、解析版本和定位。
- `EvidencePort`：EvidenceRef、证据链接、引用解析和覆盖率。
- `KnowledgeGraphPort`：实体、关系、断言、抽取运行、查询和冲突。
- `VectorStorePort`：按域/知识库/模型版本检索。
- `AgentRuntimePort`：工具集、调用记录、超时、降级、预算。
- `ReportRendererPort`：模板注册、字段映射、渲染、产物上传、版本。
- `TaskPort`：任务、状态、截止日、指派、审计日志。

接口稳定后，原 NPA 和年审分别实现 adapter，未来新业务只需要实现领域接口和领域 UI，不再复制整个项目。

## 8. 配置分类与 `.env` 迁移原则

### 8.1 可以共用“配置含义”的项目级配置

这些配置的客户端含义可以共用，但值仍由当前项目 `.env` 管理：

- FastAPI host/port、日志级别、请求超时、SSE 心跳。
- LLM/OCR/embedding 客户端的 endpoint、超时、重试、并发和模型路由机制。
- PostgreSQL/Redis/MinIO 驱动参数的命名和校验规则。
- JWT、密码哈希、会话和审计日志的机制。
- 公共上传大小、允许扩展名、解析超时和任务并发的机制。

### 8.2 必须按业务项目更换的配置

以下值必须由年审单独维护，不能使用原不良资产的值：

- `PROJECT_CODE`、`BUSINESS_DOMAIN`、环境名和 Redis namespace。
- MySQL database/user/password；年审使用自己的 `ata_ai`，不能回退到原 `ata_agent`。
- PostgreSQL schema 或 database namespace；即使物理实例共用，也必须有业务域和租户边界。
- MinIO bucket/prefix；年审使用年审桶，不使用原 NPA 桶。
- 向量库 collection、知识库编码、embedding 模型和维度。
- 年审 LLM 角色模型、提示词目录、报告章节配置和规则版本。
- 年审 API 的能力注册、工具白名单、任务类型和模板版本。
- 前端 API base URL、业务导航、域标识和上传材料分类。

### 8.3 配置清理原则

- 不读取 `E:\实验室\不良资产` 下的 `.env`。
- 不把原项目真实密钥、数据库地址、MinIO 地址、Qdrant 地址复制进新项目。
- 不在公共代码中保留 `CPWS_*`、`RECOVERY_*`、`DEBTOR_*` 等 NPA 专用变量。
- 旧变量只允许出现在迁移检查文档或兼容脚本，不允许作为运行时 fallback。
- `.env.example` 只列变量、用途、是否必填和示例占位符，不写生产密钥。
- 每次启动输出脱敏后的“配置摘要”，至少包含域、数据库名、Redis namespace、MinIO bucket、向量 collection 和模型名，便于发现串库；禁止输出密码和 API key。

## 9. 分阶段迁移实施顺序

### 阶段 0：冻结边界和合同

- 冻结年审现有业务表和 API 的兼容版本。
- 建立 `domain_code/project_id/tenant_id` 语义。
- 定义 `EvidenceRef`、`GraphClaim`、`ReportSection`、`DegradedResult` 和 `RuntimeContext`。
- 标记所有旧 NPA 模块、变量、表和前端页面，不再新增依赖。

### 阶段 1：抽取平台核心

- 把配置、FastAPI 外壳、认证、SSE、checkpoint、heavy payload、Redis、MinIO、OCR、chunking、任务框架移到 `platform_core`。
- 将 `case_id` 等旧命名包在兼容 adapter 内，公共模型逐步改成 `project_id`。
- 统一工具注册、能力注册、Agent 调用事件和错误/降级协议。

### 阶段 2：统一证据和导入链路

- 先修复年审证据链，所有结构化行引用真实公共 source 记录。
- 建立表格预览模型和 MinIO 派生预览。
- 把报告、图谱和前端证据抽屉统一到同一个 `EvidenceResolveResponse`。
- 为每个证据链增加自动化闭环测试。

### 阶段 3：统一图谱和检索接口

- 将 KG 的抽取运行、实体归并、关系版本、冲突和证据链接抽取到平台。
- 年审注册专属本体；NPA 保留 NPA 本体。
- 建立关键词、向量和混合检索端口，并按 collection/模型/租户隔离。

### 阶段 4：恢复通用审计编排能力

- 将原八段式全审、复核、下钻的流程框架迁移到平台。
- 年审提供自己的 context loader、metrics、section specs、tools 和 prompts。
- 不把原不良资产章节、工具和提示词放入年审。

### 阶段 5：实现年审正式产物

- 建立模板注册、模板版本、字段映射、底稿生成、报告生成和 MinIO 产物管理。
- 建立 `report_citation_map`，让每个底稿结论和报告段落可回到证据。
- 增加复核、修改、重跑、版本比较和下载。

### 阶段 6：用第二业务线验证基础架构

- 以 NPA 作为第二个插件接入，而不是把 NPA 旧代码继续留在公共层。
- 验证两个业务线同时运行时的 PostgreSQL、Redis、MinIO、向量库和权限隔离。
- 再考虑是否拆成独立仓库、公共 Python 包和公共前端包。

## 10. 验收标准

### 平台隔离

- 年审启动时不会读取原不良资产 `.env`、旧数据库名或旧 API。
- 两个业务域使用相同公共服务实例时，Redis、MinIO、向量库和 PostgreSQL 查询不会串数据。
- 公共模块 import 图中不出现 `annual_audit` 或 `npa`。

### 证据与图谱

- PDF、图片、Excel、CSV、文本分别返回正确的定位类型。
- 证据点击可以返回原文件、真实页/表/行/单元格或明确的预览不可用状态。
- 任何 finding、KG claim、报告段落都能通过稳定 ID 回到 source_file/page/chunk。
- 图谱结果包含版本、置信度、证据数量和冲突状态。

### Agent 与报告

- 下钻调用只使用当前业务域授权工具，并保存调用轨迹。
- 工具、模型或知识库不可用时，返回可见的降级状态，不伪造确定性结论。
- 年审全审能够按章节生成、归并、校验引用并创建任务。
- 底稿和年度审计报告可以按模板生成真实 DOCX/PDF/XLSX，产物可从 MinIO 下载并具有版本。
- 重跑或修正后，旧版本仍可查询，新版本有明确输入、规则、模型和模板版本。

## 11. 本次改造的明确边界

本方案允许共用“基础设施和公共代码”，不允许共用“业务数据和业务语义”。因此：

- 可以共用 PostgreSQL/Redis/MinIO/Qdrant 服务实例、SDK、连接池、监控和迁移机制。
- 可以共用图谱、向量搜索、下钻、证据、报告编排的框架。
- 不共用原不良资产数据库中的业务表、样例数据、知识库 collection、MinIO bucket、Redis key 空间和业务提示词。
- 年审的 `ata_ai` 只属于年审事务数据；公共 PostgreSQL 只承载经过隔离设计的平台数据。
- 原项目代码迁移以“抽公共能力 + 业务 adapter”为准，不以“目录复制 + 全局改名”为准。

这套边界完成后，年审是第一个业务插件，不良资产是第二个业务插件，后续新业务只需实现领域契约和业务 UI，就可以复用图谱、向量检索、下钻、证据链、任务、权限和产物生成能力。

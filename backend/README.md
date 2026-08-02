# AI Hunter 统一后端

AI Hunter 的单体 FastAPI 后端。它把 LangGraph AI 编排与原 NpaDemo 确定性领域引擎合并到一个 Python 包、一个进程和一个端口，面向不良资产（NPA）处置场景提供**完整审计 / 下钻追问 / 任务督办 / 修正重审 / 回款复盘**，并配套案件、材料、知识图谱与回款闭环能力。

会话状态由 `langgraph-checkpoint-postgres` 持久化；长报告等大对象走三层存储（进程 → Redis → Postgres），与对话消息物理隔离。

## 当前能力

意图分流（`classify_intent` 后四路）：

- `full_audit`：基于真实案件上下文生成**八段式审计报告**（8 段专家子 agent 并行生成，reconcile 拼接 + 角标 + 任务提取）
- `drilldown`：挂载 **18 个工具**的 LangGraph tool-calling agent，做局部穿透、检索与任务操作
- `re_audit`：先把口头修正抽成**权威订正**（`extract_correction` 写 `case_correction` 表），再基于原始数据 + 订正**重跑** `full_audit`，而非在旧报告上做文本修补。订正写库后**跨会话/跨人、每次审计自动应用**，全程可追溯（决策三）
- `review`：**AI 回款复盘** —— 预期 vs 实际三视角对账（总量 / 时点 / 处置路径）+ 差异归因 + 经验规则建议

支撑能力：

- **权限网关**（Tier 3）：认证信任**用户中心 JWT**（本服务为信赖方，只验签取身份）+ 授权本项目自管（角色→报告段落 audience 分权 + 模块级分权）+ 五维人员标签。默认 `AUTH_ENABLED=false` 放行，灰度上线

- **知识图谱**：实体 / 关系 / 断言 / 证据抽取入库，报告角标 → 证据抽屉 → 页图高亮的引用链，实体子图可视化
- **回款闭环看板**：案件进度、预期·实际回款、回收率、催收·利润提醒，实收自动捕获（`pending → confirm` 防污染）
- **确定性数值引擎**：报告口径（去毒净值 / NPV / 回收率 / 回款）由引擎按口径算好，LLM 只解读不重算；金额统一万元 / 4 位 / 无千分位
- **checkpointer**：LangGraph 会话持久化（Postgres / 内存）
- **memory**：只保留轻量对话记忆，长报告不进消息历史
- **wenshu retrieval**：裁判文书关键词 + `bge-m3` 向量混合检索（直连 `cpwsdata` 库）

## 目录概览

```text
ai_hunter/app/
  api/                FastAPI 路由（chat / files / graph / progress / review）
  graph/              主图、节点、状态、LLM 工厂、确定性数值引擎、复盘对账引擎
  graph/nodes/        每个节点一个文件；state.py 定义 AuditGraphState
  prompts/            八段式报告、复盘、路由、下钻、图谱抽取等提示词
  services/           后端 API / 检索 / 知识图谱 / 进度看板等数据访问封装
  subgraphs/          ingest / full_audit / drilldown / review / build_knowledge_graph 子图
  tools/              工具注册表与 18 个下钻工具实现
  scripts/            大对象存储维护等运维脚本
ai_hunter/domain_engine/
  api.py               原 8080 案件、审计与任务接口
  documents.py         文档分类、解析与结构化入库
  integration.py       将领域路由注册到统一 FastAPI 应用
  db.py                领域数据库访问
scripts/domain_engine/ 领域排障与只读检查脚本
sql/                  DDL（首次启动前手动执行，除非开启自动建表）
tests/                pytest 用例（仅此目录被收集）
docs/                 部署指南、前端联调手册、各特性设计稿
```

## 架构说明

主图入口见 [ai_hunter/app/graph/main.py](/Users/liuyize/NpaLangG/ai_hunter/app/graph/main.py)，节点顺序写死在 `build_audit_orchestrator_graph()` 里，是顶层编排的唯一来源。

整体流转：

```text
normalize_input
  → hydrate_memory_context
  → resolve_case_context
  → hydrate_case_graph_context
  → (should_ingest_files?) ──是──→ ingest_graph → summarize_ingest_result ┐
                            └─否────────────────────────────────────────┘
  → classify_intent
  → 四路分流：
      · full_audit  →  full_audit_graph
      · review      →  review_graph
      · re_audit    →  extract_correction → full_audit_graph
      · drilldown   →  drilldown_agent_graph
  → (full_audit/re_audit 后 should_create_tasks? → create_tasks)
  → finalize_answer
  → persist_conversation_memory
```

子图（[ai_hunter/app/subgraphs/](/Users/liuyize/NpaLangG/ai_hunter/app/subgraphs/)）：

- `ingest_graph`：文件解析、实体/关系/断言抽取、结构化入库
- `full_audit_graph`：`fetch_full_context → compute_metrics → [8 段专家子 agent 并行] → reconcile_report`（拼接 + 角标 + 任务提取 + 预期回款种子化 + 风险聚合）
- `review_graph`：`fetch_review_context（拉回款数据 + 确定性三视角对账） → [复盘 3 段 R1/R2/R3 并行] → reconcile_review`
- `drilldown_agent_graph`：工具型追问与任务操作（18 个工具）
- `build_knowledge_graph_graph`：知识图谱构建管线

> **重审 ≠ 改旧报告**：修正请求落到 `correction_records` / `user_corrections`，再让 `full_audit_graph` 用原始数据 + 修正台账重跑。
> **复盘是只读对账**：不改 `case_progress`、不抽任务、不种子化预期；只计已确认（confirmed）实收。

## 环境要求

- Python `>= 3.11`
- PostgreSQL（checkpointer + 业务库）
- Redis（大对象热缓存，可选但推荐）
- 可访问业务 FastAPI 服务（案件 / 审计 / 任务 / 企业画像 / 文档分类）
- 可访问至少一个 OpenAI-compatible 模型服务

依赖定义在 [pyproject.toml](/Users/liuyize/NpaLangG/pyproject.toml)。

## 安装

```bash
python3 -m pip install -e '.[dev]'
```

首次启动前手动建表（除非设了 `LANGGRAPH_CHECKPOINTER_AUTO_SETUP=true`）：

```bash
# 用业务库连接串执行 DDL（去掉 POSTGRES_DSN 里的 +psycopg 后缀即为标准 psql DSN）
psql "postgresql://postgres:***@10.0.10.114:5432/ai_hunter" -f sql/langgraph_checkpointer.sql
# 按需执行其余 DDL：knowledge_graph_v1.sql / heavy_payload_store.sql / conversation_messages.sql
#   material_events.sql / recovery_progress.sql / kg_unresolved_items.sql / sql_doc_category_tables.sql 等
```

## 配置

- [`.env.example`](/Users/liuyize/NpaLangG/.env.example)：带注释模版
- [`.env`](/Users/liuyize/NpaLangG/.env)：本地运行配置（已被 gitignore）

### 一键切换主模型

```env
LLM_DEFAULT_PROVIDER=minimax
```

支持的 provider：`minimax` / `kimi` / `faker` / `openai`。

### 角色级多模型协作

只改 `.env` 即可让某个角色换厂商，不必改代码：

```env
LLM_DEFAULT_PROVIDER=minimax
LLM_PROVIDER_ROUTER=kimi
LLM_PROVIDER_AGENT=faker
```

角色：`router`（意图路由）/ `report_a`（报告段，复盘段同样走此角色）/ `report_b` / `agent`（下钻代理）。

> 八段式报告还按段做 provider 分流：核心分析段（资产/资金流/盘活/博弈）走 `kimi` 分摊负载，其余走默认（minimax）；各 provider 独立并发信号量，单端点故障会回退默认 provider。

### 已接入的模型厂商配置

#### MiniMax 中国区

```env
MINIMAX_BASE_URL=https://api.minimaxi.com/v1
MINIMAX_API_KEY=...
MINIMAX_MODEL_ROUTER=MiniMax-M2.7
MINIMAX_MODEL_REPORT_A=MiniMax-M2.7
MINIMAX_MODEL_REPORT_B=MiniMax-M2.7
MINIMAX_MODEL_AGENT=MiniMax-M2.7
```

#### Kimi（默认模型 `Kimi-k2.6`）

```env
KIMI_BASE_URL=https://api.moonshot.cn/v1
KIMI_API_KEY=...
KIMI_MODEL_ROUTER=kimi/Kimi-k2.6
KIMI_MODEL_REPORT_A=kimi/Kimi-k2.6
KIMI_MODEL_REPORT_B=kimi/Kimi-k2.6
KIMI_MODEL_AGENT=kimi/Kimi-k2.6
```

#### Faker Gateway（vLLM 风格路径，本地 / CI 模型替换）

```env
FAKER_MODEL_BASE_URL=https://faker-model.rhzy.ai/v1
FAKER_MODEL_API_KEY=...
FAKER_MODEL_ROUTER=vllm/google/gemma-4-26B-A4B-it
FAKER_MODEL_REPORT_A=vllm/google/gemma-4-26B-A4B-it
FAKER_MODEL_REPORT_B=vllm/google/gemma-4-26B-A4B-it
FAKER_MODEL_AGENT=vllm/google/gemma-4-26B-A4B-it
```

### 可调旋钮（均可选，不设则用代码默认）

```env
# 八段式报告并发（按 provider 限流，避免 529 过载）
REPORT_SECTION_CONCURRENCY=3
REPORT_SECTION_CONCURRENCY_KIMI=3
REPORT_SECTION_CONCURRENCY_MINIMAX=3

# 确定性数值引擎（报告口径）
METRICS_DISCOUNT_RATE=0.12          # NPV 折现率
METRICS_AMOUNT_DECIMALS=4           # 报告金额小数位
# METRICS_TRANCHE_YEARS / _ALLOCATION / _WEIGHT / _ZEROING_REQUIRES 见 graph/metrics_engine.py

# 回款看板提醒阈值
RECOVERY_OVERDUE_DAYS=60                 # 催收逾期宽限天数
PROFIT_DISTRIBUTION_THRESHOLD_PCT=85     # 利润分配触发阈值（%）

# 司法时效看板红黄绿阈值
DEADLINE_RED_DAYS=30                     # 红色预警：剩余 ≤30 天
DEADLINE_YELLOW_DAYS=90                  # 黄色预警：剩余 ≤90 天

# 权限网关（私有化本地身份 / 用户中心 JWT，授权本项目自管）
AUTH_ENABLED=false                       # false=放行(灰度)；true=强制鉴权
AUTH_IDENTITY_MODE=private               # private=私有化本地身份；platform=平台用户中心
USER_CENTER_JWT_ALG=HS256                # HS256 / RS256
USER_CENTER_JWT_SECRET=                  # HS256 密钥；RS256 用 USER_CENTER_JWT_PUBLIC_KEY
AUTH_DEV_TRUST_HEADERS=true              # 无 JWT 时是否信任 X-User-Id/X-User-Roles 开发头
AUTH_JWT_COMPANY_CLAIM=company           # JWT 中公司/机构 id 的 claim 名
AUTH_JWT_APPS_CLAIM=apps                 # JWT 中可访问产品码列表的 claim 名
AUTH_REQUIRE_PROJECT_ACCESS=false        # platform 模式是否要求 apps 包含 AUTH_PROJECT_CODE
AUTH_PROJECT_CODE=ai_hunter              # 本项目产品码
AUTH_LEGACY_ROLES_ENABLED=false          # v2 迁移期是否允许 JWT/dev header roles 回退；私有化生产应关闭
AUTH_LOCAL_JWT_SECRET=                   # private 本地登录 JWT 密钥；生产必须配置强随机值
AUTH_LOCAL_ACCESS_TOKEN_MINUTES=480      # 本地 access token 有效期
AUTH_PASSWORD_HASH_ALGO=argon2id         # 本地密码哈希算法
AUTH_PASSWORD_MIN_LENGTH=10              # 最小密码长度
AUTH_PASSWORD_FAILED_LOCK_THRESHOLD=5    # 连续失败 N 次锁定
AUTH_PASSWORD_LOCK_MINUTES=15            # 锁定分钟数
```

## 统一服务配置

```env
UNIFIED_API_BASE_URL=http://127.0.0.1:8081
# 内部领域路由仍校验服务身份；使用独立随机密钥，禁止提交真实值
AUDIT_API_TOKEN=
```

原 `AUDIT_API_BASE_URL`、`TASK_API_BASE_URL`、`CASE_API_BASE_URL`、`KNOWLEDGE_API_BASE_URL`、`ENTERPRISE_API_BASE_URL` 和 `DOC_CATEGORY_API_BASE_URL` 仅作为拆分部署回滚兼容项；正常单体部署保持为空，统一回退到 `UNIFIED_API_BASE_URL`。`AUDIT_API_TOKEN` 不是用户登录 JWT。

### LangGraph Checkpointer 数据库

```env
POSTGRES_DSN=postgresql+psycopg://postgres:***@10.0.10.114:5432/ai_hunter
LANGGRAPH_CHECKPOINTER=postgres
```

> `LANGGRAPH_CHECKPOINTER=postgres` 走基于连接池的**同步** `PostgresSaver`；Postgres 不可达时回退 `MemorySaver`（**测试通过不代表持久化生效**）。SSE 流式用一份**单独编译的异步图**（`AsyncPostgresSaver`），同步 / 异步 checkpointer 不可互换。`settings.postgres_checkpointer_dsn` 会去掉 `+psycopg` 后缀再交给 LangGraph。

### Heavy Payload 三层存储

大对象（报告、全量上下文等）依次走：① 进程内缓存 ② Redis 热缓存 ③ PostgreSQL 持久化。

```env
REDIS_URL=redis://10.0.10.2:6379/0
HEAVY_PAYLOAD_TTL_SECONDS=86400
HEAVY_PAYLOAD_ENABLE_POSTGRES=true
HEAVY_PAYLOAD_PRUNE_BATCH_SIZE=500
```

### 裁判文书 / 向量检索库

```env
CPWS_DB_HOST=10.0.10.114
CPWS_DB_PORT=5434
CPWS_DB_NAME=cpwsdata
CPWS_QDRANT_BASE_URL=http://10.0.10.2:6333
CPWS_QDRANT_COLLECTION=case_chunks_000
CPWS_EMBEDDING_BASE_URL=http://10.0.10.2:8111/v1/embeddings
CPWS_EMBEDDING_MODEL=bge-m3
```

## 运行 FastAPI

```bash
python -m ai_hunter
```

服务入口见 [ai_hunter/app/main.py](/Users/liuyize/NpaLangG/ai_hunter/app/main.py)。

## 接口总览

| 路由文件 | 端点 | 作用 |
|---|---|---|
| [routes_chat.py](/Users/liuyize/NpaLangG/ai_hunter/app/api/routes_chat.py) | `POST /chat/invoke` | 主对话入口（JSON / SSE 流式；Phase 2.5.4 可灰度启用只读节点、专用图、领域 Agent 和建案/上传/任务确定性写命令；低置信或缺槽位请求先澄清） |
| | `POST /chat/upload-files`、`GET/DELETE /chat/threads*` | 会话内上传（案件主数据校验债务人）、线程 / 消息 / 轮次查询 |
| [routes_files.py](/Users/liuyize/NpaLangG/ai_hunter/app/api/routes_files.py) | `POST /files/upload-and-ingest` | 操作员上传卷宗并触发摄入；必须先建案，不从材料猜测债务人 |
| | `GET /files/health`、`/files/page-anchors` 见 graph | 健康检查、批次 / 材料事件 / 演进 / 未决项查询、批次重试 |
| [routes_graph.py](/Users/liuyize/NpaLangG/ai_hunter/app/api/routes_graph.py) | `POST /evidence/resolve` | 报告角标 → 证据抽屉 + 页图高亮 |
| | `POST /graph/relation-evidence`、`/graph/subgraph`、`/graph/demo-case-trace/validate` | 关系证据链、实体子图、标杆案件发布前验收 |
| | `GET /graph/cases/{id}/entities`、`/files/page-anchors` | 列案件实体、单页 bbox |
| [routes_progress.py](/Users/liuyize/NpaLangG/ai_hunter/app/api/routes_progress.py) | `GET/PUT /cases/{id}/progress` | 回款闭环进度看板聚合 / 更新 |
| | `POST/GET /cases/{id}/recovery`、`POST .../{rid}/confirm`、`POST/GET .../forecast` | 实收录入 / 列表 / 确认待确认收款、预期回款写读 |
| [routes_review.py](/Users/liuyize/NpaLangG/ai_hunter/app/api/routes_review.py) | `POST /cases/{id}/review` | AI 回款复盘对账（额外返回结构化三视角指标） |
| [routes_corrections.py](/Users/liuyize/NpaLangG/ai_hunter/app/api/routes_corrections.py) | `GET/POST /cases/{id}/corrections`、`POST .../{cid}/revoke` | 权威文字订正与追溯（列/录/撤销；每次审计自动应用） |
| [routes_deadline.py](/Users/liuyize/NpaLangG/ai_hunter/app/api/routes_deadline.py) | `GET /cases/{id}/deadline-board` | 司法时效看板（红黄绿四级 + 倒计时，确定性重算，阈值 env 可配） |
| [routes_users.py](/Users/liuyize/NpaLangG/ai_hunter/app/api/routes_users.py) | `GET /me`、`GET /tag-catalog`、`PUT /users/{id}(/tags)` | 身份/权限自省 + 人员标签管理（权限网关 Tier 3） |

> 报告角标联调、证据抽屉、实体子图等前端串联细节见 [docs/integration/前端调用手册-追溯与知识图谱.md](/Users/liuyize/NpaLangG/docs/integration/前端调用手册-追溯与知识图谱.md)。

## API 调用示例

前端联调前先确认跨域：`CORS_ALLOW_ORIGINS=*`（本地）或固定前端地址；需要带 cookie 时再开 `CORS_ALLOW_CREDENTIALS=true`。

### 1. 健康检查

```bash
curl -sS http://127.0.0.1:8081/files/health
# {"status":"ok"}
```

### 2. 触发完整审计

```bash
curl -sS -X POST http://127.0.0.1:8081/chat/invoke \
  -H 'Content-Type: application/json' \
  -d '{
    "thread_id": "demo-116",
    "query": "案件116出具完整审计报告",
    "current_case_id": 116,
    "uploaded_files": []
  }'
```

返回字段重点：

- `final_report` / `final_report_ref`：最终报告全文与稳定引用（点报告角标时需带上 ref）
- `trace_items` / `citation_coverage`：断言证据摘要、角标覆盖率与缺失项
- `intent`：本次路由结果
- `route_decision`：注册表约束的业务线、capability、置信度、来源和澄清状态；切换前后响应契约不变，内部执行结果和 shadow 不进入响应
- `parse_summary` / `memory_context`：文件解析摘要、脱水短期记忆

路由边界：`evidence.resolve` 只返回当前案件上传卷宗中的 claim、原文、页码和高亮锚点；`caselaw.search` 使用 CPWS/Qdrant 检索外部相似裁判案例，结果仅供参考，与当前业务案件不存在绑定关系。

### 2.1 报告角标联调

完整审计返回后，接通「角标 → 证据抽屉 → 页图高亮」：

1. `POST /chat/invoke` 拿 `final_report` 与 `final_report_ref`
2. 正文里识别 `[1]`、`[2]` 角标
3. 用户点击时调 `POST /evidence/resolve`，用返回的 `primary_evidence + primary_page` 渲染首屏
4. 切换同 claim 其他证据页时按需调 `GET /files/page-anchors`

```bash
curl -sS -X POST http://127.0.0.1:8081/evidence/resolve \
  -H 'Content-Type: application/json' \
  -d '{"case_id": 116, "report_ref": "final_report:...", "citation_id": "1"}'
```

返回含 `claim_id` / `claim_text` / `evidences[]` / `primary_evidence` / `primary_page`（`page_image_ref` + `bbox_list` + `anchors`）。`evidences[].entity_id` 可直接传给 `/graph/subgraph` 跳实体图谱。

### 2.2 标杆案件发布前验收

```bash
curl -sS -X POST http://127.0.0.1:8081/graph/demo-case-trace/validate \
  -H 'Content-Type: application/json' \
  -d '{"case_id": 116, "report_ref": "final_report:..."}'
```

逐角标检查 `citation_id → claim_id`、claim 是否有证据、主证据是否带页号/bbox/页图、是否能回到 page anchors；返回 `ready` / `checks` / `issues`。

### 3. 上传文件并触发摄入

按文件类型自动分流：`txt/csv/md` 直读文本；`pdf/doc/docx/xls*` 走文档 OCR；图片走图片 OCR。

```bash
curl -sS -X POST http://127.0.0.1:8081/files/upload-and-ingest \
  -F current_case_id=116 \
  -F current_debtor_id=76 \
  -F doc_category=bankruptcy_material \
  -F "files=@卷宗资料.pdf;type=application/pdf"
```

上传入口先按 `debtor_id` 精确匹配案件画像；未传 ID 时只允许案件存在唯一债务人。
`current_debtor_name` 仅用于一致性校验，冲突返回 409；资产购买方等 `case_party` 角色不会被当成债务人。
接口返回 `202` 及 `upload_batch_id/material_event_id`，OCR、parse-document 和图谱摄入在后台执行。
`upload_batch_id` 是真实幂等键：相同案件/债务人/类别/文件集合重放直接返回已有批次状态，不再进入 MinIO/OCR/KG；同 ID 绑定不同上下文或文件集合返回 `409`。批次只在 KG 阶段完成后标记 `completed`，`/retry` 仅允许失败批次调用。

### 4. 触发下钻追问

```bash
curl -sS -X POST http://127.0.0.1:8081/chat/invoke \
  -H 'Content-Type: application/json' \
  -d '{
    "thread_id": "demo-drilldown-116",
    "query": "案件116的白手套风险详细说说",
    "current_case_id": 116,
    "uploaded_files": []
  }'
```

进入 `drilldown_agent_graph`，由工具型 agent 自主决定调用案件画像 / 白手套分析 / 文书检索 / 任务工具等。

### 5. 触发修正重审

```bash
curl -sS -X POST http://127.0.0.1:8081/chat/invoke \
  -H 'Content-Type: application/json' \
  -d '{
    "thread_id": "demo-reaudit-116",
    "query": "水西南路房产估值不对，按800万重审",
    "current_case_id": 116,
    "uploaded_files": []
  }'
```

进入 `classify_intent → extract_correction → full_audit_graph`：先把口头修正抽成修正台账，再基于原始数据重跑。

### 6. 触发 AI 回款复盘

两种等价方式。① 对话（带"复盘 / 对账 / 回款复盘"关键词 → `intent=review`）：

```bash
curl -sS -X POST http://127.0.0.1:8081/chat/invoke \
  -H 'Content-Type: application/json' \
  -d '{"thread_id":"demo-review-116","query":"对案件116做回款复盘对账","current_case_id":116}'
```

② 专用接口（额外返回结构化三视角对账指标，可直接喂看板 / 图表）：

```bash
curl -sS -X POST http://127.0.0.1:8081/cases/116/review -H 'Content-Type: application/json' -d '{}'
```

返回字段重点：

- `final_report`：复盘报告全文（复用报告持久化链路，落 `conversation_messages`，历史可取回，按 `intent=review` 区分）
- `review_metrics.overall`：总量对账（预期 / 实收 / 达成率 / 差异，金额带 `*_万元` 展示串）
- `review_metrics.timeline`：时点对账（截至今日应收 vs 已收 / 时点缺口 / 各预期分档状态）
- `review_metrics.by_disposal_path`：实收按处置路径分组（金额 / 占比）

复盘**只计已确认收款**，待确认（pending）不计入。

### 7. 携带文件触发 ingest

`uploaded_files` 可直接挂到 `/chat/invoke`，图自动判断是否进入 `ingest_graph`：

```bash
curl -sS -X POST http://127.0.0.1:8081/chat/invoke \
  -H 'Content-Type: application/json' \
  -d '{
    "thread_id": "demo-ingest-001",
    "query": "解析并入库这批材料",
    "current_case_id": 116,
    "uploaded_files": [
      {"name": "抵押合同.pdf", "url": "https://example.com/mortgage.pdf", "content_type": "application/pdf"}
    ]
  }'
```

单个文件对象支持 `name` / `url` / `content_type`，可选 `type` / `extension` / `content`。

### 8. 回款闭环进度看板

```bash
curl -sS http://127.0.0.1:8081/cases/116/progress       # 看板聚合（阶段/风险/预期·实际/回收率/提醒）
curl -sS -X POST http://127.0.0.1:8081/cases/116/recovery \
  -H 'Content-Type: application/json' \
  -d '{"amount": 8000000, "recovered_at": "2026-05-20", "disposal_path": "清算拍卖"}'
```

看板金额返回元原值 + `*_wan` 万元展示串。自动抽取的实收为 `status=pending`，需 `POST /cases/{id}/recovery/{rid}/confirm` 确认后才计入实收总额。提醒阈值由 `RECOVERY_OVERDUE_DAYS` / `PROFIT_DISTRIBUTION_THRESHOLD_PCT` 配置。

## 运行测试

```bash
pytest -q
```

当前基线：`389 passed, 15 warnings`（2026-07-29，覆盖 Phase 2.5.4 确定性写命令、身份/租户门禁、上传批次幂等、KG 证据引用门禁、建案会话回绑、JSON/SSE 幂等缓存路由审计与既有完整回归；warnings 均为既有 LangGraph 弃用提示）。

- `pyproject.toml` 钉了 `testpaths = ["tests"]`，**只有** `tests/` 会被收集。
- 仓库根目录与 `scripts/` 下的 `test_*.py` 是打活服务的 HTTP 冒烟脚本，**不要用 pytest 跑**。
- 很多测试在缺远程依赖时会优雅回退到占位输出（有意为之，保证本地稳定）。

直接驱动主图（不走 HTTP）：

> 以下完整审计会写入报告引用、`recovery_forecast`、`case_progress`;`ENABLE_TASK_AUTOCREATE=true` 时还会调用任务 API。执行前必须确认目标环境并取得数据库和业务 API 写入授权。

```bash
python3 - <<'PY'
from ai_hunter.app.graph.context_loader import resolve_final_report
from ai_hunter.app.graph.main import build_audit_orchestrator_graph
g = build_audit_orchestrator_graph()
res = g.invoke(
    {"thread_id": "demo-116", "query": "案件116出具完整审计报告", "current_case_id": 116},
    config={"configurable": {"thread_id": "demo-116"}},
)
print(resolve_final_report(res)[:2000])
PY
```

## 运维清理

`heavy_payload_store` 支持统计与安全清理，建议先 dry-run 再执行：

```bash
python3 -m ai_hunter.app.scripts.heavy_payload_maintenance stats
python3 -m ai_hunter.app.scripts.heavy_payload_maintenance prune --payload-type full_context --older-than-seconds 86400 --limit 100
python3 -m ai_hunter.app.scripts.heavy_payload_maintenance prune --execute --payload-type full_context --older-than-seconds 86400 --limit 100
```

## 工具能力

下钻 Agent 已注册 18 个工具，注册表见 [ai_hunter/app/tools/registry.py](/Users/liuyize/NpaLangG/ai_hunter/app/tools/registry.py)（`ALL_DRILLDOWN_TOOLS`）。新工具必须在此注册才能被 agent 发现：

- 文档类目：文书类目目录、案件卷宗类目状态、卷宗类目校验
- 案件 / 企业：案件画像、新建案件、结构化入库、企业查询
- 检索：法律文书、裁判文书混合检索
- 审计分析：白手套分析、行为扫描、估值挤压、差额校验、期限扫描、资金流分析
- 任务 / 文档：批量建任务、任务管理、文档解析（OCR）

## Prompt 位置

提示词集中在 [ai_hunter/app/prompts/](/Users/liuyize/NpaLangG/ai_hunter/app/prompts/)，改提示改这里别内联：

- 八段式审计报告：`report_common_prefix.txt` + `report_s1.txt` … `report_s8.txt`（各段一个专家 persona）
- 回款复盘报告：`review_s1.txt`（对账总览）/ `review_s2.txt`（差异归因）/ `review_s3.txt`（经验与规则建议）
- 意图路由：`router.txt`；下钻 agent：`drilldown_agent.txt`
- 知识图谱：`extract_entities_relations.txt` / `reconcile_graph_delta.txt`

> 报告金额统一口径：**万元 / 4 位小数 / 无千分位**（`metrics_engine.format_amount` + reconcile 去千分位）。

## 数据库表（DDL 在 sql/）

- 会话与大对象：`checkpoints*`（LangGraph）、`conversation_messages`、`heavy_payload_store`
- 卷宗与摄入：`source_file` / `source_page` / `source_chunk` / `source_upload_batch` / `material_event` / `doc_category_*`
- 知识图谱：`kg_entity` / `kg_relation` / `kg_claim` / `kg_evidence_link` / `kg_extraction_run` / `kg_reconciliation_ledger` / `kg_unresolved_item` / `report_citation_map`
- 回款闭环：`case_progress` / `recovery_record` / `recovery_forecast`
- 权威订正：`case_correction`（文字订正写库、加载期应用、可追溯）
- 权限网关：`app_user` / `app_user_tag` / `app_tag_catalog` / `app_role_permission`（用户投影 + 五维人员标签 + 角色→权限映射；认证走用户中心 JWT 不落本地）
- 拿包前业务线：`packages` / `pricing_params` / `screening_*`

## 设计约束

- 长报告不进入 `messages`，报告正文与对话 memory 物理隔离
- 修正请求进入 `correction_records` / `user_corrections`，重审基于原始数据 + 修正台账重跑
- 数值口径由确定性引擎拥有，报告 / 复盘的金额一律取引擎算好的 `*_万元` 字段，LLM 不重算
- 复盘只读对账：不改 `case_progress`、不抽任务、不种子化预期，只计 confirmed 实收
- 任务提取优先用结构化输出，正则仅兜底
- 报告正文禁止出现内部字段名 / 变量名 / snake_case 标识符（公共前缀硬规则）
- 案件参与方统一写入 `case_party`；债务人专项画像仍以 `debtors` 为权威，卷宗材料不得自动覆盖主数据

## 已知注意点

- MiniMax 中国区走 `https://api.minimaxi.com/v1`；其结构化节点不建议硬设 `temperature=0`（代码已兼容，会抬到 `0.01`）
- Kimi 当前默认模型 `Kimi-k2.6`，以 `settings.py` 为准
- `query_wenshu_knowledge` 不走 HTTP，而是直连 `cpwsdata` 库做关键词 + `bge-m3` 混合检索
- 八段报告并行生成有 529 过载风险，已用按 provider 的有界并发信号量 + 退避重试兜底
- 测试用例允许在无远程依赖时回退到占位输出，以保证本地开发稳定

## 文档

- [AGENTS.md](/Users/liuyize/NpaLangG/AGENTS.md) / [CLAUDE.md](/Users/liuyize/NpaLangG/CLAUDE.md)：面向 AI 协作者的命令、目录、约定与"动手前先看"
- [docs/integration/前端调用手册-追溯与知识图谱.md](/Users/liuyize/NpaLangG/docs/integration/前端调用手册-追溯与知识图谱.md)：前端联调手册
- [docs/design/13-案件参与方角色模型与债务人解析治理.md](/Users/liuyize/NpaLangG/docs/design/13-案件参与方角色模型与债务人解析治理.md)：案件角色模型、债务人解析优先级、迁移与回滚
- [docs/](/Users/liuyize/NpaLangG/docs/)：文档索引、路线图、部署指南、各特性设计稿（数值引擎 / 八段报告 / 回款闭环与复盘等）

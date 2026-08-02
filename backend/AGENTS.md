# AGENTS.md

AI Hunter 统一后端 —— 基于 Python 3.11+ FastAPI + LangGraph 的单体服务,
面向不良资产(NPA)案件的完整审计 / 下钻追问 / 任务督办 / 修正重审。
会话状态由 `langgraph-checkpoint-postgres` 持久化;大对象走 3 层存储(进程 → Redis → Postgres)。

## 目录结构

- `ai_hunter/app/main.py` —— FastAPI 应用工厂,文件底部 `app = create_app()`。
- `ai_hunter/domain_engine/` —— 原 8080 的案件、材料、审计、任务与领域数据库能力；由 `integration.py` 挂入统一应用，原 `/api/*` 路径保持兼容。
- `ai_hunter/app/graph/main.py:24` —— `build_audit_orchestrator_graph()` 是顶层图的唯一来源,节点顺序写死在这里。
- `ai_hunter/app/graph/nodes/` —— 每个节点一个文件;`state.py` 定义 `AuditGraphState`。
- `ai_hunter/app/subgraphs/` —— 摄入 / 八段审计 / 三段复盘 / 下钻 Agent / 知识图谱子图,以及 Phase 2.5.4 的业务线注册子图、专用执行器和确定性写命令执行器。
- `ai_hunter/app/tools/registry.py` —— 注册的 18 个工具(案件 / 审计 / 任务 / 检索 / 文档分类)。
- `ai_hunter/app/prompts/*.txt` —— 路由、八段报告(`report_common_prefix` + `report_s1`...`report_s8`)、三段复盘(`review_s1`...`review_s3`)、通用/领域 Agent、图谱抽取与对账提示词。改提示词改这里,别内联。
- `tests/` —— pytest 套件(且**只有**这个目录会被 pytest 收集,见下文)。
- `scripts/` —— **不是** pytest 测试。是打 `localhost:8081` 的 HTTP 冒烟 / 回归脚本(`test_mixed_*.py` / `test_3_turn_*.py` / `test_idempotency_and_ordering.py` / `smoke_operator_upload_flow.py` / `test_unified_message_layer.py` 等)。
- `sql/` —— DDL。首次启动前手动跑 `langgraph_checkpointer.sql`,除非设了 `LANGGRAPH_CHECKPOINTER_AUTO_SETUP=true`。
- `docs/deployment/DEPLOY_UBUNTU_10.2.md` —— Ubuntu 10.0.10.2 部署指南(systemd 单元、env 布局)。

## 常用命令

```bash
# 安装(editable + dev 依赖)
python3 -m pip install -e '.[dev]'

# 启动 API(默认端口 8081,与 README/.env 一致)
python -m ai_hunter

# 跑维护中的测试套件
pytest -q

# 不走 HTTP,直接驱动主图。完整审计会写报告引用、预期回款/进度;
# ENABLE_TASK_AUTOCREATE=true 时还会调用任务 API 创建任务,
# 必须先取得数据库和业务 API 写入授权。
python3 - <<'PY'
from ai_hunter.app.graph.context_loader import resolve_final_report
from ai_hunter.app.graph.main import build_audit_orchestrator_graph
g = build_audit_orchestrator_graph()
res = g.invoke(
    {"thread_id":"t1","query":"案件116出具完整审计报告","current_case_id":116},
    config={"configurable":{"thread_id":"t1"}},
)
print(resolve_final_report(res)[:1500])
PY

# 大对象存储:统计 / 预演清理 / 真实清理
python3 -m ai_hunter.app.scripts.heavy_payload_maintenance stats
python3 -m ai_hunter.app.scripts.heavy_payload_maintenance prune --payload-type full_context --older-than-seconds 86400 --limit 100
# --execute 会删除数据,执行前必须取得明确授权
python3 -m ai_hunter.app.scripts.heavy_payload_maintenance prune --execute --payload-type full_context --older-than-seconds 86400 --limit 100
```

仓库**没有** Makefile / tox / pre-commit / CI(`.github/` 不存在),也没配 lint / format / typecheck —— 不要自己造命令。

## 测试约定

- `pyproject.toml` 钉了 `testpaths = ["tests"]`,且 `tests/` 是**唯一**维护中的套件(当前基线 `413 passed`,2026-08-02)。
- 仓库根目录松散的 `test_*.py` 会卡在活服务上,`.gitignore` 已经忽略了 `/test_*.py`。**别把它们挪进 `tests/`**。
- `scripts/test_*.py` 是 HTTP 冒烟脚本,不要用 pytest 跑,需要时手动对活服务跑。
- 很多测试在缺远程依赖时会优雅回退到占位输出(README "已知注意点" 里有说明,这是有意为之)。

## 配置

- 真实配置在 `.env`(**不**是 `.env.example`)。`.env` 已被 gitignore。从 `.env.example` 复制,补齐各厂商 key。
- `LLM_DEFAULT_PROVIDER` 一键切全局主模型;按角色覆盖用 `LLM_PROVIDER_{ROUTER,REPORT_A,REPORT_B,AGENT}`。支持的 provider:`minimax` / `kimi` / `faker` / `openai`。解析逻辑见 `settings.py:resolve_provider` / `get_llm_config`。
- `LANGGRAPH_CHECKPOINTER=postgres|memory`。`postgres` 走的是基于 `psycopg_pool.ConnectionPool` 的**同步** `PostgresSaver`(见 `graph/checkpointer.py`)。Postgres 不可达时会回退到 `MemorySaver` —— **测试通过不代表持久化生效**。
- SSE 流式(`/chat/invoke` `stream=true`)用一份**单独编译的异步图**,带 `AsyncPostgresSaver`;同步 / 异步 checkpointer 不能互相替换。
- `POSTGRES_DSN` 用 SQLAlchemy 形式;`settings.postgres_checkpointer_dsn` 会去掉 `+psycopg` 后缀再给 LangGraph。
- `ROUTER_EXECUTION_MODE=legacy|business_line`,默认 `legacy`;`business_line` 当前灰度启用七个确定性只读节点、三个专用图、两个领域 Agent,以及 `case.create / material.upload / task.write` 三个确定性写命令节点。三条写能力的隔离真实写入冒烟已验收,但生产部署前检查、灰度切流和观察窗口尚未执行,生产仍保持 `legacy`。
- **部署地址 ≠ 代码默认值**:Settings 中 Postgres `127.0.0.1`、Redis 为空、MinIO 关闭且端点为空,仅用于本地开发兜底,不代表当前部署拓扑。
- AI 编排和领域 API 统一监听 `APP_PORT`（默认 8081）；内部工具地址使用 `UNIFIED_API_BASE_URL`。旧分服务 URL 变量仅用于回滚兼容，正常部署保持为空。数据库、Redis、MinIO 等真实地址必须以部署环境 `.env` 为准。
- PDF 主动分段实现已完成但默认 `OCR_PDF_SPLIT_ENABLED=false`;晨光 61 页和正华 19 页 PDF 已通过整卷 OCR 隔离真实 HTTP 验收。主动分段分支仍未做真实 HTTP 验收,上线前需在隔离进程显式开启后重跑真实 PDF。

## 架构要点(常踩的坑)

- **图流转**(`graph/main.py`):`normalize_input → hydrate_memory_context → resolve_case_context → hydrate_case_graph_context → (ingest_graph?) → classify_intent → execution_route_edge`。`legacy` 进入完整审计 / 重审 / 复盘 / 下钻 / 澄清分支;`business_line` 对已迁移能力进入 `operator` / `audit_analysis` / `supervision` / `common` 子图,其余能力保留 legacy 回滚路径。
- **案件安全门禁**:`audit.full` / `audit.reaudit` / `recovery.review` 都要求正整数 `case_id`;缺失或 `case_id<=0` 时进入 `clarify`,不得执行专用图。
- **重审 ≠ 改旧报告**:修正请求走 `extract_correction` → 落到 `correction_records` / `user_corrections`,然后让 `full_audit_graph` 用原始数据 + 修正台账**重跑**。不要直接修补报告文本。
- **长报告与 `messages` 物理隔离**(有意为之)。`memory.py` 节点会脱水报告输出,详见 `LANGGRAPH_MEMORY_*` 配置。
- **Ingest 是条件分支**,在 `hydrate_case_graph_context` 之后看 `should_ingest_files`;给 `/chat/invoke` 传 `uploaded_files` 会自动触发。
- **下钻 Agent 共 18 个工具**(文档类目 3 件 / 案件画像 / 文书检索 / 白手套分析 / 任务操作 / OCR / 资金流扫描 / 估值挤压 等)。工具在 `app/tools/` 注册，确定性领域实现位于 `domain_engine/`；新工具**必须**进入 `tools/registry.py` 才能被发现。
- **引用链**:报告角标 `[1]`、`[2]` → `POST /evidence/resolve` → 渲染 `page_image_ref` + `bbox_list`;`POST /graph/demo-case-trace/validate` 是标杆案件发布前的卡口校验。
- **`query_wenshu_knowledge` 直连 `cpwsdata` 数据库**(不是 HTTP 服务),做关键词 + `bge-m3` / embedding 混合检索。

## 厂商坑

- **MiniMax**(`minimaxi.com`):`graph/llm.py:24` 会注入 `extra_body={"reasoning_split": True}`;结构化输出节点**不要硬写** `temperature=0` —— `_normalize_temperature` 会把它抬到 `0.01`。router 在 MiniMax 上也别写死 `temperature=0`。
- **Kimi** 的当前默认模型是 `kimi/Kimi-k2.6`;README、`.env.example` 和 `settings.py` 必须保持一致。
- **Faker** 是 vLLM 风格路径(`vllm/<vendor>/<model>`),用于本地 / CI 模型替换。

## 协作审计与 PR Review 约定

- 对话中的修复过程必须带 **PR review / change review** 视角:先说明风险点、判断依据、改动范围,再说明修复。
- 每次编辑写入后,必须立即给出 **Review checkpoint**:列出已编辑文件,贴出关键真实 diff hunk(带增删行标记),并用 1-3 句解释该 diff 为什么解决问题。
- 最终回复必须包含可审计信息:改了哪些文件、关键 diff/行为变化、验证命令与结果、未验证项/剩余风险。不能只给“已修复/测试通过”的结论。
- 用户需要看到修复过程中的 review 审计;涉及关键逻辑时,必须引用具体文件位置或贴出对应 diff 片段。
- 如果变更影响线上行为(模型 provider、SSE、持久化、任务创建、权限、DDL),必须说明回滚点和是否已重启服务/是否已真实冒烟。
- 若工作区存在非本次修改的本地改动,必须在最终回复中区分“本次改动”和“既有/用户改动”,避免把无关 diff 归因到本次修复。

## 改之前先看

- 改提示词?改对应的 `prompts/*.txt`;八段审计需同步检查 `report_common_prefix.txt` 与受影响的 `report_s1.txt`...`report_s8.txt`,复盘需检查 `review_s1.txt`...`review_s3.txt`。`report_part_a/b.txt` 仅保留旧路径兼容。
- 加节点?在 `graph/main.py` 接线,在 `state.py` 声明字段,并按 `tests/test_main_graph.py` 的风格加测试。
- 加工具?在 `tools/registry.py` 注册;下钻 agent 只认这个注册表。
- 改库表?DDL 放 `sql/`,沿用现有命名风格,顺便在 `sql/` 里的评审 / 备忘文件里记录变更。
- 手动 full-audit 冒烟使用 `case_id=116`。该路径会写报告引用、`recovery_forecast`、`case_progress`;`ENABLE_TASK_AUTOCREATE=true` 时还会调用任务 API。执行前必须获得数据库/业务 API 写入授权,不能用 `case_id=0` 绕过门禁。

# AI猎手 审计系统 -> LangGraph 迁移方案

> 历史迁移记录：本文保留用于追溯早期双服务设计；当前运行架构以[统一后端架构](统一后端架构.md)为准，领域 API 已合入 8081 单一服务。

## 1. 先说结论

这份 Dify 工作流本质上不是一个单 Agent，而是一个混合编排系统：

1. 会话态持久化：`current_case_id`、`current_debtor_id`、`current_debtor_name`
2. 文件摄入链路：文档/图片过滤、OCR、文本聚合、结构化入库
3. 路由分流：完整审计 vs 追问下钻/任务中枢 vs 修正重审
4. 报告生成链路：全景数据获取 -> 前4段 LLM -> 后4段 LLM -> 任务抽取 -> 任务入库
5. 深挖 Agent：14 个工具的 function calling
6. 修正台账：用户指出事实错误后，以 `user_corrections` 驱动重审

迁到 LangGraph 时，不建议照着 Dify 节点一比一搬运。正确做法是改造成：

- 一个主图 `audit_orchestrator_graph`
- 两个子图 `ingest_graph`、`full_audit_graph`
- 一个工具型 Agent 图 `drilldown_agent_graph`
- 一层独立的 service/tool adapter，负责 OCR、案件上下文、任务、审计引擎、企查查、文书检索
- 一层持久化 checkpointer/store，替代 Dify conversation variables

## 2. 从 Dify 里读出来的核心能力

### 2.1 会话变量

源文件里定义了 3 个长期状态：

- `current_case_id` [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:35>)
- `current_debtor_id` [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:27>)
- `current_debtor_name` [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:19>)

LangGraph 里这三个字段必须进入持久化 state，而不是只存在消息上下文。

### 2.2 文件摄入链

文件分成四类：

- `txt` 过滤 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:781>)
- `md` 过滤 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:741>)
- `document` 过滤 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:643>)
- `image` 过滤 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:703>)

PDF 和图片都走 OCR：

- PDF OCR 迭代节点 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:1216>)
- OCR 服务包装代码 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:1257>)
- 图片 OCR 迭代节点 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:2070>)

四类文本最后聚合成统一 `aggregated_text`，再提交给 `parse-document`：

- 文本聚合模板 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:1363>)
- 入库请求体拼装 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:1043>)
- 文档解析入库接口 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:891>)

### 2.3 路由分流

当前 Dify 用 question-classifier 把请求分成两类：

- `全面审计流水线` [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:1907>)
- `追问下钻与任务中枢` [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:1917>)

迁到 LangGraph 后建议扩成三类：

- `full_audit`
- `drilldown`
- `re_audit`

其中 `re_audit` 用于“用户指出底层事实、估值、状态有误，并要求重新出报告”的场景。

### 2.4 完整审计链

完整审计链的核心顺序是：

1. 获取案件全景数据 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:1968>)
2. LLM 生成前 4 段 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:2186>)
3. LLM 生成后 4 段和下钻索引 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:2258>)
4. 清洗输出并抽取 SOP 任务 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:2327>)
5. 批量写入任务 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:2009>)

### 2.5 深挖 Agent

深挖 Agent 节点 `索引深度分析` 是 function calling 模式，挂了 14 个工具：

- 案件画像、案例检索、白手套分析、创建案件、结构化字段入库、批量创建任务
- 企查查穿透、任务管理、文档智能解析入库
- 四大审计引擎、资金拓扑、裁判文书知识库

入口定义在 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:1516>)，工具清单定义从 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:1556>) 开始。

## 3. LangGraph 推荐架构

### 3.1 目录结构

```text
ai_hunter/
  app/
    api/
      routes_chat.py
      routes_files.py
    graph/
      main.py
      state.py
      routers.py
      nodes/
        normalize_input.py
        resolve_case.py
        ingest_files.py
        route_intent.py
        fetch_full_context.py
        generate_report_a.py
        generate_report_b.py
        reconcile_report.py
        create_tasks.py
        run_drilldown_agent.py
    subgraphs/
      ingest_graph.py
      full_audit_graph.py
      drilldown_agent_graph.py
    services/
      ocr_service.py
      audit_api.py
      task_api.py
      case_api.py
      enterprise_api.py
      knowledge_api.py
      retrieval_api.py
    tools/
      audit_tools.py
      task_tools.py
      case_tools.py
    prompts/
      router.txt
      report_part_a.txt
      report_part_b.txt
      drilldown_agent.txt
    settings.py
  tests/
    test_router.py
    test_ingest_graph.py
    test_full_audit_graph.py
    test_task_extraction.py
  .env.example
```

### 3.2 主图结构

```text
START
  -> normalize_input
  -> resolve_case_context
  -> maybe_ingest_files
  -> route_intent

route_intent == full_audit
  -> full_audit_graph
  -> maybe_create_tasks
  -> finalize_answer

route_intent == drilldown
  -> drilldown_agent_graph
  -> finalize_answer

END
```

### 3.3 为什么这样拆

- `resolve_case_context` 统一做 case_id 继承与解析，替代 Dify 里两段重复正则。
- `ingest_graph` 专职处理上传材料，避免主图塞满 OCR 和文件类型判断。
- `full_audit_graph` 专职处理重型报告生成，便于后续单独加缓存和异步执行。
- `drilldown_agent_graph` 独立承载 function calling，对话追问和任务管理都归它。
- service/tool 层把 HTTP 调用与 graph 解耦，后面换后端接口或加鉴权不会碰 graph。

## 4. State 设计

建议使用 `TypedDict` 或 `pydantic` 明确定义状态。

```python
from typing import Any, Literal, NotRequired
from typing_extensions import TypedDict

class AuditGraphState(TypedDict, total=False):
    thread_id: str
    user_id: str
    query: str
    messages: list[Any]

    current_case_id: int
    current_debtor_id: int
    current_debtor_name: str

    uploaded_files: list[dict[str, Any]]
    txt_contents: list[str]
    md_contents: list[str]
    pdf_ocr_contents: list[str]
    image_ocr_contents: list[str]
    aggregated_text: str

    parse_summary: str
    categories_found: list[str]
    records_inserted: int

    intent: Literal["full_audit", "drilldown"]
    full_context_json: str
    full_context_data: dict[str, Any]

    report_part_a: str
    report_part_b: str
    final_report: str

    extracted_tasks: list[dict[str, Any]]
    task_create_result: dict[str, Any]

    agent_output: str
    errors: list[str]
```

### 4.1 长期状态和临时状态要分开

长期状态：

- `current_case_id`
- `current_debtor_id`
- `current_debtor_name`
- `messages`

临时状态：

- OCR 中间结果
- `aggregated_text`
- `full_context_json`
- `report_part_a/report_part_b`
- `extracted_tasks`

长期状态建议用 LangGraph checkpointer 持久化，临时状态跟着单次 run 走。

## 5. 节点设计

### 5.1 `normalize_input`

职责：

- 接收 query 和 files
- 标准化文件对象
- 把聊天输入和上传输入统一成 graph state

### 5.2 `resolve_case_context`

职责：

- 提取 query 中的 `case_id`
- 若未命中则回退到历史 `current_case_id`
- 若存在文件但没有 case_id，则允许“补充材料”沿用当前案件

这里就是把 Dify 里的两段正则节点合并：

- `获取案件审计信息` [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:926>)
- `获取案件信息` [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:1455>)

### 5.3 `ingest_graph`

内部节点建议：

```text
filter_files
  -> extract_plain_text
  -> ocr_pdf_files
  -> ocr_image_files
  -> merge_texts
  -> infer_debtor_name
  -> parse_document_and_ingest
  -> update_case_context
  -> summarize_ingest
```

关键点：

- OCR 要支持并发 map，但要限制并发数
- `infer_debtor_name` 是一个弱推断节点，不能污染强主数据
- `parse_document_and_ingest` 返回的新 `case_id/debtor_id/debtor_name` 才是权威值

### 5.4 `route_intent`

不要再用 Dify 黑盒 classifier 节点，建议自己写一个轻量 router：

1. 先规则判断
2. 规则不确定时再调小模型分类
3. 输出稳定枚举值 `full_audit` 或 `drilldown`

这样做有两个好处：

- 成本低
- 行为更可控，避免“查看任务”被错误打进完整审计

### 5.5 `full_audit_graph`

内部节点建议：

```text
fetch_full_context
  -> generate_report_part_a
  -> generate_report_part_b
  -> reconcile_report_and_extract_tasks
```

说明：

- `fetch_full_context` 对应 `/api/audit/get_full_context`
- 两个 LLM 节点继续拆开，保留你现有 prompt 资产
- `reconcile_report_and_extract_tasks` 同时做两件事：报告清洗、SOP 任务结构化抽取

### 5.6 `drilldown_agent_graph`

建议模式：

- LangGraph ReAct/Tool-calling Agent
- 只挂你真正想暴露的工具
- 输出只返回“增量洞察”

这里最重要的不是复刻 Dify Agent，而是把工具做成强类型函数：

```python
@tool
def get_whiteglove_analysis(case_id: int) -> dict: ...

@tool
def manage_tasks(
    action: str,
    case_id: int,
    task_id: int | None = None,
    assigned_to: str | None = None,
    new_status: str | None = None,
    completion_note: str | None = None,
) -> dict: ...
```

## 6. Service 边界

### 6.1 不要在 graph 节点里直写 HTTP

建议把这些接口统一下沉到 service：

- `OCRService`
- `AuditAPIClient`
- `TaskAPIClient`
- `CaseAPIClient`
- `EnterpriseAPIClient`
- `KnowledgeAPIClient`

### 6.2 最低限度接口拆分

```python
class AuditAPIClient:
    def parse_document(self, payload: dict) -> dict: ...
    def get_full_context(self, case_id: int) -> dict: ...
    def audit_delta_check(self, case_id: int) -> dict: ...
    def audit_valuation_squeeze(self, case_id: int) -> dict: ...
    def audit_deadline_scan(self, case_id: int) -> dict: ...
    def audit_behavioral_scan(self, case_id: int) -> dict: ...
```

## 7. Prompt 策略

现在的 Dify prompt 资产很重，别丢，直接迁成外部 prompt 文件。

建议拆成：

- `router.txt`
- `report_part_a.txt`
- `report_part_b.txt`
- `drilldown_agent.txt`

### 7.1 一个重要调整

现在后半段 prompt 把前半段 `reasoning_content` 一起喂进去了 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:2305>)。

迁到 LangGraph 后不建议继续传 chain-of-thought 原文。建议替换为：

- 前半段结构化摘要
- 或前半段正文
- 或受控的 `analysis_notes`

原因：

- 降低提示泄露风险
- 让模型输出更稳定
- 避免把推理痕迹写进业务链路

## 8. `.env` 设计

### 8.1 推荐环境变量

```dotenv
APP_ENV=dev
APP_HOST=0.0.0.0
APP_PORT=8081
LOG_LEVEL=INFO

OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL_ROUTER=gpt-4.1-mini
OPENAI_MODEL_REPORT_A=gpt-4.1
OPENAI_MODEL_REPORT_B=gpt-4.1
OPENAI_MODEL_AGENT=gpt-4.1
OPENAI_TEMPERATURE_ROUTER=0.1
OPENAI_TEMPERATURE_REPORT=0.7
OPENAI_TEMPERATURE_AGENT=0.3

LANGGRAPH_CHECKPOINTER=postgres
LANGGRAPH_THREAD_TTL_HOURS=168

POSTGRES_DSN=postgresql+psycopg://user:password@127.0.0.1:5432/ai_hunter
REDIS_URL=redis://127.0.0.1:6379/0

AUDIT_API_BASE_URL=http://10.0.10.2:8080
AUDIT_API_TIMEOUT_SECONDS=600
AUDIT_API_TOKEN=

OCR_BASE_URL=https://ocr.rhzy.ai
OCR_TIMEOUT_SECONDS=600
OCR_VERIFY_SSL=false
OCR_BACKEND=vlm-auto-engine
OCR_LANG_LIST=ch
OCR_TABLE_ENABLE_PDF=true
OCR_TABLE_ENABLE_IMAGE=false
OCR_AUTO_ROTATE_PDF=false
OCR_AUTO_ROTATE_IMAGE=true

TASK_API_BASE_URL=http://10.0.10.2:8080
CASE_API_BASE_URL=http://10.0.10.2:8080
KNOWLEDGE_API_BASE_URL=http://10.0.10.2:8080
ENTERPRISE_API_BASE_URL=http://10.0.10.2:8080

MAX_UPLOAD_FILES=20
MAX_UPLOAD_FILE_MB=500
MAX_IMAGE_FILE_MB=10
MAX_FILE_BATCH_COUNT=5
OCR_MAX_PARALLEL=5

ENABLE_TASK_AUTOCREATE=true
ENABLE_AGENT_MEMORY=true
ENABLE_REPORT_CACHE=true
ENABLE_REASONING_TRACE=false
```

### 8.2 为什么要这样拆

- 模型参数单独配置，方便按节点控成本
- `OCR_*` 和 `AUDIT_API_*` 拆开，避免后续 OCR 服务迁移时相互污染
- `ENABLE_TASK_AUTOCREATE=true` 时，完整审计/重审提取任务后自动调用任务 API 批量创建；`false` 时保留 `extracted_tasks`，但跳过外部任务写入
- `ENABLE_REASONING_TRACE=false` 明确禁止把推理内容写回业务输出

## 9. 配置类建议

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8081
    log_level: str = "INFO"

    openai_api_key: str
    openai_base_url: str | None = None
    openai_model_router: str = "gpt-4.1-mini"
    openai_model_report_a: str = "gpt-4.1"
    openai_model_report_b: str = "gpt-4.1"
    openai_model_agent: str = "gpt-4.1"

    postgres_dsn: str
    redis_url: str | None = None

    audit_api_base_url: str
    audit_api_timeout_seconds: int = 600
    audit_api_token: str | None = None

    ocr_base_url: str
    ocr_timeout_seconds: int = 600
    ocr_verify_ssl: bool = False
```

## 10. 第一阶段落地顺序

### Phase 0

- 暂不接 OCR、任务接口、真实案件接口
- 用 mock `full_context_json` 跑通 `full_audit_graph`
- 验证 `A -> B -> 结构化任务提取` 主干稳定可复现

### Phase 1

- 起 FastAPI + LangGraph 基础工程
- 落 `state.py`、`settings.py`
- 实现 `resolve_case_context`
- 实现 `ingest_graph`
- 打通 `parse_document`

### Phase 2

- 实现 `full_audit_graph`
- 把前后 8 段报告迁出 Dify prompt
- 结构化提取任务并落库

### Phase 3

- 实现 `drilldown_agent_graph`
- 工具注册、权限控制、超时和重试
- 接入 memory/checkpointer

### Phase 4

- 增加缓存、审计日志、回放能力
- 细化可观测性
- 做回归测试和线上灰度

## 11. 关键风险

### 11.1 不要继续把所有事塞进一个图

这份 Dify 工作流的问题不是功能不够，而是职责太杂。LangGraph 如果照搬，会得到一个更难维护的大图。

### 11.2 OCR 与入库必须幂等

文件上传重试、OCR 超时重跑、前端重复点击，都可能导致重复入库。要给 `parse_document` 一层幂等键。

### 11.3 任务提取不要只靠正则

当前 Dify 最后一步用正则从 LLM 文本里抠任务 [AI猎手 — 审计系统.yml](</Users/liuyize/NpaLangG/AI猎手 — 审计系统.yml:2343>)，能跑，但比较脆。

迁移时建议升级成：

- 优先让模型输出 JSON schema
- 正则解析只做兜底

### 11.4 `reasoning_content` 不要入业务面

这点上面提过一次，再强调一次。业务系统里保留正文、摘要、结构化字段就够了。

## 12. 最小可用版本定义

你们的 MVP 不需要一步到位复刻 Dify 全部能力。最小可用版本建议只包含：

1. 输入 `case_id` 生成完整 8 段报告
2. 上传 PDF/图片补充材料并入库
3. 支持“查看任务 / 标记完成 / 指派”
4. 支持“下钻 01 / 查一下某公司”

这样上线风险最低，且最接近现有真实使用路径。

## 13. 多轮对话与记忆治理正式方案

这一部分不是附属优化，而是 AI 猎手从“能跑”走向“工业级可控”的核心地基。系统必须明确区分：

- 会话记忆
- 业务状态
- 长期知识摘要

并且严格执行“报告正文、大 JSON、重工具返回不进入长期消息历史”的原则。

### 13.1 总原则

1. 报告正文不进入 `messages`
2. `full_context_json`、原始 OCR 长文本、工具全量 JSON 不进入长期消息历史
3. 多轮记忆依赖“短消息 + 摘要 + 当前案件态”，不是全量回放
4. 重审依赖“原始事实 + 修正台账”，不是修改旧报告文本
5. checkpointer 只保留轻量状态，重对象走引用外置

### 13.2 现状评估

#### 已采纳

- `messages` 与 `final_report/report_part_a/report_part_b` 已分离
- `persist_conversation_memory` 已采用轻量摘要回写
- `re_audit`、`user_corrections`、`correction_records` 已具备基础形态

#### 部分采纳或临时绕开

- 当前 `memory_context` 只是窗口内文本拼接，尚未升级为滚动摘要
- 当前未正式接入 `trim_messages`，但由于没有长期保存完整 ToolMessage 链，暂时绕开了 orphaned tool call 风险
- 当前 drilldown prompt 已注入案件上下文和 `report_part_b`，但修正台账优先级还未形成统一注入规范

#### 尚未正式采纳但必须补齐

- 工具输出防爆墙：统一脱水摘要
- 案件切换隔离：切换 `case_id` 时清空跨案污染状态
- checkpointer 大对象指针化：重 JSON 不直接长期快照
- 安全修剪：正式采用 `trim_messages`

### 13.3 三层记忆架构

#### 第一层：会话记忆（短期）

用途：

- 支撑“刚才那个矿权继续说”
- 支撑“上一个任务状态如何”
- 支撑 drilldown 的连续追问

数据形态：

- `messages`
- `memory_context`

约束：

- 只存轻量问答摘要
- 不存整份报告
- 不存大体量工具原始返回
- 不存完整 `full_context_json`

#### 第二层：业务状态记忆（中期）

用途：

- 持续跟踪案件上下文
- 持续跟踪债务人上下文
- 持续跟踪任务、修正、文件入库状态

数据形态：

- `current_case_id`
- `current_debtor_id`
- `current_debtor_name`
- `parse_summary`
- `task_create_result`
- `correction_records`
- `user_corrections`

说明：

这层属于 graph state，不属于聊天消息。

#### 第三层：长期知识摘要（长期）

用途：

- 保存案件长期人工修正口径
- 保存用户偏好的输出风格
- 保存某案件持续性的博弈点

数据形态：

- `memory_context` 的历史摘要部分
- 后续可扩展为独立 store/table

说明：

长期知识必须结构化或摘要化，不能把原始聊天记录无限保留。

### 13.4 ToolMessage 防爆正式方案

Gemini 指出的 ToolMessage 爆炸问题成立，而且在本系统里是高风险项。

#### 风险来源

以下工具最容易返回超大 JSON：

- `fetch_enterprise`
- `get_fund_flow`
- `get_legal_writ`
- `query_wenshu_knowledge`
- `parse_document`

如果原样进入 agent 的工具消息流，会造成：

- prompt token 暴涨
- 多轮追问迅速失控
- 响应速度下降
- 模型在大段原始 JSON 中失焦

#### 正式策略

所有 drilldown 工具统一采用“脱水摘要”策略，而不是原样回传全量载荷。

统一规则：

1. 只保留当前问题所需的关键字段
2. 结果过大时按 top-k 截断
3. 输出固定包含：
   - `summary`
   - `key_facts`
   - `truncated`
   - `next_hint`
4. 截断时明确提示 agent 需要更精确查询条件

建议返回结构：

```json
{
  "summary": "命中 17 条关联企业记录，已展示最关键的 5 条。",
  "key_facts": [],
  "truncated": true,
  "next_hint": "如需继续穿透，请指定公司名或层级。"
}
```

工程约束：

- 不允许工具函数直接 `json.dumps(全量原始返回)` 暴露给 agent
- 工具适配层必须先本地脱水，再交给 LangGraph agent
- 对 `raw_text`、`full_chain`、`documents`、`attachments` 等重字段做白名单裁剪

### 13.5 安全消息修剪正式方案

正式方案不能依赖手写 `messages[-N:]`。

#### 风险

如果未来多轮对话保留了更完整的 agent/tool 消息链，简单切片可能切断：

- 发起 tool call 的 `AIMessage`
- 与之配对的 `ToolMessage`

后续再次请求模型时可能直接报错。

#### 正式策略

采用 LangChain 原生 `trim_messages`：

1. 优先保留最近一轮完整工具调用对
2. 修剪前先判断消息类型边界
3. 老消息先压缩进 `memory_context`，再裁剪原始消息

### 13.6 滚动摘要正式方案

当前 `memory_context` 只是窗口内文本拼接。正式方案应升级为“窗口 + 摘要”双层结构。

#### 目标

- 最近几轮保留原始轻量语义
- 更早轮次压缩成摘要
- 让 token 成本稳定在常数级

#### 建议结构

```text
memory_context =
  [案件状态摘要]
  [历史对话摘要]
  [最近 N 轮原始轻量问答]
```

摘要必须优先保留：

- 当前案件号
- 当前债务人
- 当前关注标的
- 最近一次重审结论
- 最近一次工具发现的关键异常
- 尚未完成的任务动作

可以舍弃：

- 冗余寒暄
- 重复确认
- 已被正式报告吸收的旧表述

### 13.7 案件切换隔离正式方案

这是必须强制落地的安全屏障。

#### 风险

如果上一轮还在讨论 `case_id=116`，下一轮突然切到 `case_id=210`，系统却继续携带旧 `memory_context/messages/report_part_b` 工作，就会产生跨案件污染。

#### 正式策略

在 `normalize_input` 或 `resolve_case_context` 节点加入案件切换检测：

1. 从 query 中提取新的 `case_id`
2. 与历史 `current_case_id` 对比
3. 如果发生切换：
   - 清空 `messages`
   - 清空 `memory_context`
   - 清空 `report_part_a/report_part_b/final_report`
   - 清空 `full_context_json/full_context_data`
   - 保留必要的全局偏好信息

### 13.8 Checkpointer 轻量化正式方案

LangGraph checkpointer 会在节点间写入 state 快照，因此重对象必须谨慎处理。

#### 不应直接长期持久化的对象

- 超大 `full_context_json`
- 原始 OCR 长文本
- 原始附件解析结果
- 企查查穿透全量 JSON
- 资金流完整拓扑

#### 正式策略

改造成“引用型状态”：

- `full_context_ref`
- `ocr_payload_ref`
- `enterprise_snapshot_ref`
- `fund_flow_ref`

实际数据可落：

- PostgreSQL 业务表
- Redis
- 对象存储

checkpointer 中只保留：

- ref id / key
- 摘要
- hash
- 更新时间

### 13.9 修正台账优先级正式方案

`correction_records` 必须高于历史对话、高于旧报告、高于原始 JSON 的冲突字段。

统一 Prompt 注入顺序：

1. 角色 prompt
2. 案件摘要 / 下钻索引
3. 当前问题
4. `correction_records` 或其脱水文本

也就是让修正台账位于“离输出最近”的位置，保证覆盖强度最高。

### 13.10 推荐状态字段升级

建议在现有 `AuditGraphState` 基础上补充：

```python
class AuditGraphState(TypedDict, total=False):
    memory_context: str
    memory_summary: str
    last_case_id: int
    current_focus_topics: list[str]

    full_context_ref: str
    ocr_payload_ref: str
    enterprise_snapshot_ref: str
    fund_flow_ref: str

    tool_trace_summary: list[str]
```

说明：

- `memory_summary`：历史对话滚动摘要
- `last_case_id`：用于案件切换检测
- `current_focus_topics`：例如“矿权估值”“白手套穿透”“任务补录”
- `*_ref`：重对象外置引用
- `tool_trace_summary`：工具发现的轻量结论摘要，不存原始工具返回

### 13.11 正式落地顺序

建议按风险优先级推进：

1. 案件切换隔离屏障
2. 工具输出脱水摘要
3. `memory_context` 滚动摘要
4. `trim_messages` 安全修剪
5. checkpointer 重对象指针化
6. 长期知识存储独立化

### 13.12 当前代码改造目标

从现有仓库出发，正式目标不是“继续凑合能跑”，而是把以下临时状态升级为正式机制：

- `messages[-window:]` 升级为“安全修剪 + 摘要滚动”
- 工具 `json.dumps(raw)` 升级为“本地脱水摘要返回”
- case 继承升级为“case change barrier”
- `full_context_json` 升级为“短期使用 + 后续 ref 化”
- drilldown prompt 注入升级为“修正台账最高优先级”

这套方案落地后，LangGraph 才算真正接住了多轮对话、审计重审与工业级状态管理。

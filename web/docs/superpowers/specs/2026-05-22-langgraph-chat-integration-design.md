# LangGraph 聊天集成设计（纯 LangGraph 方案）v2

**日期**: 2026-05-23（v2.1 复测修正：2026-05-25；v2.2 后端修复后复测：2026-05-25）
**状态**: 待实现
**基于真实接口测试数据**

> **v2.2 修订**（2026-05-25，后端修复后再次复测 `http://10.0.10.2:8081`）：
> - §2.5.1：`/chat/threads/{id}/messages` **已能返回数据**，返回结构为扁平列表，按时间顺序排列。
> - `POST /chat/invoke` 现返回**真实 LLM 答案**（不再是占位符）。
> - 验证**前端生成 thread_id（UUID）新建对话**：发消息后列表/详情/messages 均可查，多轮上下文生效；注意 `title = last_query`（随最新消息变化，影响 §5 列表展示）。
>
> **v2.1 修订**（2026-05-25，逐个真实调用复测）：
> - §2.1：`case_id=1` 不再返回 error，SSE 可完整跑通；修正事件流与映射。
> - §4.3：修正 `node`/`final` 的归一化逻辑（答案只在 `final.final_report`，无 token 流式）。
> - §4.4：修正 `caseId` 类型——LangGraph `case_id` 是**整数**，不能复用 uuid 列。

---

## 1. 背景与目标

完全接入 LangGraph 作为唯一 AI Provider，不再使用 Dify。基于实际测试的接口返回数据设计。

**支持功能**:
1. **案件分析** — 绑定具体案件，基于案件材料进行问答
2. **通用咨询** — 不绑定案件，通用法律知识问答

---

## 2. 外部接口清单（已测试）

### 2.1 主对话入口（SSE 流式）✅
- **接口**: `POST /chat/invoke`
- **请求头**: `Accept: text/event-stream` 或 body 传 `stream: true`
- **请求体**:
```json
{
  "thread_id": "test-thread-001",
  "query": "分析这个案件",
  "current_case_id": 1,
  "current_debtor_id": 0,
  "current_debtor_name": "",
  "stream": true,
  "uploaded_files": []
}
```

> ChatRequest 还接受可选字段（openapi 实测）：`doc_category`、`batch_name`、`upload_batch_id`、`operator_id`、`operator_name`。常规对话可不传。

**SSE 事件流**（复测 2026-05-25）：服务端按节点推进依次下发，事件类型为 `start / node / final / done`，失败时为 `error`：
```
event: start
data: {"thread_id": "verify-sse-002", "query": "你好", "current_case_id": 0, "uploaded_file_count": 0}

event: node
data: {"node": "normalize_input", "summary": "已归一化请求参数", "payload": {}}

event: node
data: {"node": "classify_intent", "summary": "已完成意图路由：drilldown", "payload": {"intent": "drilldown"}}

... (更多 node 事件，携带节点进度 summary，如 hydrate_memory_context / resolve_case_context / drilldown_agent_graph / finalize_answer)

event: node
data: {"node": "persist_conversation_memory", "summary": "已持久化当前会话记忆", "payload": {"message_count": 3}}

event: final
data: {"thread_id": "...", "current_case_id": 0, "final_report": "【完整答案文本】", ...}   // 字段与 §2.2 JSON 模式同构

event: done
data: {...}
```

**关键事实（与旧版描述不同）**:
- **case_id=1 不再返回 error**，能完整跑通（start → node×N → final → done）。旧版"case_id=1 返回 error"已作废。
- `node` 事件携带的是**节点进度 summary，不是答案文本增量**。
- **真正的答案只在 `final` 事件的 `final_report` 字段一次性返回**，没有 token 级流式输出。
- `error` 事件仅在真实失败时出现，格式 `{"thread_id": "...", "message": "错误信息"}`。

### 2.2 主对话入口（JSON 模式）✅
- **接口**: `POST /chat/invoke`（`stream: false`）
- **返回**（实测）:
```json
{
  "thread_id": "test-thread-json",
  "current_case_id": 0,
  "current_debtor_id": 0,
  "current_debtor_name": "",
  "final_report_ref": "",
  "final_report": "【追问/任务中枢占位】\ncase_id=0\nquery=你好...",
  "trace_items": [],
  "reconciliation_items": [],
  "unresolved_relations": [],
  "unresolved_claims": [],
  "citation_coverage": {
    "total_claims": 0,
    "cited_claims": 0,
    "uncited_claims": 0,
    "coverage_ratio": 0.0,
    "missing_items": []
  },
  "parse_summary": "",
  "doc_category": "",
  "batch_name": "",
  "upload_batch_id": "",
  "operator_id": "",
  "operator_name": "",
  "upload_batch_summary": {},
  "recognized_categories": [],
  "missing_categories": [],
  "duplicate_files": [],
  "suspected_mismatch_files": [],
  "new_files": [],
  "doc_category_validation": {},
  "intent": "drilldown",
  "memory_context": ""
}
```

### 2.3 获取会话历史列表 ✅
- **接口**: `GET /chat/threads?case_id={id}&limit=50&offset=0`
- **返回**（实测）:
```json
{
  "threads": [
    {
      "thread_id": "t1",
      "title": "案件1",
      "checkpoint_id": "1f143bb4-f637-6b9e-8012-fd1be5490b61",
      "case_id": 1,
      "debtor_id": 0,
      "debtor_name": "",
      "last_query": "案件1",
      "last_intent": "full_audit",
      "updated_at": "2026-04-29T11:05:19.506087+00:00"
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0
}
```

### 2.4 获取会话详情 ✅
- **接口**: `GET /chat/threads/{thread_id}`
- **返回**（实测，存在的数据）:
```json
{
  "thread_id": "t1",
  "title": "案件1",
  "checkpoint_id": "1f143bb4-f637-6b9e-8012-fd1be5490b61",
  "case_id": 1,
  "debtor_id": 0,
  "debtor_name": "",
  "last_query": "案件1",
  "last_intent": "full_audit",
  "final_report_ref": "",
  "memory_context": "[最近对话]\nuser: 案件1\nassistant: intent=full_audit | case_id=1 | report_generated chars=7324",
  "step": 18,
  "upload_batch_id": "",
  "doc_category": "",
  "batch_name": "",
  "created_at": "2026-04-29T10:56:43.409875+00:00",
  "updated_at": "2026-04-29T11:05:19.506087+00:00"
}
```

**注意**: 不存在的 thread_id 返回 `{"detail": "Thread xxx not found"}` (404)

### 2.5 删除会话 ✅
- **接口**: `DELETE /chat/threads/{thread_id}`
- **返回**:
```json
{
  "success": true,
  "thread_id": "xxx"
}
```

### 2.5.1 获取会话消息列表 ✅
- **接口**: `GET /chat/threads/{thread_id}/messages`
- **返回结构**: `{ thread_id, messages, message_count }`；单条 message 字段：`role, content, type, id, name, final_report_ref`
- **特点**: 返回按时间顺序排列的扁平消息列表，user 与 assistant 消息交替出现。适用于简单场景的历史展示。

### 2.5.2 获取会话轮次聚合列表 ✅
- **接口**: `GET /chat/threads/{thread_id}/turns`
- **返回结构**: `{ thread_id, turns, turn_count }`；每个 turn 包含一条 `user` 消息和该轮所有 `assistants` 回复（支持 regenerate 多版本）
- **字段说明**:
  - `turn_id`: 轮次唯一标识
  - `user`: 该轮用户消息（`role, content, created_at`）
  - `assistants`: 该轮 AI 回复数组（支持多版本 regenerate），含 `final_report_ref`、`intent`、`case_id`、`version`
- **与 messages 的区别**:
  - **按轮次聚合**：天然结构化，无需前端手动配对 user/assistant
  - **支持多版本**：同一轮次可返回多个 assistant 回复（version 区分）
- **建议**: 优先使用 turns 作为历史消息展示来源。完整答案正文仍建议以本地 `webMessages` 为准。

## 3. 接口可用性总结

| 接口 | 状态 | 说明 |
|------|------|------|
| `POST /chat/invoke` | ✅ 可用 | JSON + SSE（start/node/final/done）；答案只在 final.final_report，无 token 流式 |
| `GET /chat/threads` | ✅ 可用 | 有真实数据 |
| `GET /chat/threads/{id}` | ✅ 可用 | 存在返回详情，不存在返回 404 |
| `GET /chat/threads/{id}/messages` | ✅ 可用 | 按时间顺序返回扁平消息列表 |
| `GET /chat/threads/{id}/turns` | ✅ 可用 | 按轮次聚合，支持多版本，优先替代 messages |
| `DELETE /chat/threads/{id}` | ✅ 可用 | 软删除 |

---

## 4. 架构设计

### 4.1 核心原则

1. **不用 Dify**: 所有 AI 能力走 LangGraph
2. **本地代理**: 所有外部调用通过 Next.js API Route 代理
3. **复用现有 UI**: 基于 @assistant-ui/react 的 Thread UI 不变
4. **数据库存储**: 对话列表、消息历史存 PostgreSQL

### 4.2 数据流

```
Browser
  └── @assistant-ui/react (Thread UI)
        ├── useNewChatRuntime → 创建 thread → 调 /api/chat
        └── useChatRuntime → 加载历史 → 调 /api/chat

Next.js API Routes
  ├── POST /api/chat → 代理到 LangGraph /chat/invoke
  ├── GET /api/chat/threads → 代理到 LangGraph /chat/threads
  ├── GET /api/chat/threads/[id] → 代理到 LangGraph /chat/threads/{id}
  ├── GET /api/chat/threads/[id]/turns → 代理到 LangGraph /chat/threads/{id}/turns
  ├── DELETE /api/chat/threads/[id] → 代理到 LangGraph /chat/threads/{id}
```

### 4.3 SSE 事件处理

**LangGraph SSE → 前端统一格式**:

⚠️ 关键：`node` 事件是**节点进度 summary**，不是答案文本增量；答案**仅**在 `final.final_report`。因此不能把 `node` 直接当作答案 `text_chunk` 累加（否则会把"已归一化请求参数"等进度文字混进答案正文）。

| LangGraph 事件 | 前端事件 | 处理逻辑 |
|----------------|----------|----------|
| `start` | -（或 `node_started`） | 提取 thread_id，更新 conversation |
| `node` | `node_started` / `node_finished` | 作为"思考/进度"展示，用 `summary` 文案，**不计入答案正文** |
| `final` | `text_chunk` + `message_end` | 把 `final_report` 作为完整答案下发一次，再发 `message_end` 触发落库 |
| `done` | - | 流结束，发 `[DONE]` |
| `error` | `error` | 显示错误信息 |

**注意**: 答案一次性返回（无 token 流式），前端"打字机"效果只能在收到 `final` 后本地模拟；流式期间只能展示 `node` 进度。这与现有前端 `lib/assistant-ui/sse.ts` 的 `node_started/node_finished` + `text_chunk` 契约可对齐，无需改前端解析器。

### 4.4 数据模型

**webConversations**（修改）:
```typescript
appType: varchar("app_type", { length: 20 })
  .$type<"audit" | "extract" | "langgraph">()  // 扩展枚举，新增 langgraph
  .default("langgraph")

// 新增字段存 LangGraph thread_id（前端生成的字符串，如 "t1" 或 UUID）
langgraphThreadId: varchar("langgraph_thread_id", { length: 255 })

// ⚠️ 类型不匹配：现有 webConversations.caseId 是 uuid，但 LangGraph current_case_id 是【整数】
//   （实测 case_id=1、123；lib/types/doc-categories.ts 也是 number）。
//   不能复用 uuid 字段绑定 LangGraph 案件，需新增整数列：
langgraphCaseId: integer("langgraph_case_id")  // 绑定 LangGraph 案件（通用咨询为 null）
```

> 历史消息来源：§2.5.1 的 `/messages` 返回按时间顺序的扁平消息列表，§2.5.2 的 `/turns` 按轮次聚合、支持多版本，结构更优，建议优先使用。完整答案正文仍应以本地 `webMessages` 为准（落库时机见 §4.3 的 `final` → `message_end`），外部接口仅作辅助校验。

**webMessages**（保持现有）:
- 存用户消息和助手消息
- content 存文本内容

---

## 5. 对话列表设计

### 5.1 数据来源

从 LangGraph `GET /chat/threads` 获取，不按时间分组（接口已按时间排序）。

> ⚠️ 实测：`title` 等于 `last_query`（最新一条用户消息），会随对话推进变化（如多轮后变成"那第二步呢？"）。若想保持"对话标题=首句/案件名"，应在本地 `webConversations.title` 自行维护，不要直接展示 LangGraph 的 `title`。

### 5.2 展示方式

```
会话列表
─────────────────
📄 案件1                    4月29日
   [案件分析] #1

📄 通用咨询                 昨天
   [通用]

📄 债务纠纷分析             周一
   [案件分析] #2
```

**标签**:
- 案件分析（绿色）— 有 caseId
- 通用咨询（灰色）— 无 caseId

### 5.3 操作

- 点击 → 进入对话详情
- 长按/右键 → 删除对话

---

## 6. 新建对话

### 6.1 入口

**全局按钮**:
```
+ 新建对话
  ├── 🏢 案件分析...（弹出案件选择器）
  └── 💬 通用咨询
```

**案件详情页**:
- "AI 分析此案件"按钮
- 自动创建绑定该案件的对话

### 6.2 创建流程

1. 用户选择类型（案件分析/通用咨询）
2. 案件分析：选择案件（从已有案件列表）
3. 前端生成 `thread_id`（UUID）
4. 创建本地 conversation 记录
5. 跳转到 `/chat/{conversationId}`

---

## 7. 错误处理

### 7.1 流式错误

```
event: error
data: {"thread_id": "xxx", "message": "错误信息"}
```

**前端处理**:
- 显示错误提示（红色气泡）
- 保留已生成的内容
- 提供"重试"按钮

### 7.2 常见错误场景

| 场景 | 错误 | 处理 |
|------|------|------|
| 案件无数据 | `{"message": ""}` | 提示"案件暂无数据，请先上传材料" |
| Thread 不存在 | 404 | 自动创建新 thread |

---

## 8. 实现顺序

1. **Phase 1**: 数据库迁移（新增 langgraphThreadId；新增整数列 langgraphCaseId——LangGraph case_id 是整数，详见 §4.4；appType 枚举加 "langgraph"）
2. **Phase 2**: API Route 代理层
   - `/api/chat` → LangGraph /chat/invoke
   - `/api/chat/threads` → LangGraph /chat/threads
   - `/api/chat/threads/[id]` → LangGraph /chat/threads/{id}
3. **Phase 3**: 前端 Runtime（useChatRuntime）
4. **Phase 4**: 对话列表组件
5. **Phase 5**: 新建对话流程
6. **Phase 6**: 案件详情页快捷入口

---

## 9. 风险评估

| 风险 | 缓解措施 |
|------|----------|
| LangGraph 案件数据为空，返回 error | 前端做好空状态提示，引导用户上传材料 |
| thread_id 管理 | 本地生成 UUID，与 LangGraph 保持一致 |

---


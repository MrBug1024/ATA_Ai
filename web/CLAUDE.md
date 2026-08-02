# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment Files

| File | Purpose | Committed? |
|---|---|---|
| `.env.example` | Template with placeholder values | Yes |
| `.env.local` | Local dev backend-address overrides | **No** (`.gitignore`d) |
| `.env.test` | Test environment (fake keys) | Yes (no real secrets) |
| `.env.production` | Production build configuration | **No** — inject via CI/CD or Docker build args |

## Docker

```bash
# Production
docker compose up -d --build
```

Production `docker-compose.yml` only runs the frontend app. `NEXT_PUBLIC_*` backend addresses are compiled into the browser bundle at image build time; changing them requires rebuilding the image. Never put secrets in `NEXT_PUBLIC_*` values.

## Commands

```bash
# Development
pnpm dev              # Start Next.js dev server (port 3000)
pnpm build            # Production build
pnpm start            # Start production server
pnpm test             # Run vitest unit/integration tests
pnpm test:e2e         # Run Playwright E2E tests
```

## Environment Variables

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | 统一认证、AI、案件与领域后端地址 (e.g. `http://10.0.10.2:8081`),**浏览器直连** |

## Architecture

AI 辅助文档分析平台。浏览器通过 `NEXT_PUBLIC_API_BASE_URL` 直连统一后端；Next.js 只负责 UI，不运行认证 API、PostgreSQL 或 Drizzle。登录由 `POST /auth/login` 提供，身份通过 `GET /me` 校验。详细产品架构见 `README.md`。

### Data Flow

```
Browser
  └── lib/backend/* → Unified API (HTTP / SSE / Bearer auth)
```

> access token 只能发送到 `NEXT_PUBLIC_API_BASE_URL`，不得发送给其他 origin。
> token 保存在浏览器 `localStorage`；这是移除同源服务端会话后的已知 XSS 风险，任何富文本或外部内容渲染都必须保持严格净化。

### Backend 接缝(关键约束)

`lib/backend/` 是唯一的后端契约模块。组件、hooks、页面**不得**直接 `fetch` 后端或拼接后端 URL,只能调用此层的命名操作:

```ts
// 正确
import { getThreadDetail, getThreadTurns, deleteThread } from "@/lib/backend/langgraph";
import { createCase } from "@/lib/backend/cases";
```

- `lib/backend/http.ts` — `BackendError`、`extractErrorMessage()`(统一 FastAPI `detail` / `error` / `message` 错误体)、JSON/form/无 body 请求 helper。底层走 `lib/api/client.ts` 的 `apiFetch()`；仅 LangGraph 请求附加 Bearer 且 401 时重定向登录页，其他后端的非 2xx（包括 401）仍由调用层转为 `BackendError`。
- `lib/backend/auth.ts` — LangGraph 认证操作：`login()` / `getMe()` / `logout()` / `changePassword()`。
- `lib/backend/admin.ts` — LangGraph 管理操作：公司、用户、标签、用户角色与全局角色权限；对应 key builder 供 `use-admin.ts` 使用。
- `lib/backend/langgraph.ts` — LangGraph 全部操作:threads(`threadsKey()` / `listThreads()` / `getThreadDetail()` / `getThreadTurns()` / `getThreadMessages()` / `deleteThread()`)、`chatInvoke()`(流式)、文件上传(`uploadChatFiles()` / `uploadAndIngest()`)、案件文件(`caseMaterialEventsKey()` 等 key builder + 对应操作)、图谱与证据(`fetchSubgraph()` / `fetchRelationEvidence()` / `resolveEvidence()` 等)。
- `lib/backend/cases.ts` — Cases 后端:`listCases()` / `createCase()` / `getDocCategories()` / `getCaseDocCategories()` / `validateDocCategory()`。
- SWR hooks 的 key 一律用 backend 模块导出的 `xxxKey()` builder,fetcher 调对应操作;跨模块刷新会话列表用当前 SWR Provider 的 `mutate(isThreadsListKey)`,覆盖所有分页/过滤组合。

### SSE 事件格式

浏览器直接 `POST {NEXT_PUBLIC_API_BASE_URL}/chat/invoke`(经 `chatInvoke()`),前端消费原始 SSE 事件:

```
event: start       data: {"thread_id":"...","query":"..."}
event: node        data: {"node":"agent","summary":"步骤说明","payload":{}}
event: text_chunk  data: {"text":"增量 token"}
event: final       data: {"final_report":"完整回答","final_report_ref":"<不透明 UUID>"}
event: done        data: {}
event: error       data: {"message":"..."}
```

`lib/assistant-ui/sse.ts` 把事件解析为 `LangGraphSseEvent`(discriminated union),消费方 switch `ev.type`,禁止手动 `as` 断言。注意:前端**有意不**把 `final_report` 写回消息内容(text_chunk 累加已是流式结果,替换会让 smooth 动画重放);只取 `final_report_ref` 供证据追溯。

### 文件处理

- **聊天附件**:`uploadChatFiles()` 上传 → `lib/assistant-ui/attachment-store.ts`(单一事实来源)暂存 FileItem 与预览 URL → 发送时 `consumeFileItemsByAttachmentIds()` 取走随 `chatInvoke` 携带。
- **案件卷宗**:`uploadAndIngest()` 上传,处理进度轮询 `getMaterialEvent()`;对话框状态机在 `lib/upload/add-material-flow.ts`(纯 reducer,可单测)。
- 上传进度由 `lib/stores/upload-queue.ts`(Zustand)在客户端统一管理,浮动组件展示队列。

### Key Directories

- `lib/backend/` — 唯一后端契约模块(`http.ts` 核心,`auth.ts` / `admin.ts` / `langgraph.ts` / `cases.ts` 命名操作与 key builder)。
- `lib/api/` — `client.ts`(`apiFetch` Bearer 注入、401 处理、`langgraphUrl()` / `casesUrl()`,仅供 lib/backend 使用)。
- `lib/auth/` — 浏览器端 LangGraph access token 状态；不包含服务端认证或数据库代码。
- `lib/assistant-ui/` — 对话 runtime(`use-langgraph-runtime.ts`)、SSE 解析(`sse.ts`)、附件 store(`attachment-store.ts`)与 adapter(`chat-attachment-adapter.ts`)。
- `lib/hooks/` — SWR / mutation hooks,全部是 lib/backend 操作的薄声明;命令式操作用 `use-backend-mutation.ts` 包装。
- `lib/upload/add-material-flow.ts` — 上传卷宗对话框的纯状态机。
- `lib/utils/file-type.ts` — 共享文件类型探测(`getFileTypeInfo` 图标 / `resolvePreviewType` 预览)。
- `components/shared/preview-host.tsx` — 附件预览 Provider 与分栏面板(挂在 AssistantChat 内,点击消息附件打开);`file-preview-panel.tsx` 渲染图片 / PDF / 文本,其余降级下载。
- `components/shared/pdf-page-view.tsx` — 全项目唯一的 react-pdf 包装(含 bbox 高亮,`pdfjs.workerSrc` 单点配置;SSR 路由需经 `next/dynamic({ ssr: false })` 加载)。
- `components/chat/chatgpt-thread.tsx` — `@assistant-ui/react` thread UI(ChatGPT 风格布局,含 ThinkingPanel)。
- `components/knowledge-graph/` — 图谱模态、证据抽屉、页图查看器、时间线等。

### UI Stack

- **@assistant-ui/react** — Chat thread UI primitives（必须在 `AssistantRuntimeProvider` 内；`Tooltip` 需要 `TooltipProvider`）
- **shadcn/ui** — `components/ui/`
- **Tailwind CSS v4** + `tw-animate-css`
- **Zustand** for client state, **Sonner** for toasts

### Persistence Notes

- 前端仓库没有数据库 schema、迁移或数据库容器。
- 用户、会话、消息与文件都由外部后端持久化；前端通过命名 API 操作读取。

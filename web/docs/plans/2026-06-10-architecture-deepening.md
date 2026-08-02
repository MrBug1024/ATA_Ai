# Architecture Deepening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收敛 25+ 处散落的后端直连调用到统一的 `lib/backend/` 接缝,类型化 SSE 事件,并整合附件存储、PDF 渲染、文件类型探测与上传状态机等浅模块。

**Architecture:** 接受"浏览器直连 LangGraph/Cases 后端"的现状(候选 1 方案 b),新建 `lib/backend/` 作为唯一后端契约模块(http 核心 + 按后端分文件的命名操作),hooks 退化为薄 SWR 声明;文档(CLAUDE.md/AGENTS.md)改写为与现实一致。

**Tech Stack:** Next.js 15 / React 19 / SWR / Zustand / vitest / react-pdf

**决策记录:**
- 候选 1 → 方案 (b):不重建 Next.js 网关,收敛直连调用 + 改文档。安全暴露(后端无会话校验)作为已知 tradeoff 写入文档。
- 候选 2 → 仅 ①:SSE discriminated union;不做 send/reload 提取。
- 候选 4 证据渲染部分:**跳过**。三处渲染形态差异大(列表项带引文 / 紧凑 chip / 页图叠加),非真重复。
- `page-viewer.tsx` 的 `resolveMode` 不并入共享 `resolvePreviewType`:其"有 URL 时兜底当图片"语义是知识图谱页特有,强行统一会改行为。

**验证命令:** `pnpm test`(vitest run),最终 `pnpm build`。每个任务一个 commit(conventional commits,无 attribution)。

---

### Task 1: 后端 HTTP 核心 `lib/backend/http.ts`

**Files:**
- Create: `lib/backend/http.ts`
- Test: `tests/unit/backend-http.test.ts`

接口:

```ts
import { apiFetch } from "@/lib/api/client";

export class BackendError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "BackendError";
  }
}

/** FastAPI 风格错误体取 message:detail[].msg / detail / error,兜底 fallback */
export function extractErrorMessage(body: unknown, fallback: string): string;

export async function getJson<T>(url: string, fallback?: string): Promise<T>;
export async function postJson<T>(url: string, body: unknown, fallback?: string): Promise<T>;
export async function postForm<T>(url: string, form: FormData, fallback?: string): Promise<T>;
export async function deleteJson(url: string, fallback?: string): Promise<void>;
```

实现要点:所有函数走 `apiFetch`(保留 401 重定向);`!res.ok` 时 `res.json().catch(() => ({}))` 后用 `extractErrorMessage` 抛 `BackendError`。这统一了现状三种错误解析变体(use-chat-upload 的 `detail[0]?.msg`、use-upload-ingest 的 `err.detail || err.error`、create-case-dialog 的 detail 数组 join)。

- [ ] 写失败测试(extractErrorMessage 三种错误体 + getJson/postJson/postForm 的 ok 与 !ok 路径,mock global.fetch)
- [ ] 实现并通过
- [ ] Commit `refactor(backend): 新增统一后端 HTTP 核心模块`

### Task 2: 命名操作模块 `lib/backend/langgraph.ts` + `lib/backend/cases.ts`

**Files:**
- Create: `lib/backend/langgraph.ts`, `lib/backend/cases.ts`, `lib/backend/index.ts`
- Test: `tests/unit/backend-langgraph.test.ts`, `tests/unit/backend-cases.test.ts`

`langgraph.ts` 导出(URL builder 用于 SWR key,操作函数用于 fetch):

```ts
// threads
threadsKey(): string                       // = langgraphUrl("/chat/threads?limit=50&offset=0")
listThreads(): Promise<LangGraphThread[]>  // 解 { threads } 包裹
getThreadMessages(threadId): Promise<ThreadMessagesResponse>
deleteThread(threadId): Promise<void>
chatInvoke(body: ChatInvokeBody, signal): Promise<Response>  // 流式,返回原始 Response
// files
uploadChatFiles(req: ChatUploadRequest, files: File[]): Promise<ChatUploadResponse>
uploadAndIngest(req): Promise<UploadAndIngestResponse>
caseMaterialEventsKey(caseId) / listCaseMaterialEvents(caseId)   // 解 material_events
caseUploadBatchesKey(caseId) / listCaseUploadBatches(caseId)     // 解 upload_batches
evolutionItemsKey(caseId, action?, limit) / listEvolutionItems(...)  // 解 evolution_items
unresolvedItemsKey(caseId, status, limit) / getUnresolvedItems(...)
materialEventKey(eventId) / getMaterialEvent(eventId)
uploadBatchKey(batchId) / getUploadBatch(batchId)
pageAnchorsKey(fileId, pageNo, chunkId?) / getPageAnchors(...)
// graph / evidence
graphEntitiesKey(caseId) / listGraphEntities(caseId)             // 解 entities
fetchSubgraph(req) / fetchRelationEvidence(req) / validateDemoCaseTrace(req) / resolveEvidence(req)
```

`cases.ts` 导出:`casesKey(page, keyword)` / `listCases`、`docCategoriesKey()` / `getDocCategories`(解 categories)、`caseDocCategoriesKey(caseId)` / `getCaseDocCategories`、`validateDocCategory(req)`、`createCase(payload): Promise<{ case_id: number; message?: string }>`。

类型迁移:`LangGraphThread`、`ThreadMessage`、`ThreadMessagesResponse` 定义移入 `langgraph.ts`(后者原内联在 `app/(main)/chat/[id]/page.tsx`);`use-conversations.ts` 改为 re-export 保持兼容。`Case` 接口从 `use-cases.ts` 移入 `cases.ts`,hook re-export。

- [ ] 写失败测试(每个 key builder 的 URL;代表性操作的解包与错误路径,mock fetch)
- [ ] 实现并通过
- [ ] Commit `refactor(backend): 收敛全部后端契约到 lib/backend 命名操作`

### Task 3: SSE 类型化事件 + chatInvoke 迁移

**Files:**
- Modify: `lib/assistant-ui/sse.ts`, `tests/unit/sse.test.ts`

```ts
export type LangGraphSseEvent =
  | { type: "start"; threadId?: string }
  | { type: "node"; node: string; summary?: string; payload?: Record<string, unknown> }
  | { type: "text_chunk"; text: string }
  | { type: "final"; finalReportRef?: string }
  | { type: "done" }
  | { type: "error"; message: string }
  | { type: "unknown"; event: string; data: Record<string, unknown> };

export function toLangGraphEvent(event: string, data: Record<string, unknown>): LangGraphSseEvent;
export async function* parseSseStream(response, signal?): AsyncGenerator<LangGraphSseEvent>;
```

`runStream` 内 switch 改为 `ev.type` 窄化,删除全部 `as string` 断言;fetch 调用替换为 `chatInvoke(...)`(payload 构造移入 backend 模块)。`sse.test.ts` 断言改为类型化事件。

- [ ] 更新测试(typed 事件断言,先失败)
- [ ] 实现并通过
- [ ] Commit `refactor(sse): SSE 事件 discriminated union,invoke 迁入 backend`

### Task 4: SWR GET hooks 迁移(12 个)

**Files (Modify):** `use-conversations` `use-case-doc-categories` `use-case-material-events` `use-case-upload-batches` `use-doc-categories` `use-evolution-items` `use-graph-entities` `use-material-event` `use-page-anchors` `use-unresolved-items` `use-upload-batch` `use-cases`

模板(公开返回形状不变,既有测试为安全网):

```ts
export function useCaseMaterialEvents(caseId: number | null) {
  const key = caseId !== null ? caseMaterialEventsKey(caseId) : null;
  const { data, error, isLoading, mutate } = useSWR(key, () => listCaseMaterialEvents(caseId as number));
  return { events: data ?? [], isLoading, error: error instanceof Error ? error.message : null, refresh: mutate };
}
```

`THREADS_URL` 保持从 `use-conversations` 导出(值 = `threadsKey()`,`use-langgraph-runtime` 的 `mutate(THREADS_URL)` 不受影响)。

- [ ] 逐个迁移,删除本地 fetcher 与 URL 拼接
- [ ] `pnpm test` 既有 hook 测试全绿
- [ ] Commit `refactor(hooks): SWR hooks 迁移至 backend 操作`

### Task 5: mutation hooks 收敛

**Files:**
- Create: `lib/hooks/use-backend-mutation.ts`; Test: `tests/unit/use-backend-mutation.test.tsx`
- Modify: `use-demo-case-validate` `use-evidence-resolve` `use-graph-subgraph` `use-relation-evidence` `use-chat-upload` `use-upload-ingest` `use-validate-doc-category`

```ts
export function useBackendMutation<TReq, TResp>(fn: (req: TReq) => Promise<TResp>) {
  // { data, isMutating, error, trigger, reset } — 复刻现有 4 个 KG hook 的状态机
}
// 迁移示例(公开 API 不变):
export function useEvidenceResolve() {
  const m = useBackendMutation(resolveEvidence);
  return { data: m.data, isMutating: m.isMutating, error: m.error, resolve: m.trigger, reset: m.reset };
}
```

`use-chat-upload` / `use-upload-ingest` / `use-validate-doc-category` 变为 backend 操作的薄包装(FormData 构造移入 backend)。

- [ ] useBackendMutation 测试先行(成功/失败/reset)
- [ ] 迁移 7 个 hook,既有测试绿
- [ ] Commit `refactor(hooks): mutation hooks 收敛到 useBackendMutation`

### Task 6: 页面与组件内联调用迁移

**Files (Modify):**
- `app/(main)/chat/[id]/page.tsx` → `getThreadMessages(id)`(删本地 ThreadMessage 类型与 apiFetch)
- `app/(main)/cases/[id]/page.tsx` → `getThreadMessages(latestThreadId)`
- `components/layout/app-sidebar.tsx:209` → `deleteThread(id)`(try/catch + toast)
- `components/cases/create-case-dialog.tsx:53` → `createCase(payload)`(错误解析归 backend)

- [ ] 迁移 4 处;`grep -rn "langgraphUrl\|casesUrl" --include="*.tsx" --include="*.ts" app components lib/hooks lib/assistant-ui` 仅剩 lib/backend 内部使用
- [ ] `pnpm test` 全绿(case-detail-page.test.tsx 等)
- [ ] Commit `refactor: 页面与组件改走 backend 操作,消除内联 fetch`

### Task 7: 附件生命周期单一事实来源

**Files:**
- Create: `lib/assistant-ui/attachment-store.ts`; Test: `tests/unit/attachment-store.test.ts`
- Modify: `chat-attachment-adapter.ts`(委托存储)、`use-langgraph-runtime.ts`、`app/(main)/chat/[id]/page.tsx`、`components/assistant-ui/attachment.tsx`(import 改向)、`tests/unit/chat-attachment-adapter.test.ts`

```ts
// 单 Map<string, { fileItem?: FileItem; previewUrl?: string }>
stageFileItem(id, fi)            // 同步记 fileItem + previewUrl(原 set + rememberPreviewUrl)
consumeFileItems(ids): FileItem[] // 取走 fileItem,保留 previewUrl(原 consume 语义)
primeFileItems(entries)
seedPreviewUrls(entries)
getPreviewUrl(id)
resetAttachmentStore()           // 测试用
```

- [ ] store 测试先行(consume 后 previewUrl 仍可取)
- [ ] 迁移 + 旧双 Map 删除,全部消费方 import 新模块
- [ ] Commit `refactor(attachments): 附件状态收敛为单一 store`

### Task 8: 共享文件类型探测 `lib/utils/file-type.ts`

**Files:**
- Create: `lib/utils/file-type.ts`; Test: `tests/unit/file-type.test.ts`
- Modify: `components/assistant-ui/attachment.tsx`(删 26-58 行本地实现)、`components/shared/file-preview-panel.tsx`(删 resolvePreviewType)

```ts
export function getFileTypeInfo(name?: string, contentType?: string): { icon: React.ElementType; color: string };
export function resolvePreviewType(name: string, contentType?: string): "image" | "pdf" | "text" | "none";
```

实现 = attachment.tsx 现有 getFileTypeInfo 原样迁移 + file-preview-panel 的 resolvePreviewType 原样迁移(签名改为 name+contentType,不依赖 PreviewableFile)。

- [ ] 测试先行(image/pdf/word/sheet/video/audio/archive/code/兜底 + preview 三态)
- [ ] 迁移两处消费方
- [ ] Commit `refactor(utils): 文件类型探测收敛为共享模块`

### Task 9: PDF 渲染整合

**Files:**
- Create: `components/shared/pdf-page-view.tsx`(由 `components/knowledge-graph/pdf-page-view.tsx` 移动+泛化)
- Modify: `components/knowledge-graph/page-viewer.tsx`(dynamic import 路径)、`components/shared/file-preview-panel.tsx`(内嵌 PdfViewer 的 Document/Page 换用共享组件,保留分页 UI)
- Delete: `components/knowledge-graph/pdf-page-view.tsx`

泛化 props:`bboxes?: BBox[]`(无则不渲染 overlay)、`renderTextLayer?: boolean`、`renderAnnotationLayer?: boolean`、`onLoadSuccess?: (numPages: number) => void`。`pdfjs.GlobalWorkerOptions.workerSrc` 赋值只保留在共享模块一处(file-preview-panel 删除第 11 行)。

- [ ] 移动+泛化;两个消费方接线
- [ ] `pnpm test`(bbox-overlay、graph-modal 等相关测试绿);手动确认无 SSR 引入(file-preview-panel 是 client 组件,直接 import 可保留其现有方式;page-viewer 保持 dynamic ssr:false)
- [ ] Commit `refactor(pdf): 统一 PDF 页渲染组件,workerSrc 单点配置`

### Task 10: 上传状态机提取

**Files:**
- Create: `lib/upload/add-material-flow.ts`; Test: `tests/unit/add-material-flow.test.ts`
- Modify: `components/cases/add-material-dialog.tsx`(useReducer 接线,JSX 不动)

```ts
export type Step = "select" | "validate" | "uploading" | "processing" | "completed" | "failed";
export interface FlowState { step: Step; files: File[]; selectedCategory: string; batchName: string;
  validationResult: ValidationResult | null; materialEventId: string | null; uploadResult: UploadAndIngestResponse | null; }
export type FlowEvent =
  | { type: "FILES_ADDED"; files: File[] } | { type: "FILE_REMOVED"; index: number }
  | { type: "CATEGORY_SELECTED"; code: string } | { type: "BATCH_NAME_SET"; name: string }
  | { type: "VALIDATE_STARTED" } | { type: "VALIDATION_OK"; result: ValidationResult }
  | { type: "VALIDATION_WARNED"; result: ValidationResult } | { type: "VALIDATION_ERRORED" }
  | { type: "UPLOAD_STARTED" } | { type: "UPLOAD_SUCCEEDED"; result: UploadAndIngestResponse }
  | { type: "UPLOAD_FAILED" } | { type: "PROCESSING_COMPLETED" } | { type: "PROCESSING_FAILED" } | { type: "RESET" };
export function flowReducer(state: FlowState, event: FlowEvent): FlowState;
export function validationOutcome(r: ValidationResult): "proceed" | "warn";  // ok && !mismatch && !duplicate
export function canSubmit(state: FlowState): boolean;
```

- [ ] reducer 测试先行(全部转换路径 + canSubmit + validationOutcome)
- [ ] 对话框接线(异步编排仍在组件,只 dispatch 事件)
- [ ] Commit `refactor(cases): 上传卷宗状态机提取为纯模块`

### Task 11: 顺手清理

**Files:**
- Modify: `lib/api/response.ts`(删 handleRouteError)、`tests/unit/api-response.test.ts`(删对应用例)
- Create: `components/help/help-content.tsx`(内容数据);Modify: `components/help/help-dialog.tsx`(映射渲染)

- [ ] 确认 `grep -rn handleRouteError app lib components` 仅 response.ts + 测试,删除
- [ ] 帮助内容外置为 `HELP_SECTIONS: { id, title, content: ReactNode }[]`,dialog 瘦身为骨架
- [ ] Commit `chore: 移除死代码 handleRouteError,帮助内容外置`

### Task 12: 文档对齐

**Files:**
- Modify: `CLAUDE.md`、`AGENTS.md`

重写 Architecture/Data Flow/Provider 层章节:浏览器经 `NEXT_PUBLIC_LANGGRAPH_API_BASE_URL` / `NEXT_PUBLIC_CASES_API_BASE_URL` 直连后端;`lib/backend/` 是唯一后端契约模块(组件/hooks/页面禁止直接 fetch 后端);`app/api/` 仅剩 Better Auth;明确安全 tradeoff(后端接口不经会话校验,依赖网络层隔离)。删除不存在的 `lib/langgraph/`、`/api/chat`、webConversations 等描述。

- [ ] 改写并核对每条描述与代码一致
- [ ] Commit `docs: CLAUDE.md/AGENTS.md 对齐直连架构与 lib/backend 接缝`

### Task 13: 终验

- [ ] `pnpm test` 全绿
- [ ] `pnpm build` 成功
- [ ] `rtk gain` 不适用;`git log --oneline` 检查提交序列

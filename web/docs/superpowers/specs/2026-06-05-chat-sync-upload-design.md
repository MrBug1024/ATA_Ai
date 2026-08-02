# 对话入口同步文件上传 — 设计

**日期**: 2026-06-05
**状态**: 待实现
**对应后端规范**: `POST /chat/upload-files` + `POST /chat/invoke` (2026-06-05)

---

## 1. 背景与目标

LangGraph 后端在 `2026-06-05` 新增对话流同步文件上传接口,把"先把材料落 MinIO,再带引用进对话"合并成两步:
- `POST /chat/upload-files` (multipart) — 同步落 MinIO,返回 `FileItem[]` 与 `duplicate_files`
- `POST /chat/invoke` body 加 `uploaded_files: FileItem[]` — 后端看到 `uploaded_files` 即走 ingest/audit 节点

**前端要做的**:让用户能在 chat composer 里拖文件 → 文件自动先一步落到后端 → 发送时把 storage_ref/file_hash 等塞进 invoke。约束:
- 强约束:无 `caseId` 时不允许上传(后端 `current_case_id > 0` 是硬要求)
- 现有架构是浏览器直连 LangGraph(`7e3de01 refactor(api): drop Next.js Route Handlers and LangGraph provider layer`),不重建代理层
- chat composer 已用 `@assistant-ui/react`,附件状态用 AUI 的 `AttachmentAdapter` 机制,不写新的全局 store

**不在范围**:
- 不动 `AddMaterialDialog`(案件页的同步上传+OCR 路径,本来就独立,本次不动)
- 不动 `lib/stores/upload-queue.ts`(该 store 服务于 AddMaterialDialog 的长生命周期 OCR 任务,本特性的附件生命周期短)
- 不动 `lib/hooks/use-upload-ingest.ts`(`/files/upload-and-ingest` 旧路径,与本特性正交)

---

## 2. 外部接口契约(摘自规范)

### 2.1 `POST /chat/upload-files`

multipart-form 字段:
- `files` (multi) — 待上传文件
- `current_case_id` (required,>0)
- `current_debtor_id` (optional,unknown→0)
- `current_debtor_name` (optional)
- `doc_category` (optional)
- `batch_name` (optional)
- `upload_batch_id` (optional,空时后端生成)
- `operator_id` / `operator_name` (optional)

200 响应:
```ts
{
  upload_batch_id: string;
  case_id: number;
  debtor_id: number;
  debtor_name: string;
  effective_debtor_name: string;
  file_count: number;
  duplicate_files: string[];
  files: FileItem[];
}
```

`FileItem` 形状(节选,详见 §3.1):
```ts
{
  name, url, type, extension, content_type, content,
  doc_category, upload_batch_id, file_hash, file_size,
  content_ref, duplicate_of, storage_ref,
  storage_provider, storage_bucket, storage_key, storage_etag, storage_version
}
```

去重规则:同 SHA256 在**单次请求**内去重;`duplicate_files` 是被去重的文件名列表。

### 2.2 `POST /chat/invoke`

`body.uploaded_files: FileItem[]`(新字段)。`stream: true` 或 `Accept: text/event-stream` 走 SSE。

SSE 事件:`start / node / text_chunk / final / done / error`(已实现)。

---

## 3. 数据模型

### 3.1 新文件 `lib/types/chat-upload.ts`

导出:`FileItem`、`ChatUploadResponse`、`ChatUploadRequest`(纯类型,无运行时代码)。

### 3.2 既有 `lib/assistant-ui/types.ts`

`DbMessage` 不动;附件不在消息内容里,只存于 AUI 的 composer state 与 runtime 的 `useRef<Map<messageId, FileItem[]>>`。

### 3.3 既有 `components/assistant-ui/attachment.tsx`

**不动**。AUI 的 `AttachmentLike`(`status: requires-action/running/complete/incomplete`)和它现在的展示逻辑完全够用。

---

## 4. 架构与数据流

```
Browser (Composer / Thread)
─────────────────────────────────────────────────
drop / pick → ComposerPrimitive.AddAttachment
                 ↓
        useAttachmentAdapters()  (AUI 内置)
                 ↓
        ChatAttachmentAdapter (新)
          .add({ file })
            ├─ 状态: running(乐观)
            ├─ useChatUpload.upload(files, caseId)
            │     └─ POST /chat/upload-files
            │         → { files: FileItem[], duplicate_files: [] }
            ├─ 解析
            │     ├─ files[*] → attachment.content[0].file_item
            │     │   status: complete
            │     └─ duplicate_files → toast.warning(数量/名字)
            │                          不进 attachment.content
            └─ 失败 → status: incomplete, reason: err.message
                 ↓
click Send → onNew(message)
                 ↓
        useLanggraphRuntime.handleSend
          ├─ collectFileItems(message)
          │     └─ flatMap message.attachments[*].content[*].file_item
          ├─ attachmentsRef.current.set(streamMsgId, fileItems)
          └─ runStream({ ..., uploadedFiles: fileItems })
                 ↓
        fetch POST /chat/invoke
          body.uploaded_files = FileItem[]
```

---

## 5. 模块设计

### 5.1 `lib/hooks/use-chat-upload.ts` (新)

```ts
"use client";
export function useChatUpload() {
  return useCallback(async (req: ChatUploadRequest, files: File[]): Promise<ChatUploadResponse> => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    form.append("current_case_id", String(req.caseId));
    form.append("current_debtor_id", String(req.debtorId ?? 0));
    form.append("current_debtor_name", req.debtorName ?? "");
    if (req.docCategory) form.append("doc_category", req.docCategory);
    if (req.batchName) form.append("batch_name", req.batchName);
    if (req.uploadBatchId) form.append("upload_batch_id", req.uploadBatchId);
    if (req.operatorId) form.append("operator_id", req.operatorId);
    if (req.operatorName) form.append("operator_name", req.operatorName);

    const res = await apiFetch(langgraphUrl("/chat/upload-files"), { method: "POST", body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const msg =
        (Array.isArray(err.detail) && err.detail[0]?.msg) ||
        err.error ||
        `Chat upload failed: ${res.status}`;
      throw new Error(msg);
    }
    return res.json() as Promise<ChatUploadResponse>;
  }, []);
}
```

不与 `useUploadIngest` 共享逻辑 — 该 hook 走 `/files/upload-and-ingest` 旧路径,产物含 `material_event_id`,本 hook 走新路径,产物只含 `FileItem`。

### 5.2 `lib/assistant-ui/chat-attachment-adapter.ts` (新)

AUI `AttachmentAdapter` 实现,接收 `caseId: number` 与 `upload` 函数(从 hook 来)。适配器由 `useExternalStoreRuntime({ adapters: { attachments } })` 注入。

```ts
export interface ChatAttachmentAdapterDeps {
  caseId: number;
  upload: (req: ChatUploadRequest, files: File[]) => Promise<ChatUploadResponse>;
}

export function createChatAttachmentAdapter(deps: ChatAttachmentAdapterDeps): AttachmentAdapter {
  return {
    accept: "*/*",   // 任何后端 LangGraph 支持的格式
    async add({ file }) {
      const id = crypto.randomUUID();
      try {
        const res = await deps.upload({ caseId: deps.caseId }, [file]);
        if (res.duplicate_files.length > 0) {
          toast.warning(`本批重复文件已忽略: ${res.duplicate_files.join(", ")}`);
        }
        const fileItems = res.files.filter(f => !res.duplicate_files.includes(f.name));
        if (fileItems.length === 0) {
          return { id, type: "file_item", name: file.name, contentType: file.type, file, status: { type: "incomplete", reason: "全部文件重复" } };
        }
        const fi = fileItems[0];
        return {
          id: `${id}-${fi.file_hash}`,
          type: "file_item",
          name: fi.name,
          contentType: fi.content_type,
          file,                              // 保留 File 用于本地图片预览
          file_item: fi,                     // FileItem 详情
          status: { type: "complete" },
        };
      } catch (err) {
        const reason = err instanceof Error ? err.message : "上传失败";
        return {
          id,
          type: "file_item",
          name: file.name,
          contentType: file.type,
          file,
          status: { type: "incomplete", reason },
        };
      }
    },
    async remove() { /* 移除不需去 MinIO */ },
    async send() { /* add() 已直接返 complete,send 阶段无副作用 */ },
  };
}
```

AUI 关键 API(已查官方文档,2026-06-05):
- `useExternalStoreRuntime({ adapters: { attachments: AttachmentAdapter | undefined } })` — 字段名 `attachments`(复数)
- `AttachmentAdapter.add({ file })` 返回**单个** attachment 对象(非数组)
- `AttachmentAdapter.send(attachment)` 把"待发送"翻"complete"并填 `content`;我们 add 即上传,send 留空
- `accept: "*"` 控制 input accept (AUI `fileMatchesAccept` 仅认字面 `"*"`;`"*/*"` 会被拒);我们用通配让用户拖任意文件(后端 422 时给明确 reason)
- attachment 的 `content` 数组是 AUI 用来塞给 message 内容;我们用 `file_item: FileItem` 字段存到 `content[0]`,在 runtime 的 `onNew` 时取出来

### 5.3 `lib/assistant-ui/sse.ts` 改动

`RunStreamRequest` 加 `uploadedFiles?: FileItem[]`;body 拼装改为:
```ts
uploaded_files: request.uploadedFiles ?? [],
```
其余不变。

### 5.4 `lib/assistant-ui/use-langgraph-runtime.ts` 改动

新增:
- `attachmentsRef = useRef<Map<string, FileItem[]>>()`
- `collectFileItems(message: AppendMessage): FileItem[]` — flatMap `message.attachments[*].content` 取 `type === "file_item"` 的项的 `file_item`
- 接收 `attachmentAdapter: AttachmentAdapter | null` 参数,传给 `useExternalStoreRuntime({ ..., adapters: { attachment: attachmentAdapter } })`

`handleSend`:
```ts
const fileItems = collectFileItems(message);
attachmentsRef.current.set(streamMsgId, fileItems);
await runStream({ ..., uploadedFiles: fileItems }, ...);
```

`handleReload(parentId)`:
```ts
const fileItems = attachmentsRef.current.get(parentId) ?? [];
await runStream({ ..., uploadedFiles: fileItems }, ...);
```

### 5.5 `components/chat/assistant-chat.tsx` 改动

`AssistantChat` 加 `attachmentAdapter: AttachmentAdapter | null` prop,透传到 `useLanggraphRuntime`。
两个 chat 页面入口都传:
- `/chat` 无 caseId → 传 `null`
- `/chat/[id]?caseId=N` → 用 `useMemo` 包 `createChatAttachmentAdapter({ caseId, upload })`(upload 从 `useChatUpload()` 来)

### 5.6 `components/chat/chatgpt-thread.tsx` 改动

`ComposerAddAttachment` 接受 `disabled?: boolean; disabledReason?: string` props;`disabled` 时按钮 disabled + tooltip 显示 `disabledReason`。无 caseId 时:
- `disabled = true`
- `disabledReason = "请从案件列表的 AI 分析入口进入以上传卷宗"`

`ComposerSendButton` 不动 — AUI 的 `s.composer.attachments.some(a => a.status.type === "running")` 检测已经覆盖"上传中禁用"。

`AttachmentDropzone` 的 `asChild` div 不动 — AUI 在没有 adapter 时,拖入与按钮点击都不会触发任何 `add()`,自然失效。**实现时验证**:在 `/chat` 页(无 adapter)试着点击附件按钮,确认 AUI 不弹任何提示或允许拖放文件;若 AUI 行为与此不符,改用 `useAui` 检测附件 adapter 存在性,作为 `ComposerAddAttachment.disabled` 的另一来源。

---

## 6. UI 与守卫

| 入口 | caseId | 附件按钮 | 拖放 | 行为 |
|---|---|---|---|---|
| `/chat` 新建对话 | undefined | disabled | 无效 | 引导回案件列表 |
| `/chat/[id]?caseId=N` 案件分析 | N | enabled | enabled | 拖入即时上传 |
| 任何入口,上传中 | 任意 | enabled | enabled | `ComposerSendButton` 自动 disabled(读 `status.type === "running"`) |

无 caseId 的兜底:即使前端守卫失效,后端 `current_case_id > 0` 强约束会返回 422,adapter `add()` 翻成 `incomplete` 状态,用户能感知。

---

## 7. 错误处理

| 场景 | 后端 | 前端 |
|---|---|---|
| `caseId` 缺失 | 422 | 理论上 §6 守卫拦截;若发生,adapter `add()` 设 `incomplete` |
| 文件超大 | 422 | 同上,reason 用后端 detail |
| `duplicate_files` | 200 | `toast.warning` 提示被去重的名字,这些名字**不进** attachment.content;其余正常 |
| 401 token 过期 | 401 | `apiFetch` 现有 `redirectToLogin()` |
| 网络中断 | network error | adapter `add()` 翻 `incomplete` |
| OCR 异步 | 200 | 规范要求前端不感知,UI 仅显"已上传" |

不重试 — 失败就显式告知,让用户重拖。

---

## 8. 测试策略

仓库根 `pnpm test`(vitest)。新文件:

1. `lib/hooks/use-chat-upload.test.ts` — mock `apiFetch`;200/422 两条路径;FormData 字段断言
2. `lib/assistant-ui/chat-attachment-adapter.test.ts` — 成功、失败、`duplicate_files` toast、返回 attachment 形状
3. `lib/assistant-ui/sse.test.ts`(扩) — 已有测跑参数拼装;加 `uploadedFiles` 分支
4. `lib/assistant-ui/use-langgraph-runtime.test.ts`(扩) — `handleSend` 含 attachments → `runStream` body 含 `uploaded_files`;`handleReload` 从 `attachmentsRef` 取

不写 RTL 集成测试 — AUI 集成需挂 `AssistantRuntimeProvider`,仓库无此模式。`runStream` 与 `sse.ts` 已有 fetch 拦截,单元测覆盖已足。

不写 e2e(Playwright) — 仓库无此套件,加引入成本不合算。

---

## 9. 改动文件清单

新增:
- `lib/types/chat-upload.ts`
- `lib/hooks/use-chat-upload.ts`
- `lib/hooks/use-chat-upload.test.ts`
- `lib/assistant-ui/chat-attachment-adapter.ts`
- `lib/assistant-ui/chat-attachment-adapter.test.ts`

修改:
- `lib/assistant-ui/sse.ts` — `RunStreamRequest` 增 `uploadedFiles`;body `uploaded_files` 拼装
- `lib/assistant-ui/sse.test.ts` — 扩测
- `lib/assistant-ui/use-langgraph-runtime.ts` — `attachmentsRef`、`collectFileItems`、传 adapter
- `lib/assistant-ui/use-langgraph-runtime.test.ts` — 扩测
- `components/chat/assistant-chat.tsx` — 加 `attachmentAdapter` prop
- `components/chat/chatgpt-thread.tsx` — `ComposerAddAttachment` 加 `disabled`/`disabledReason`
- `app/(main)/chat/page.tsx` — 传 `attachmentAdapter = null`
- `app/(main)/chat/[id]/page.tsx` — 传 `attachmentAdapter = createChatAttachmentAdapter({...})`

---

## 10. 决策记录(回顾)

| 决策点 | 选定 | 备选 |
|---|---|---|
| 架构 | 浏览器直连 LangGraph | 重加 Next.js 代理(与 7e3de01 矛盾) |
| 上传时机 | 拖入即时上传 | 发送按钮触发 |
| 无 caseId 时 | 禁用附件按钮 + 拖放 | 弹案件选择器 |
| OCR 状态 | 前端不感知 | 后端补 ocr_pending 字段 |
| 去重粒度 | 每次拖入独立去重 | 会话级批次 |
| 附件列表送 invoke | AttachmentAdapter 走 content | 跳过 AUI 自管;扩展 message schema |
| 重发附件 | 重发仍带原件 | 重发不带 |
| 历史附件存储 | 前端持 `messageId→FileItem[]` ref | 后端补返 / 改 metadata |
| 集成方法 | 走 AUI AttachmentAdapter | 跳过 AUI 自管状态 |
| 集成路径 | 走 `lib/assistant-ui/` | 新建顶层模块 |
| 测试范围 | hook + adapter + sse + runtime 单测 | 加 RTL 集成 / e2e |

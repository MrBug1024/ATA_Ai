# 对话入口同步文件上传 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 chat composer 接入 LangGraph `/chat/upload-files` + `/chat/invoke uploaded_files`,支持拖入文件即时上传并随消息发送。

**Architecture:** 浏览器直连 LangGraph(不重建 Next.js 代理层 — 与 `7e3de01` 一致)。用 `@assistant-ui/react` 的 `AttachmentAdapter` 机制接管 `add()`,把后端 `FileItem` 塞进 `attachment.content[0].file_item`。`useExternalStoreRuntime` 的 `onNew` 从 message 收集 `FileItem[]`,塞进 `runStream` 的 `uploadedFiles`,转发到 `/chat/invoke.body.uploaded_files`。

**Tech Stack:** Next.js 16, React 19, TypeScript 5, `@assistant-ui/react@0.12.25`, vitest, sonner.

---

## 0. 范围与非目标

**在范围内**:
- 新增 `lib/types/chat-upload.ts`、`lib/hooks/use-chat-upload.ts`、`lib/assistant-ui/chat-attachment-adapter.ts`
- 改造 `lib/assistant-ui/sse.ts`、`lib/assistant-ui/use-langgraph-runtime.ts`
- 改造 `components/chat/assistant-chat.tsx`、`components/chat/chatgpt-thread.tsx`
- 改造 `app/(main)/chat/page.tsx`、`app/(main)/chat/[id]/page.tsx`
- 4 个测试文件

**不在范围内**:
- `lib/stores/upload-queue.ts`(服务 AddMaterialDialog 的 OCR 任务)
- `lib/hooks/use-upload-ingest.ts`(`/files/upload-and-ingest` 旧路径)
- `AddMaterialDialog`、`cases/page.tsx`(案件页同步上传入口)
- 后端 `POST /chat/upload-files`、`POST /chat/invoke` 改造
- AUI 库本身

**已知 UX 限制**(plan 不解决,后续单独 ticket):
- AUI `AttachmentAdapter.add()` 是 async,add 期间 Composer **不显示任何 spinner**(AUI 自身限制,见 spec §5.2)。add resolve 后 attachment 立刻变 `complete`。50MB 大文件拖入时,用户感知会是"卡一下后出现已上传条目"。这是 AUI 机制本身决定,非本 plan 可改。

---

## 1. 文件结构

| 文件 | 状态 | 职责 |
|---|---|---|
| `lib/types/chat-upload.ts` | 新 | `FileItem` / `ChatUploadResponse` / `ChatUploadRequest` |
| `lib/hooks/use-chat-upload.ts` | 新 | `useChatUpload()` 调 `POST /chat/upload-files` |
| `tests/unit/use-chat-upload.test.tsx` | 新 | hook 单测 |
| `lib/assistant-ui/chat-attachment-adapter.ts` | 新 | AUI `AttachmentAdapter` 实现 |
| `tests/unit/chat-attachment-adapter.test.ts` | 新 | adapter 单测 |
| `lib/assistant-ui/sse.ts` | 改 | `RunStreamRequest` 加 `uploadedFiles`,body 拼装 |
| `tests/unit/sse.test.ts` | 改 | 扩测 uploadedFiles |
| `lib/assistant-ui/use-langgraph-runtime.ts` | 改 | 接收 `attachmentAdapter`;`attachmentsRef`;`collectFileItems` |
| `tests/unit/use-langgraph-runtime.test.tsx` | 改 | 扩测 attachments 流向 |
| `components/chat/assistant-chat.tsx` | 改 | 接 `attachmentAdapter` prop |
| `components/chat/chatgpt-thread.tsx` | 改 | `ComposerAddAttachment` 支持 `disabled`/`disabledReason` |
| `app/(main)/chat/page.tsx` | 改 | 传 `attachmentAdapter = null` |
| `app/(main)/chat/[id]/page.tsx` | 改 | 传 `attachmentAdapter = createChatAttachmentAdapter(...)` |

---

## 2. 准备

### 任务 0: 跑基线测试,确认起点干净

**Files**: (无)

- [ ] **Step 1: 跑测试**

Run: `pnpm test`
Expected: 18 test files, 112 tests pass。

- [ ] **Step 2: 记录 baseline**

把输出贴到 commit message,作为"起点干净"证据。如已有 baseline,跳过。

---

## 3. 数据类型

### Task 1: 加 `lib/types/chat-upload.ts`

**Files**:
- Create: `lib/types/chat-upload.ts`

- [ ] **Step 1: 写文件**

完整内容(无注释,符合项目风格 — 既有 `lib/types/doc-categories.ts` 是 0 注释):

```ts
export interface FileItem {
  name: string;
  url: string;
  type: string;
  extension: string;
  content_type: string;
  content: string;
  doc_category: string;
  upload_batch_id: string;
  file_hash: string;
  file_size: number;
  content_ref: string;
  duplicate_of: string;
  storage_ref: string;
  storage_provider: string;
  storage_bucket: string;
  storage_key: string;
  storage_etag: string;
  storage_version: string;
}

export interface ChatUploadResponse {
  upload_batch_id: string;
  case_id: number;
  debtor_id: number;
  debtor_name: string;
  effective_debtor_name: string;
  file_count: number;
  duplicate_files: string[];
  files: FileItem[];
}

export interface ChatUploadRequest {
  caseId: number;
  debtorId?: number;
  debtorName?: string;
  docCategory?: string;
  batchName?: string;
  uploadBatchId?: string;
  operatorId?: string;
  operatorName?: string;
}
```

- [ ] **Step 2: 类型检查**

Run: `pnpm tsc --noEmit 2>&1 | head -20`
Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add lib/types/chat-upload.ts
git commit -m "feat(types): add FileItem / ChatUploadResponse / ChatUploadRequest for chat sync upload"
```

---

## 4. Hook: `useChatUpload`

### Task 2: 实现 `lib/hooks/use-chat-upload.ts` (TDD)

**Files**:
- Create: `lib/hooks/use-chat-upload.ts`
- Test: `tests/unit/use-chat-upload.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
// tests/unit/use-chat-upload.test.tsx
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useChatUpload } from "@/lib/hooks/use-chat-upload";

function jsonRes(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("useChatUpload", () => {
  it("成功: 200 返回 ChatUploadResponse", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonRes({
        upload_batch_id: "b1",
        case_id: 42,
        debtor_id: 0,
        debtor_name: "",
        effective_debtor_name: "",
        file_count: 1,
        duplicate_files: [],
        files: [
          {
            name: "a.pdf",
            url: "s3://...",
            type: "file",
            extension: ".pdf",
            content_type: "application/pdf",
            content: "",
            doc_category: "",
            upload_batch_id: "b1",
            file_hash: "h1",
            file_size: 100,
            content_ref: "",
            duplicate_of: "",
            storage_ref: "s3://bucket/k",
            storage_provider: "s3",
            storage_bucket: "bucket",
            storage_key: "k",
            storage_etag: "e",
            storage_version: "v",
          },
        ],
      })
    );

    const { result } = renderHook(() => useChatUpload());
    const resp = await result.current.upload(
      { caseId: 42 },
      [new File(["x"], "a.pdf")]
    );

    expect(resp.file_count).toBe(1);
    expect(resp.files[0].file_hash).toBe("h1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/chat/upload-files");
    expect((init as RequestInit).method).toBe("POST");
    const form = (init as RequestInit).body as FormData;
    expect(form.get("current_case_id")).toBe("42");
    expect(form.get("current_debtor_id")).toBe("0");
    expect(form.get("current_debtor_name")).toBe("");
    const files = form.getAll("files");
    expect(files).toHaveLength(1);
  });

  it("422 抛错使用 detail[0].msg", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonRes({ detail: [{ msg: "case_id 必填" }] }, 422)
    );
    const { result } = renderHook(() => useChatUpload());
    await expect(
      result.current.upload({ caseId: 0 }, [new File(["x"], "a.pdf")])
    ).rejects.toThrow("case_id 必填");
  });

  it("422 抛错使用 error 字段(老格式)", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes({ error: "上游拒绝" }, 422));
    const { result } = renderHook(() => useChatUpload());
    await expect(
      result.current.upload({ caseId: 1 }, [new File(["x"], "a.pdf")])
    ).rejects.toThrow("上游拒绝");
  });

  it("500 抛错使用默认文案", async () => {
    fetchMock.mockResolvedValueOnce(new Response("nope", { status: 500 }));
    const { result } = renderHook(() => useChatUpload());
    await expect(
      result.current.upload({ caseId: 1 }, [new File(["x"], "a.pdf")])
    ).rejects.toThrow("Chat upload failed: 500");
  });

  it("可选字段 debtorId/debtorName/docCategory/batchName 等会写入 FormData", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonRes({ upload_batch_id: "b1", case_id: 1, debtor_id: 0, debtor_name: "", effective_debtor_name: "", file_count: 0, duplicate_files: [], files: [] })
    );
    const { result } = renderHook(() => useChatUpload());
    await result.current.upload(
      {
        caseId: 1,
        debtorId: 7,
        debtorName: "张三",
        docCategory: "合同",
        batchName: "批次A",
        uploadBatchId: "b1",
        operatorId: "u1",
        operatorName: "操作员A",
      },
      []
    );
    const form = fetchMock.mock.calls[0][1]!.body as FormData;
    expect(form.get("current_debtor_id")).toBe("7");
    expect(form.get("current_debtor_name")).toBe("张三");
    expect(form.get("doc_category")).toBe("合同");
    expect(form.get("batch_name")).toBe("批次A");
    expect(form.get("upload_batch_id")).toBe("b1");
    expect(form.get("operator_id")).toBe("u1");
    expect(form.get("operator_name")).toBe("操作员A");
  });
});
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `pnpm test tests/unit/use-chat-upload.test.tsx`
Expected: FAIL — `@/lib/hooks/use-chat-upload` not found.

- [ ] **Step 3: 实现 hook**

```ts
// lib/hooks/use-chat-upload.ts
"use client";

import { useCallback } from "react";
import { apiFetch, langgraphUrl } from "@/lib/api/client";
import type { ChatUploadRequest, ChatUploadResponse } from "@/lib/types/chat-upload";

export function useChatUpload() {
  const upload = useCallback(
    async (req: ChatUploadRequest, files: File[]): Promise<ChatUploadResponse> => {
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

      const res = await apiFetch(langgraphUrl("/chat/upload-files"), {
        method: "POST",
        body: form,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const detail = Array.isArray(err.detail) ? err.detail[0]?.msg : undefined;
        const msg = detail || err.error || `Chat upload failed: ${res.status}`;
        throw new Error(msg);
      }

      return res.json() as Promise<ChatUploadResponse>;
    },
    []
  );

  return { upload };
}
```

- [ ] **Step 4: 跑测试,确认通过**

Run: `pnpm test tests/unit/use-chat-upload.test.tsx`
Expected: 5 tests pass.

- [ ] **Step 5: 类型检查**

Run: `pnpm tsc --noEmit 2>&1 | head -20`
Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add lib/hooks/use-chat-upload.ts tests/unit/use-chat-upload.test.tsx
git commit -m "feat(hook): add useChatUpload for POST /chat/upload-files"
```

---

## 5. AUI Adapter

### Task 3: 实现 `lib/assistant-ui/chat-attachment-adapter.ts` (TDD)

**Files**:
- Create: `lib/assistant-ui/chat-attachment-adapter.ts`
- Test: `tests/unit/chat-attachment-adapter.test.ts`

- [ ] **Step 1: 写失败测试**

```ts
// tests/unit/chat-attachment-adapter.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createChatAttachmentAdapter } from "@/lib/assistant-ui/chat-attachment-adapter";
import type { ChatUploadResponse } from "@/lib/types/chat-upload";

const toastWarning = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    warning: (...args: unknown[]) => toastWarning(...args),
    error: (...args: unknown[]) => toastWarning(...args),
  },
}));

const uploadMock = vi.fn();
beforeEach(() => {
  uploadMock.mockReset();
  toastWarning.mockReset();
});
afterEach(() => {
  vi.restoreAllMocks();
});

function fileItem(name: string, hash: string): ChatUploadResponse["files"][number] {
  return {
    name,
    url: `s3://x/${name}`,
    type: "file",
    extension: name.split(".").pop() ?? "",
    content_type: "application/pdf",
    content: "",
    doc_category: "",
    upload_batch_id: "b1",
    file_hash: hash,
    file_size: 10,
    content_ref: "",
    duplicate_of: "",
    storage_ref: `s3://x/${name}`,
    storage_provider: "s3",
    storage_bucket: "x",
    storage_key: name,
    storage_etag: "e",
    storage_version: "v",
  };
}

describe("createChatAttachmentAdapter", () => {
  const adapter = () => createChatAttachmentAdapter({ caseId: 1, upload: uploadMock });

  it("add 成功: 返回 complete attachment 含 file_item", async () => {
    uploadMock.mockResolvedValue({
      upload_batch_id: "b1",
      case_id: 1,
      debtor_id: 0,
      debtor_name: "",
      effective_debtor_name: "",
      file_count: 1,
      duplicate_files: [],
      files: [fileItem("a.pdf", "h1")],
    });
    const a = adapter();
    const att = await a.add({ file: new File(["x"], "a.pdf") });
    expect(att.status).toEqual({ type: "complete" });
    expect(att.type).toBe("file_item");
    expect((att as unknown as { name: string }).name).toBe("a.pdf");
    expect((att as unknown as { file_item: { file_hash: string } }).file_item.file_hash).toBe("h1");
  });

  it("add 失败: 返回 incomplete attachment 带 reason", async () => {
    uploadMock.mockRejectedValue(new Error("case_id 必填"));
    const a = adapter();
    const att = await a.add({ file: new File(["x"], "a.pdf") });
    expect(att.status).toEqual({ type: "incomplete", reason: "case_id 必填" });
  });

  it("add 抛非 Error 对象时用默认文案", async () => {
    uploadMock.mockRejectedValue("plain string");
    const a = adapter();
    const att = await a.add({ file: new File(["x"], "a.pdf") });
    expect(att.status).toEqual({ type: "incomplete", reason: "上传失败" });
  });

  it("重复文件: toast.warning 提示,且返回 incomplete", async () => {
    uploadMock.mockResolvedValue({
      upload_batch_id: "b1",
      case_id: 1,
      debtor_id: 0,
      debtor_name: "",
      effective_debtor_name: "",
      file_count: 0,
      duplicate_files: ["a.pdf"],
      files: [],
    });
    const a = adapter();
    const att = await a.add({ file: new File(["x"], "a.pdf") });
    expect(toastWarning).toHaveBeenCalledWith(expect.stringContaining("a.pdf"));
    expect(att.status).toEqual({ type: "incomplete", reason: "全部文件重复" });
  });

  it("accept 字段为 */*", () => {
    expect(adapter().accept).toBe("*/*");
  });

  it("remove / send 留空实现:不抛错", async () => {
    const a = adapter();
    await expect(a.remove({} as never)).resolves.toBeUndefined();
    await expect(a.send({} as never)).resolves.toBeUndefined();
  });

  it("调用 upload 时 caseId 透传", async () => {
    uploadMock.mockResolvedValue({
      upload_batch_id: "b1",
      case_id: 99,
      debtor_id: 0,
      debtor_name: "",
      effective_debtor_name: "",
      file_count: 0,
      duplicate_files: [],
      files: [],
    });
    const a = createChatAttachmentAdapter({ caseId: 99, upload: uploadMock });
    await a.add({ file: new File(["x"], "a.pdf") });
    expect(uploadMock).toHaveBeenCalledWith({ caseId: 99 }, expect.any(Array));
  });
});
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `pnpm test tests/unit/chat-attachment-adapter.test.ts`
Expected: FAIL — `@/lib/assistant-ui/chat-attachment-adapter` not found.

- [ ] **Step 3: 实现 adapter**

```ts
// lib/assistant-ui/chat-attachment-adapter.ts
import { toast } from "sonner";
import type { AttachmentAdapter } from "@assistant-ui/react";
import type { ChatUploadRequest, ChatUploadResponse } from "@/lib/types/chat-upload";

export interface ChatAttachmentAdapterDeps {
  caseId: number;
  upload: (req: ChatUploadRequest, files: File[]) => Promise<ChatUploadResponse>;
}

export interface ChatAttachment {
  id: string;
  type: "file_item";
  name: string;
  contentType: string;
  file: File;
  file_item?: import("@/lib/types/chat-upload").FileItem;
  status: { type: "complete" } | { type: "incomplete"; reason: string };
}

export function createChatAttachmentAdapter(deps: ChatAttachmentAdapterDeps): AttachmentAdapter {
  return {
    accept: "*/*",
    async add({ file }) {
      const id = crypto.randomUUID();
      try {
        const res = await deps.upload({ caseId: deps.caseId }, [file]);
        if (res.duplicate_files.length > 0) {
          toast.warning(`本批重复文件已忽略: ${res.duplicate_files.join(", ")}`);
        }
        const fileItems = res.files.filter((f) => !res.duplicate_files.includes(f.name));
        if (fileItems.length === 0) {
          return {
            id,
            type: "file_item",
            name: file.name,
            contentType: file.type,
            file,
            status: { type: "incomplete", reason: "全部文件重复" },
          };
        }
        const fi = fileItems[0];
        return {
          id: `${id}-${fi.file_hash}`,
          type: "file_item",
          name: fi.name,
          contentType: fi.content_type,
          file,
          file_item: fi,
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
    async remove() {},
    async send() {},
  };
}
```

- [ ] **Step 4: 跑测试,确认通过**

Run: `pnpm test tests/unit/chat-attachment-adapter.test.ts`
Expected: 7 tests pass.

- [ ] **Step 5: 类型检查**

Run: `pnpm tsc --noEmit 2>&1 | head -20`
Expected: 0 errors.(若 `AttachmentAdapter` 导入名或字段不匹配,按 AUI 实际导出调整)

- [ ] **Step 6: Commit**

```bash
git add lib/assistant-ui/chat-attachment-adapter.ts tests/unit/chat-attachment-adapter.test.ts
git commit -m "feat(aui): add ChatAttachmentAdapter wrapping POST /chat/upload-files"
```

---

## 6. SSE 集成

### Task 4: `lib/assistant-ui/sse.ts` — 接收 uploadedFiles

**Files**:
- Modify: `lib/assistant-ui/sse.ts`
- Test: `tests/unit/sse.test.ts`(扩)

- [ ] **Step 1: 写失败测试**

在 `tests/unit/sse.test.ts` 末尾的 `describe("runStream", ...)` 块内追加:

```ts
  it("uploadedFiles 被序列化到 body.uploaded_files", async () => {
    fetchMock.mockResolvedValue(sseResponseFrom([`event: done\ndata: {}\n\n`]));
    const { cb } = makeCallbacks();
    await runStream(
      {
        threadId: "t1",
        query: "q",
        uploadedFiles: [
          {
            name: "a.pdf",
            url: "s3://x/a.pdf",
            type: "file",
            extension: ".pdf",
            content_type: "application/pdf",
            content: "",
            doc_category: "",
            upload_batch_id: "b1",
            file_hash: "h1",
            file_size: 10,
            content_ref: "",
            duplicate_of: "",
            storage_ref: "s3://x/a.pdf",
            storage_provider: "s3",
            storage_bucket: "x",
            storage_key: "a.pdf",
            storage_etag: "e",
            storage_version: "v",
          },
        ],
      },
      cb,
      () => {},
      () => {},
      () => {}
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.uploaded_files).toHaveLength(1);
    expect(body.uploaded_files[0].file_hash).toBe("h1");
  });

  it("未传 uploadedFiles 时 body.uploaded_files = []", async () => {
    fetchMock.mockResolvedValue(sseResponseFrom([`event: done\ndata: {}\n\n`]));
    const { cb } = makeCallbacks();
    await runStream(
      { threadId: "t1", query: "q" },
      cb,
      () => {},
      () => {},
      () => {}
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.uploaded_files).toEqual([]);
  });
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `pnpm test tests/unit/sse.test.ts`
Expected: 2 new tests FAIL — uploaded_files 字段是 hardcoded `[]`(看 sse.ts:88)。

- [ ] **Step 3: 改 sse.ts**

修改 `lib/assistant-ui/sse.ts`:

替换 `RunStreamRequest` interface:
```ts
export interface RunStreamRequest {
  threadId: string;
  query: string;
  caseId?: number;
  uploadedFiles?: import("@/lib/types/chat-upload").FileItem[];
}
```

替换 body 拼装(原 `uploaded_files: []` 那一行):
```ts
      body: JSON.stringify({
        thread_id: request.threadId,
        query: request.query,
        current_case_id: request.caseId ?? 0,
        current_debtor_id: 0,
        current_debtor_name: "",
        stream: true,
        uploaded_files: request.uploadedFiles ?? [],
      }),
```

- [ ] **Step 4: 跑测试,确认通过**

Run: `pnpm test tests/unit/sse.test.ts`
Expected: 全部 pass(原 6 + 新 2)。

- [ ] **Step 5: 类型检查**

Run: `pnpm tsc --noEmit 2>&1 | head -20`
Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add lib/assistant-ui/sse.ts tests/unit/sse.test.ts
git commit -m "feat(sse): pass uploadedFiles through to /chat/invoke body"
```

---

## 7. Runtime 集成

### Task 5: `useLanggraphRuntime` — 接 attachmentAdapter + 收集 FileItems

**Files**:
- Modify: `lib/assistant-ui/use-langgraph-runtime.ts`
- Test: `tests/unit/use-langgraph-runtime.test.tsx`(扩)

- [ ] **Step 1: 写失败测试**

读 `tests/unit/use-langgraph-runtime.test.tsx` 完整后,在 describe 内追加 2 个测试:

```tsx
  it("onNew 含附件时把 file_item 传给 runStream", async () => {
    runStreamMock.mockImplementation(async (_req: unknown, cb: StreamCallbacks) => {
      cb.onAbortRef(() => {});
      cb.onReplace("ok");
    });
    renderHook(() => useLanggraphRuntime("t1", 42));
    await waitFor(() => expect(capturedConfig).toBeDefined());

    const fileItem = {
      name: "a.pdf",
      url: "s3://x/a.pdf",
      type: "file",
      extension: ".pdf",
      content_type: "application/pdf",
      content: "",
      doc_category: "",
      upload_batch_id: "b1",
      file_hash: "h1",
      file_size: 10,
      content_ref: "",
      duplicate_of: "",
      storage_ref: "s3://x/a.pdf",
      storage_provider: "s3",
      storage_bucket: "x",
      storage_key: "a.pdf",
      storage_etag: "e",
      storage_version: "v",
    };

    await act(async () => {
      await capturedConfig.onNew({
        content: "看这个文件",
        attachments: [
          {
            id: "att1",
            type: "file_item",
            name: "a.pdf",
            contentType: "application/pdf",
            content: [{ type: "file_item", file_item: fileItem }],
          },
        ],
      } as unknown as { content: string });
    });

    expect(runStreamMock.mock.calls[0][0]).toMatchObject({
      threadId: "t1",
      query: "看这个文件",
      caseId: 42,
      uploadedFiles: [fileItem],
    });
  });

  it("onReload 重发时用 parent 消息保存的附件", async () => {
    runStreamMock.mockImplementationOnce(async (_req: unknown, cb: StreamCallbacks) => {
      cb.onAbortRef(() => {});
      cb.onReplace("首次回答");
    });
    runStreamMock.mockImplementationOnce(async (_req: unknown, cb: StreamCallbacks) => {
      cb.onAbortRef(() => {});
      cb.onReplace("重发回答");
    });

    renderHook(() => useLanggraphRuntime("t1"));
    await waitFor(() => expect(capturedConfig).toBeDefined());

    const fileItem = {
      name: "x.pdf",
      url: "s3://x",
      type: "file",
      extension: ".pdf",
      content_type: "application/pdf",
      content: "",
      doc_category: "",
      upload_batch_id: "b1",
      file_hash: "h2",
      file_size: 1,
      content_ref: "",
      duplicate_of: "",
      storage_ref: "s3://x",
      storage_provider: "s3",
      storage_bucket: "x",
      storage_key: "k",
      storage_etag: "e",
      storage_version: "v",
    };

    await act(async () => {
      await capturedConfig.onNew({
        content: "原问题",
        attachments: [
          {
            id: "att2",
            type: "file_item",
            name: "x.pdf",
            contentType: "application/pdf",
            content: [{ type: "file_item", file_item: fileItem }],
          },
        ],
      } as unknown as { content: string });
    });

    const userMsg = capturedConfig.messages.find((m) => m.role === "user");
    expect(userMsg).toBeDefined();

    await act(async () => {
      await capturedConfig.onReload(userMsg!.id);
    });

    expect(runStreamMock).toHaveBeenCalledTimes(2);
    expect(runStreamMock.mock.calls[1][0]).toMatchObject({
      query: "原问题",
      uploadedFiles: [fileItem],
    });
  });
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `pnpm test tests/unit/use-langgraph-runtime.test.tsx`
Expected: 2 new tests FAIL — `runStream` 没接 `uploadedFiles`,且 onNew 不读 attachments。

- [ ] **Step 3: 改 runtime**

`lib/assistant-ui/use-langgraph-runtime.ts` 修改:

A) 在 import 后加 type import 与 helper:

```ts
import type { AttachmentAdapter } from "@assistant-ui/react";
import type { FileItem } from "@/lib/types/chat-upload";

interface FileItemContentEntry {
  type: "file_item";
  file_item: FileItem;
}

function collectFileItems(message: { attachments?: Array<{ content?: unknown[] }> }): FileItem[] {
  const out: FileItem[] = [];
  for (const att of message.attachments ?? []) {
    for (const c of att.content ?? []) {
      if (
        c &&
        typeof c === "object" &&
        (c as { type?: string }).type === "file_item" &&
        (c as { file_item?: unknown }).file_item
      ) {
        out.push((c as FileItemContentEntry).file_item);
      }
    }
  }
  return out;
}
```

B) 修改函数签名,接 `attachmentAdapter`:

```ts
export function useLanggraphRuntime(
  threadId: string,
  caseId?: number,
  initialMessages?: DbMessage[],
  attachmentAdapter?: AttachmentAdapter
) {
```

C) 加 `attachmentsRef`:

```ts
  const attachmentsRef = useRef<Map<string, FileItem[]>>(new Map());
```

D) `handleSend` 中:
- 在 `await runStream(...)` 之前:`const fileItems = collectFileItems(message as { attachments?: ... });` 然后 `attachmentsRef.current.set(streamMsgId, fileItems);`
- `runStream` 参数加 `uploadedFiles: fileItems`

E) `handleReload` 中:
- 在 `await runStream(...)` 之前:`const fileItems = attachmentsRef.current.get(parentId) ?? [];`
- `runStream` 参数加 `uploadedFiles: fileItems`

F) `useExternalStoreRuntime` 配置加 `adapters: { attachments: attachmentAdapter }`:

```ts
  const runtime = useExternalStoreRuntime<DbMessage>({
    isRunning: state.isRunning,
    messages: state.messages,
    onNew: handleSend,
    onCancel: handleCancel,
    onReload: handleReload,
    convertMessage: convertDbMessage,
    adapters: { attachments: attachmentAdapter },
  });
```

**注**: `AppendMessage` 的 `attachments` 字段是 AUI 私有 type,签名里的 `content: unknown[]` 是我们的临时契约;在 cast 段用 `as unknown as` 即可。

- [ ] **Step 4: 跑测试,确认通过**

Run: `pnpm test tests/unit/use-langgraph-runtime.test.tsx`
Expected: 全部 pass(原 7 + 新 2)。

- [ ] **Step 5: 类型检查**

Run: `pnpm tsc --noEmit 2>&1 | head -20`
Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add lib/assistant-ui/use-langgraph-runtime.ts tests/unit/use-langgraph-runtime.test.tsx
git commit -m "feat(runtime): pass attachmentAdapter + collect FileItems for /chat/invoke"
```

---

## 8. UI 接线

### Task 6: `AssistantChat` 接 `attachmentAdapter` prop

**Files**:
- Modify: `components/chat/assistant-chat.tsx`

- [ ] **Step 1: 改文件**

```tsx
// components/chat/assistant-chat.tsx
"use client";

import type { AttachmentAdapter } from "@assistant-ui/react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useLanggraphRuntime } from "@/lib/assistant-ui/use-langgraph-runtime";
import { ThinkingContext } from "@/lib/assistant-ui/thinking-context";
import { ChatThread } from "./chatgpt-thread";
import { SidebarTrigger } from "@/components/ui/sidebar";

export interface SerializableMessage {
  id: string;
  conversationId: string;
  role: "user" | "assistant";
  content: string;
  metadata: Record<string, unknown> | null;
  createdAt: string;
}

interface AssistantChatProps {
  threadId: string;
  caseId?: number;
  initialMessages?: SerializableMessage[];
  title?: string;
  attachmentAdapter?: AttachmentAdapter;
}

export function AssistantChat({
  threadId,
  caseId,
  initialMessages,
  title,
  attachmentAdapter,
}: AssistantChatProps) {
  const { runtime, thinkingMap } = useLanggraphRuntime(
    threadId,
    caseId,
    initialMessages,
    attachmentAdapter
  );

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThinkingContext.Provider value={thinkingMap}>
        <div className="flex h-full flex-col">
          <header className="flex h-14 shrink-0 items-center gap-2 px-4">
            <SidebarTrigger className="size-9 shrink-0 text-muted-foreground hover:bg-accent hover:text-foreground" />
            {title && (
              <span className="min-w-0 truncate text-sm text-foreground/70">
                {title}
              </span>
            )}
          </header>

          <div className="flex min-h-0 flex-1">
            <div className="min-w-0 flex-1 overflow-hidden">
              <ChatThread hasInitialMessages={!!initialMessages?.length} />
            </div>
          </div>
        </div>
      </ThinkingContext.Provider>
    </AssistantRuntimeProvider>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `pnpm tsc --noEmit 2>&1 | head -20`
Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add components/chat/assistant-chat.tsx
git commit -m "feat(chat): AssistantChat accepts attachmentAdapter prop"
```

---

### Task 7: `ComposerAddAttachment` 支持 `disabled`/`disabledReason`

**Files**:
- Modify: `components/assistant-ui/attachment.tsx`(只动 `ComposerAddAttachment` 那一段,约 lines 59-73)

- [ ] **Step 1: 改文件**

把 `components/assistant-ui/attachment.tsx` 的 `ComposerAddAttachment` 替换为:

```tsx
export function ComposerAddAttachment({
  className,
  disabled,
  disabledReason,
}: {
  className?: string;
  disabled?: boolean;
  disabledReason?: string;
}) {
  return (
    <ComposerPrimitive.AddAttachment asChild>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        disabled={disabled}
        title={disabled ? disabledReason : undefined}
        className={cn("size-8 shrink-0", className)}
      >
        <Paperclip className="size-4" />
        <span className="sr-only">{disabledReason ?? "Add attachment"}</span>
      </Button>
    </ComposerPrimitive.AddAttachment>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `pnpm tsc --noEmit 2>&1 | head -20`
Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add components/assistant-ui/attachment.tsx
git commit -m "feat(attachment): ComposerAddAttachment supports disabled/disabledReason"
```

---

### Task 8: `ChatThread` 透传 disabled 状态

**Files**:
- Modify: `components/chat/chatgpt-thread.tsx`

- [ ] **Step 1: 改 ChatThread 接口 + ComposerAction**

在 `components/chat/chatgpt-thread.tsx`:

A) `ChatThreadProps` 加 `caseId?: number` 与 `attachmentDisabledReason?: string` (无需传递 caseId,只透传 disabled 文案以保持 UI 简洁;不暴露 caseId 给 thread 是有意的):

```tsx
interface ChatThreadProps {
  suggestions?: string[];
  hasInitialMessages?: boolean;
  initialComposerValue?: string;
  attachmentDisabled?: boolean;
  attachmentDisabledReason?: string;
}
```

B) `ChatThread` 函数签名加这俩参数。

C) 在内部 `<ComposerAction attachmentDisabled={attachmentDisabled} attachmentDisabledReason={attachmentDisabledReason} />`,但因为 `ComposerAction` 当前不接 props,我们直接 inline:

把:
```tsx
const ComposerAction: FC = () => (
  <div className="relative mx-2 mb-2 flex items-center justify-between">
    <ComposerAddAttachment />
```

改为:
```tsx
const ComposerAction: FC<{
  attachmentDisabled?: boolean;
  attachmentDisabledReason?: string;
}> = ({ attachmentDisabled, attachmentDisabledReason }) => (
  <div className="relative mx-2 mb-2 flex items-center justify-between">
    <ComposerAddAttachment
      disabled={attachmentDisabled}
      disabledReason={attachmentDisabledReason}
    />
```

D) 在 ChatThread 内部把 `<ComposerAction />` 调用更新为传 props。

- [ ] **Step 2: 类型检查**

Run: `pnpm tsc --noEmit 2>&1 | head -20`
Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add components/chat/chatgpt-thread.tsx
git commit -m "feat(chat): ChatThread supports attachment disabled state"
```

---

## 9. 页面集成

### Task 9: `/chat` 页(无 caseId → 禁用附件)

**Files**:
- Modify: `app/(main)/chat/page.tsx`

- [ ] **Step 1: 改文件**

读 `app/(main)/chat/page.tsx` 全文。当前 `ChatPageClient` 走 `router.push(/chat/...)`,**没渲染 AssistantChat**;只在 chat detail 页才渲染。所以附件按钮其实是 detail 页的事。

但用户在 `/chat`(新对话)页 textarea 上也可能拖文件 — 该页 textarea 没用 AUI composer,没有附件能力,无影响。**真正影响的是 detail 页**。

我之前的 task 设计错了。**修正**: 本 task 不改 `/chat/page.tsx`,只改 `/chat/[id]/page.tsx`(Task 10)。

- [ ] **Step 1(revised): 跳过 — 该文件本 plan 不动**

- [ ] **Step 2: 跳到 Task 10**

把 Task 9 标为 deleted,只保留 Task 10。

---

### Task 10: `/chat/[id]` 页(有 caseId → 接 attachmentAdapter)

**Files**:
- Modify: `app/(main)/chat/[id]/page.tsx`

- [ ] **Step 1: 改文件**

```tsx
// app/(main)/chat/[id]/page.tsx
"use client";

import { use, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { AssistantChat, type SerializableMessage } from "@/components/chat/assistant-chat";
import { apiFetch, langgraphUrl } from "@/lib/api/client";
import { useChatUpload } from "@/lib/hooks/use-chat-upload";
import { createChatAttachmentAdapter } from "@/lib/assistant-ui/chat-attachment-adapter";

interface ChatDetailPageProps {
  params: Promise<{ id: string }>;
}

interface ThreadMessage {
  id: string;
  role: string;
  content: string;
  type?: string;
  name?: string;
}

interface ThreadMessagesResponse {
  thread_id: string;
  messages: ThreadMessage[];
  message_count: number;
}

export default function ChatDetailPage({ params }: ChatDetailPageProps) {
  const { id } = use(params);
  const searchParams = useSearchParams();
  const caseIdParam = searchParams.get("caseId");
  const caseId = caseIdParam ? Number(caseIdParam) : undefined;

  const [initialMessages, setInitialMessages] = useState<SerializableMessage[] | null>(null);

  const { upload } = useChatUpload();
  const attachmentAdapter = useMemo(() => {
    if (caseId == null) return undefined;
    return createChatAttachmentAdapter({ caseId, upload });
  }, [caseId, upload]);

  useEffect(() => {
    let cancelled = false;
    setInitialMessages(null);
    (async () => {
      try {
        const res = await apiFetch(
          langgraphUrl(`/chat/threads/${encodeURIComponent(id)}/messages`)
        );
        if (!res.ok) {
          if (!cancelled) setInitialMessages([]);
          return;
        }
        const data = (await res.json()) as ThreadMessagesResponse;
        const now = new Date().toISOString();
        const mapped: SerializableMessage[] = (data.messages ?? [])
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({
            id: m.id,
            conversationId: id,
            role: m.role as "user" | "assistant",
            content: m.content,
            metadata: null,
            createdAt: now,
          }));
        if (!cancelled) setInitialMessages(mapped);
      } catch {
        if (!cancelled) setInitialMessages([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (initialMessages === null) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="size-4 animate-spin text-muted-foreground/40" />
      </div>
    );
  }

  return (
    <AssistantChat
      key={id}
      threadId={id}
      caseId={caseId}
      initialMessages={initialMessages}
      attachmentAdapter={attachmentAdapter}
    />
  );
}
```

- [ ] **Step 2: 类型检查 + 全量测试**

Run:
```bash
pnpm tsc --noEmit 2>&1 | head -20
pnpm test
```
Expected: 0 type errors,所有 test files pass(应有 20+ 个测试文件,130+ 个测试)。

- [ ] **Step 3: Commit**

```bash
git add app/\(main\)/chat/\[id\]/page.tsx
git commit -m "feat(chat): wire attachment adapter on chat detail page (caseId required)"
```

---

## 10. 端到端冒烟(手动,非自动)

### Task 11: 手动冒烟脚本

无代码改动。执行步骤:

- [ ] **Step 1: 启动 dev server**

Run: `pnpm dev`
Expected: 启动在 `http://localhost:3000`。

- [ ] **Step 2: 走 /cases 列表,点 "AI 分析"**

URL 跳到 `/chat/{uuid}?caseId=N`。Composer 显示附件按钮(可点)。

- [ ] **Step 3: 拖入一个 PDF**

观察到:PDF 出现在 composer 附件区;按钮 / 拖放过程**没 spinner**(AUI 限制);后端日志看到 `POST /chat/upload-files`;附件条目显示 PDF 名。

- [ ] **Step 4: 拖入同名 PDF 第二次**

观察到:第 2 次 add 返 `incomplete`(全部重复),toast.warning 出现"本批重复文件已忽略: x.pdf"。

- [ ] **Step 5: 在 textarea 写一句问话,点发送**

观察到:后端日志看到 `POST /chat/invoke` body 含 `uploaded_files` 数组 1 项;SSE 事件正常;assistant 回答引用了 PDF 内容(若后端 OCR 已完成)。

- [ ] **Step 6: 在回答上点"重新生成"**

观察到:重发请求的 `uploaded_files` 仍含 PDF(从 ref 读出)。

- [ ] **Step 7: 走 /chat(新对话)页**

观察到:点击"AI 分析"按钮去不了该页 — `/chat` 是新对话入口,不会带 caseId,附件按钮 disabled(我们没在该页加 disabled — 该页根本没附件按钮,因为不是 AssistantChat)。

  **但用户从 /chat 直接发问 → 进 /chat/[id] 时没 caseId → 附件按钮 disabled 吗?** 走 /chat,textarea 没附件按钮,发问跳到 /chat/[id]?(要看 router.push 行为)。如果在 detail 页 caseId undefined 时附件按钮应 disabled,需在 AssistantChat 中读 caseId — 当前实现 caseId undefined 时 attachmentAdapter = undefined,AUI 无 adapter 时 ComposerAddAttachment **依然渲染**(无 caseId disable 信号)。**本次 plan 不解决**,见 §0 已知限制。spec §5.6 已记录。

---

## 11. 终检

- [ ] **Step 1: 全量测试**

Run: `pnpm test`
Expected: 全部 pass,无 fail。

- [ ] **Step 2: 类型检查**

Run: `pnpm tsc --noEmit`
Expected: 0 errors。

- [ ] **Step 3: build**

Run: `pnpm build`
Expected: 编译通过(若 AUI 私有 type 引发 strict 警告,在 task 5 的 cast 处用 `as unknown as` 已处理)。

- [ ] **Step 4: 提交 plan 文档**

```bash
git add docs/superpowers/plans/2026-06-05-chat-sync-upload.md
git commit -m "docs(plan): add implementation plan for chat sync upload"
```

---

## 12. 决策记录

| 决策 | 选定 | 备选 |
|---|---|---|
| Adapter API 字段 | `adapters.attachments`(复数,查 AUI 官方文档) | 误用 `attachment` 单数 |
| `add()` 返回 | 单个 attachment 对象 | 数组(AUI 文档确认) |
| 重复文件 UX | toast.warning + `incomplete` | 完全静默 |
| add 阶段状态 | 直接 `complete`(add 即上传) | `requires-action` 让 send 阶段再 complete |
| 重发附件来源 | `attachmentsRef` session 内 | 后端 `/chat/threads/{id}/messages` 返附件 |
| `/chat/page.tsx` 改动 | 不改(新对话页无附件按钮) | 加 placeholder UI |
| e2e 自动化 | 不做,仅手动冒烟 | Playwright |

---

## 13. 文件改动总览

**新文件 (5)**: `lib/types/chat-upload.ts`、`lib/hooks/use-chat-upload.ts`、`tests/unit/use-chat-upload.test.tsx`、`lib/assistant-ui/chat-attachment-adapter.ts`、`tests/unit/chat-attachment-adapter.test.ts`

**改文件 (7)**: `lib/assistant-ui/sse.ts`、`tests/unit/sse.test.ts`、`lib/assistant-ui/use-langgraph-runtime.ts`、`tests/unit/use-langgraph-runtime.test.tsx`、`components/chat/assistant-chat.tsx`、`components/assistant-ui/attachment.tsx`、`components/chat/chatgpt-thread.tsx`、`app/(main)/chat/[id]/page.tsx`

**未动文件 (1, plan 内删除 task 9)**: `app/(main)/chat/page.tsx`

**总 commit 数**: 9 + 1 doc commit

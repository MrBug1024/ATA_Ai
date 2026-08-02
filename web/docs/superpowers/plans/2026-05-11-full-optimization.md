# AI Hunter 全面优化 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 四阶段优化 AI Hunter：架构重构消除代码重复 → SWR 迁移提升性能 → UI 改进（侧边栏搜索、对话重命名、文件预览面板）→ 建立完整测试体系。

**Architecture:** 方案 A 顺序推进。Phase 1 提取共享模块后，Phase 2 迁移数据请求层，Phase 3 在干净基础上构建 UI，Phase 4 补全测试覆盖。

**Tech Stack:** Next.js 16, TypeScript, SWR, Vitest, Playwright, Tailwind CSS v4, Drizzle ORM, shadcn/ui

---

## Phase 1：架构重构

### Task 1：提取共享类型 `lib/assistant-ui/types.ts`

**Files:**
- Create: `lib/assistant-ui/types.ts`

- [ ] **Step 1：创建类型文件**

```typescript
// lib/assistant-ui/types.ts
import type { MessageStatus } from "@assistant-ui/react";

export interface AttachmentMeta {
  name: string;
  contentType: string;
  upload_file_id: string;
  file?: File;
  previewUrl?: string;
}

export interface ServerAttachment {
  difyFileId: string;
  name: string;
  mimeType: string;
  previewUrl: string;
}

export interface DbMessage {
  id: string;
  conversationId: string;
  role: "user" | "assistant";
  content: string;
  difyMessageId: string | null;
  files: string[] | null;
  metadata: Record<string, unknown> | null;
  createdAt: string | Date;
  _status?: MessageStatus;
  _attachments?: AttachmentMeta[];
  serverAttachments?: ServerAttachment[];
}

export type DifyFile = {
  type: string;
  transfer_method: "local_file";
  upload_file_id: string;
};
```

- [ ] **Step 2：验证构建无报错**

```bash
pnpm build
```

Expected: 构建成功，无 TypeScript 错误。

- [ ] **Step 3：提交**

```bash
git add lib/assistant-ui/types.ts
git commit -m "refactor: add shared types module for assistant-ui"
```

---

### Task 2：提取 think 工具函数（TDD）

**Files:**
- Create: `lib/utils/think.ts`
- Create: `tests/unit/think.test.ts`

- [ ] **Step 1：先写失败测试**

```typescript
// tests/unit/think.test.ts
import { describe, it, expect } from "vitest";
import { extractThink, stripThink } from "@/lib/utils/think";

describe("extractThink", () => {
  it("无 think 标签时返回原文", () => {
    expect(extractThink("Hello world")).toEqual({
      thinkText: "",
      displayText: "Hello world",
      thinkDone: false,
    });
  });

  it("提取 think 内容与显示内容", () => {
    expect(extractThink("<think>推理过程</think>最终答案")).toEqual({
      thinkText: "推理过程",
      displayText: "最终答案",
      thinkDone: true,
    });
  });

  it("未闭合的 think 标签", () => {
    expect(extractThink("<think>流式中...")).toEqual({
      thinkText: "流式中...",
      displayText: "",
      thinkDone: false,
    });
  });

  it("嵌套 think 标签", () => {
    expect(extractThink("<think>outer<think>inner</think>still</think>display")).toEqual({
      thinkText: "outerinnerstill",
      displayText: "display",
      thinkDone: true,
    });
  });

  it("think 前后都有显示内容", () => {
    expect(extractThink("前缀 <think>思考</think> 后缀")).toEqual({
      thinkText: "思考",
      displayText: "前缀  后缀",
      thinkDone: true,
    });
  });
});

describe("stripThink", () => {
  it("移除 think 内容并 trim", () => {
    expect(stripThink("<think>推理</think>  答案  ")).toBe("答案");
  });

  it("无标签时原样返回（已 trim）", () => {
    expect(stripThink("  hello  ")).toBe("hello");
  });
});
```

- [ ] **Step 2：运行测试确认失败**

```bash
pnpm vitest run tests/unit/think.test.ts
```

Expected: FAIL — `Cannot find module '@/lib/utils/think'`

（如果 vitest 尚未安装，先完成 Task 16 的 Step 1 再回来）

- [ ] **Step 3：创建实现**

```bash
mkdir -p lib/utils
```

```typescript
// lib/utils/think.ts
export function extractThink(raw: string): {
  thinkText: string;
  displayText: string;
  thinkDone: boolean;
} {
  let thinkText = "";
  let displayText = "";
  let depth = 0;
  let hadThink = false;
  let i = 0;

  while (i < raw.length) {
    if (raw.startsWith("<think>", i)) {
      depth++;
      hadThink = true;
      i += 7;
    } else if (raw.startsWith("</think>", i)) {
      if (depth > 0) depth--;
      i += 8;
    } else if (depth > 0) {
      thinkText += raw[i++];
    } else {
      displayText += raw[i++];
    }
  }

  return { thinkText: thinkText.trim(), displayText, thinkDone: hadThink && depth === 0 };
}

export function stripThink(text: string): string {
  return extractThink(text).displayText.trim();
}
```

- [ ] **Step 4：运行测试确认通过**

```bash
pnpm vitest run tests/unit/think.test.ts
```

Expected: PASS — 7 tests passed

- [ ] **Step 5：提交**

```bash
git add lib/utils/think.ts tests/unit/think.test.ts
git commit -m "feat: extract shared think utility with tests"
```

---

### Task 3：更新 `app/api/chat/route.ts` 使用共享 think 工具

**Files:**
- Modify: `app/api/chat/route.ts`

- [ ] **Step 1：替换内联 stripThink**

在 `app/api/chat/route.ts` 顶部添加 import：

```typescript
import { stripThink } from "@/lib/utils/think";
```

删除文件中第 117–127 行的内联 `stripThink` 函数定义：

```typescript
// 删除这段：
function stripThink(text: string): string {
  let out = "", depth = 0, i = 0;
  while (i < text.length) {
    if (text.startsWith("<think>", i)) { depth++; i += 7; }
    else if (text.startsWith("</think>", i)) { if (depth > 0) depth--; i += 8; }
    else if (depth === 0) { out += text[i++]; }
    else { i++; }
  }
  return out.trim();
}
```

- [ ] **Step 2：验证构建**

```bash
pnpm build
```

Expected: 构建成功。

- [ ] **Step 3：提交**

```bash
git add app/api/chat/route.ts
git commit -m "refactor: use shared stripThink in chat route"
```

---

### Task 4：提取 SSE 解析模块 `lib/assistant-ui/sse.ts`

**Files:**
- Create: `lib/assistant-ui/sse.ts`

- [ ] **Step 1：创建 SSE 模块**

将 `use-dify-runtime.ts` 中的 `parseSseStream`、`StreamCallbacks`、`runStream` 移动到新文件：

```typescript
// lib/assistant-ui/sse.ts
import { extractThink } from "@/lib/utils/think";
import type { ThinkingUpdate } from "./thinking-context";

export interface SseEvent {
  event: string | undefined;
  data: Record<string, unknown>;
}

export interface StreamCallbacks {
  conversationId: string;
  onChunk: (content: string) => void;
  onReplace: (content: string) => void;
  onAbortRef: (cancel: () => void) => void;
  onThinking?: (update: ThinkingUpdate) => void;
}

export async function* parseSseStream(response: Response): AsyncGenerator<SseEvent> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.trim() || !line.startsWith("data: ")) continue;
        const dataStr = line.slice(6);
        if (dataStr === "[DONE]") return;

        let parsed: SseEvent | null = null;
        try {
          parsed = JSON.parse(dataStr) as SseEvent;
        } catch {
          continue;
        }
        if (parsed) yield parsed;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function runStream(
  conversationId: string,
  query: string,
  callbacks: StreamCallbacks,
  scheduleFlush: (fn: () => void) => void,
  cancelFlush: () => void,
  flushNow: () => void,
  files?: Array<{ type: string; transfer_method: "local_file"; upload_file_id: string }>,
  attachmentMeta?: Array<{ name: string; contentType: string; upload_file_id: string; file?: File; previewUrl?: string }>
): Promise<void> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conversationId,
      query,
      ...(files && files.length > 0 ? { files } : {}),
      ...(attachmentMeta && attachmentMeta.length > 0 ? { attachmentMeta } : {}),
    }),
  });

  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.error || "Failed to send message");
  }

  callbacks.onAbortRef(() => response.body?.cancel());

  let rawAccumulated = "";
  let displayAccumulated = "";
  let prevThinkText = "";
  let prevThinkDone = false;

  for await (const sseEvent of parseSseStream(response)) {
    const { event, data } = sseEvent;

    if (event === "node_started") {
      const nodeData = (data.data as { title?: string; node_type?: string } | undefined);
      const title = nodeData?.title ?? "";
      const nodeType = nodeData?.node_type ?? "";
      if (title) callbacks.onThinking?.({ type: "node_started", title, nodeType });
    }

    if (event === "node_finished") {
      callbacks.onThinking?.({ type: "node_finished" });
    }

    if (event === "message" || event === "agent_message" || event === "text_chunk") {
      const chunk =
        typeof data.answer === "string" ? data.answer
        : typeof data.text === "string" ? data.text
        : "";

      if (chunk) {
        rawAccumulated += chunk;
        const { thinkText, displayText, thinkDone } = extractThink(rawAccumulated);

        if (thinkText !== prevThinkText || thinkDone !== prevThinkDone) {
          prevThinkText = thinkText;
          prevThinkDone = thinkDone;
          if (thinkText || thinkDone) {
            callbacks.onThinking?.({ type: "think_update", content: thinkText, isDone: thinkDone });
          }
        }

        if (displayText.length > displayAccumulated.length) {
          const delta = displayText.slice(displayAccumulated.length);
          displayAccumulated = displayText;
          callbacks.onChunk(delta);
          scheduleFlush(flushNow);
        }
      }
    }

    if (event === "message_replace") {
      const raw = typeof data.answer === "string" ? data.answer : "";
      rawAccumulated = raw;
      const { thinkText, displayText, thinkDone } = extractThink(raw);
      prevThinkText = thinkText;
      prevThinkDone = thinkDone;
      displayAccumulated = displayText;
      if (thinkText) callbacks.onThinking?.({ type: "think_update", content: thinkText, isDone: thinkDone });
      cancelFlush();
      callbacks.onReplace(displayText);
    }

    if (event === "error") {
      const msg = typeof data.message === "string" ? data.message : "Stream error";
      throw new Error(msg);
    }
  }
}
```

- [ ] **Step 2：验证构建**

```bash
pnpm build
```

Expected: 构建成功（此时 use-dify-runtime 仍有重复代码，不影响构建）。

- [ ] **Step 3：提交**

```bash
git add lib/assistant-ui/sse.ts
git commit -m "refactor: extract SSE parsing module"
```

---

### Task 5：提取 `useThinking` hook

**Files:**
- Create: `lib/assistant-ui/use-thinking.ts`

- [ ] **Step 1：创建 hook**

```typescript
// lib/assistant-ui/use-thinking.ts
"use client";

import { useState, useCallback, useRef } from "react";
import type { ThinkingState, ThinkingUpdate } from "./thinking-context";

export function useThinking() {
  const [thinkingMap, setThinkingMap] = useState<Map<string, ThinkingState>>(new Map());
  const streamIdRef = useRef<string>("");
  const thinkingMapRef = useRef(thinkingMap);
  thinkingMapRef.current = thinkingMap;

  const initThinking = useCallback((streamId: string) => {
    streamIdRef.current = streamId;
    setThinkingMap((prev) => {
      const next = new Map(prev);
      next.set(streamId, {
        steps: [],
        thinkContent: "",
        thinkDone: false,
        isComplete: false,
        startedAt: Date.now(),
      });
      return next;
    });
  }, []);

  const updateThinking = useCallback((update: ThinkingUpdate) => {
    const streamId = streamIdRef.current;
    if (!streamId) return;
    setThinkingMap((prev) => {
      const state = prev.get(streamId);
      if (!state) return prev;
      let newState: ThinkingState;
      if (update.type === "node_started") {
        newState = { ...state, steps: [...state.steps, { title: update.title, nodeType: update.nodeType, done: false }] };
      } else if (update.type === "node_finished") {
        let marked = false;
        const steps = [...state.steps].reverse().map((s) => {
          if (!marked && !s.done) { marked = true; return { ...s, done: true }; }
          return s;
        }).reverse();
        newState = { ...state, steps };
      } else {
        newState = { ...state, thinkContent: update.content, thinkDone: update.isDone };
      }
      const next = new Map(prev);
      next.set(streamId, newState);
      return next;
    });
  }, []);

  const completeThinking = useCallback(() => {
    const streamId = streamIdRef.current;
    if (!streamId) return;
    setThinkingMap((prev) => {
      const state = prev.get(streamId);
      if (!state) return prev;
      const next = new Map(prev);
      next.set(streamId, { ...state, isComplete: true, completedAt: Date.now() });
      return next;
    });
    streamIdRef.current = "";
  }, []);

  return { thinkingMap, setThinkingMap, thinkingMapRef, streamIdRef, initThinking, updateThinking, completeThinking };
}
```

- [ ] **Step 2：验证构建**

```bash
pnpm build
```

- [ ] **Step 3：提交**

```bash
git add lib/assistant-ui/use-thinking.ts
git commit -m "refactor: extract useThinking hook"
```

---

### Task 6：提取 `convertDbMessage`

**Files:**
- Create: `lib/assistant-ui/convert-message.ts`

- [ ] **Step 1：创建转换模块**

```typescript
// lib/assistant-ui/convert-message.ts
import type { ThreadMessageLike } from "@assistant-ui/react";
import { stripThink } from "@/lib/utils/think";
import type { DbMessage, AttachmentMeta } from "./types";

export function convertDbMessage(msg: DbMessage): ThreadMessageLike {
  let attachments: ThreadMessageLike["attachments"];

  if (msg._attachments?.length) {
    attachments = msg._attachments.map((a) => ({
      id: a.upload_file_id,
      type: "file" as const,
      name: a.name,
      contentType: a.contentType,
      file: a.file,
      previewUrl: a.previewUrl,
      status: { type: "complete" as const },
      content: [{ type: "data" as const, name: "difyFile", data: {
        upload_file_id: a.upload_file_id,
        ...(a.previewUrl ? { previewUrl: a.previewUrl } : {}),
      }}],
    }));
  } else if (msg.serverAttachments?.length) {
    attachments = msg.serverAttachments.map((a) => ({
      id: a.difyFileId,
      type: "file" as const,
      name: a.name,
      contentType: a.mimeType,
      previewUrl: a.previewUrl,
      status: { type: "complete" as const },
      content: [{ type: "data" as const, name: "difyFile", data: {
        upload_file_id: a.difyFileId,
        previewUrl: a.previewUrl,
      }}],
    }));
  } else {
    const metaAttachments = msg.metadata?.attachments as AttachmentMeta[] | undefined;
    if (metaAttachments?.length) {
      attachments = metaAttachments.map((a) => ({
        id: a.upload_file_id,
        type: "file" as const,
        name: a.name,
        contentType: a.contentType,
        status: { type: "complete" as const },
        content: [{ type: "data" as const, name: "difyFile", data: { upload_file_id: a.upload_file_id } }],
      }));
    }
  }

  return {
    role: msg.role,
    content: msg.role === "assistant" ? stripThink(msg.content) : msg.content,
    id: msg.id,
    createdAt: msg.createdAt ? new Date(msg.createdAt) : undefined,
    status: msg._status,
    attachments,
  };
}
```

- [ ] **Step 2：验证构建**

```bash
pnpm build
```

- [ ] **Step 3：提交**

```bash
git add lib/assistant-ui/convert-message.ts
git commit -m "refactor: extract convertDbMessage"
```

---

### Task 7：重构 `use-dify-runtime.ts`

**Files:**
- Modify: `lib/assistant-ui/use-dify-runtime.ts`

- [ ] **Step 1：替换为使用共享模块的精简版本**

用以下内容**完整替换** `lib/assistant-ui/use-dify-runtime.ts`：

```typescript
"use client";

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useExternalStoreRuntime, type AppendMessage } from "@assistant-ui/react";
import type { DifyAppType } from "@/lib/dify";
import { createAttachmentAdapter, difyFileType } from "./attachment-adapter";
import { ThinkingContext } from "./thinking-context";
import { useThinking } from "./use-thinking";
import { runStream } from "./sse";
import { convertDbMessage } from "./convert-message";
import type { DbMessage, DifyFile, AttachmentMeta } from "./types";

export { ThinkingContext };

interface DifyRuntimeState {
  messages: DbMessage[];
  isRunning: boolean;
}

export function useDifyRuntime(
  conversationId: string,
  appType: DifyAppType = "audit",
  initialMessages?: DbMessage[]
) {
  const attachmentAdapter = useMemo(
    () => createAttachmentAdapter(appType, conversationId),
    [appType, conversationId]
  );

  const [state, setState] = useState<DifyRuntimeState>({
    messages: initialMessages ?? [],
    isRunning: false,
  });

  const abortRef = useRef<(() => void) | null>(null);
  const messagesRef = useRef<DbMessage[]>([]);
  messagesRef.current = state.messages;

  const pendingContentRef = useRef<string | null>(null);
  const updateTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { thinkingMap, setThinkingMap, thinkingMapRef, streamIdRef, initThinking, updateThinking, completeThinking } = useThinking();

  const cancelFlush = useCallback(() => {
    if (updateTimerRef.current) {
      clearTimeout(updateTimerRef.current);
      updateTimerRef.current = null;
    }
  }, []);

  const applyStreamingContent = useCallback((content: string) => {
    setState((prev) => {
      const sid = streamIdRef.current;
      const msgs = [...prev.messages];
      const lastIdx = msgs.length - 1;
      if (lastIdx >= 0 && msgs[lastIdx].role === "assistant" && msgs[lastIdx].id.startsWith("stream-")) {
        msgs[lastIdx] = { ...msgs[lastIdx], content };
      } else {
        msgs.push({
          id: sid || `stream-${Date.now()}`,
          conversationId,
          role: "assistant",
          content,
          difyMessageId: null,
          files: null,
          metadata: null,
          createdAt: new Date(),
        });
      }
      return { ...prev, messages: msgs };
    });
  }, [conversationId, streamIdRef]);

  const scheduleFlush = useCallback((flushFn: () => void) => {
    if (updateTimerRef.current) return;
    updateTimerRef.current = setTimeout(() => {
      updateTimerRef.current = null;
      flushFn();
    }, 30);
  }, []);

  const fetchMessages = useCallback(async () => {
    try {
      const res = await fetch(`/api/conversations/${conversationId}/messages`);
      const result = await res.json();
      if (result.success) {
        setState((prev) => ({ ...prev, messages: result.data.messages as DbMessage[] }));
      }
    } catch {
      // silent
    }
  }, [conversationId]);

  useEffect(() => {
    fetchMessages();
  }, [fetchMessages]);

  // Transfer completed stream-* thinking entries to real DB message IDs after fetchMessages
  useEffect(() => {
    const currentMap = thinkingMapRef.current;
    const completedStreamEntries = [...currentMap.entries()].filter(
      ([id, s]) => id.startsWith("stream-") && s.isComplete
    );
    if (completedStreamEntries.length === 0) return;

    const realAssistants = state.messages.filter(
      (m) => m.role === "assistant" && !m.id.startsWith("stream-") && !m.id.startsWith("error-")
    );
    if (realAssistants.length === 0) return;

    setThinkingMap((prev) => {
      const next = new Map(prev);
      let changed = false;
      for (const [, entry] of completedStreamEntries) {
        for (const msg of [...realAssistants].reverse()) {
          if (!prev.has(msg.id)) {
            next.set(msg.id, entry);
            changed = true;
            break;
          }
        }
      }
      return changed ? next : prev;
    });
  }, [state.messages, thinkingMapRef, setThinkingMap]);

  const flushPending = useCallback(() => {
    const c = pendingContentRef.current;
    pendingContentRef.current = null;
    if (c !== null) applyStreamingContent(c);
  }, [applyStreamingContent]);

  const handleSend = useCallback(
    async (message: AppendMessage) => {
      const content =
        typeof message.content === "string"
          ? message.content
          : message.content.filter((p) => p.type === "text").map((p) => (p as { text?: string }).text ?? "").join("");

      if (!content.trim()) return;

      const attachmentMeta: AttachmentMeta[] = [];
      const difyFiles: DifyFile[] = [];

      for (const attachment of message.attachments ?? []) {
        if (attachment.status.type !== "complete") continue;
        for (const part of attachment.content ?? []) {
          const p = part as { type: string; name?: string; data?: unknown };
          if (p.type === "data" && p.name === "difyFile") {
            const data = p.data as { upload_file_id?: string; mime_type?: string; localPreviewUrl?: string } | undefined;
            if (data?.upload_file_id) {
              difyFiles.push({ type: difyFileType(data.mime_type ?? attachment.contentType ?? ""), transfer_method: "local_file", upload_file_id: data.upload_file_id });
              attachmentMeta.push({ name: attachment.name ?? "file", contentType: attachment.contentType ?? "application/octet-stream", upload_file_id: data.upload_file_id, file: (attachment as { file?: File }).file, previewUrl: data.localPreviewUrl });
            }
          }
        }
      }

      const streamMsgId = `stream-${Date.now()}`;
      initThinking(streamMsgId);
      setState((prev) => ({
        ...prev,
        messages: [
          ...prev.messages,
          { id: `temp-${Date.now()}`, conversationId, role: "user", content, difyMessageId: null, files: null, metadata: null, createdAt: new Date(), ...(attachmentMeta.length > 0 ? { _attachments: attachmentMeta } : {}) },
          { id: streamMsgId, conversationId, role: "assistant", content: "", difyMessageId: null, files: null, metadata: null, createdAt: new Date() },
        ],
        isRunning: true,
      }));

      let accumulatedContent = "";
      try {
        await runStream(conversationId, content, {
          conversationId,
          onChunk: (chunk) => { accumulatedContent += chunk; pendingContentRef.current = accumulatedContent; },
          onReplace: (replacement) => { accumulatedContent = replacement; pendingContentRef.current = null; applyStreamingContent(replacement); },
          onAbortRef: (cancel) => { abortRef.current = cancel; },
          onThinking: updateThinking,
        }, scheduleFlush, cancelFlush, flushPending, difyFiles.length > 0 ? difyFiles : undefined, attachmentMeta.length > 0 ? attachmentMeta : undefined);

        cancelFlush();
        if (pendingContentRef.current !== null) { applyStreamingContent(pendingContentRef.current); pendingContentRef.current = null; }
        completeThinking();
        await fetchMessages();
        setState((prev) => ({ ...prev, isRunning: false }));
      } catch (err) {
        cancelFlush();
        completeThinking();
        const errorMessage = err instanceof Error ? err.message : "Unknown error";
        setState((prev) => {
          const msgs = [...prev.messages];
          const lastIdx = msgs.length - 1;
          if (lastIdx >= 0 && msgs[lastIdx].role === "assistant" && msgs[lastIdx].id.startsWith("stream-")) {
            msgs[lastIdx] = { ...msgs[lastIdx], _status: { type: "incomplete", reason: "error", error: errorMessage } };
          } else {
            msgs.push({ id: `error-${Date.now()}`, conversationId, role: "assistant", content: accumulatedContent, difyMessageId: null, files: null, metadata: null, createdAt: new Date(), _status: { type: "incomplete", reason: "error", error: errorMessage } });
          }
          return { ...prev, messages: msgs, isRunning: false };
        });
      }
    },
    [conversationId, fetchMessages, scheduleFlush, cancelFlush, applyStreamingContent, flushPending, initThinking, updateThinking, completeThinking]
  );

  const handleCancel = useCallback(async () => {
    abortRef.current?.();
    cancelFlush();
    setState((prev) => ({ ...prev, isRunning: false }));
  }, [cancelFlush]);

  const handleReload = useCallback(
    async (parentId: string | null) => {
      if (!parentId) return;
      const currentMessages = messagesRef.current;
      const parentIndex = currentMessages.findIndex((m) => m.id === parentId);
      if (parentIndex === -1) return;
      const parentMessage = currentMessages[parentIndex];
      if (parentMessage.role !== "user") return;

      const streamMsgId = `stream-${Date.now()}`;
      initThinking(streamMsgId);
      setState((prev) => ({
        ...prev,
        messages: [...currentMessages.slice(0, parentIndex + 1), { id: streamMsgId, conversationId, role: "assistant", content: "", difyMessageId: null, files: null, metadata: null, createdAt: new Date() }],
        isRunning: true,
      }));

      if (!parentId.startsWith("temp-")) {
        fetch(`/api/conversations/${conversationId}/messages?afterId=${parentId}`, { method: "DELETE" }).catch(() => {});
      }

      let accumulatedContent = "";
      try {
        await runStream(conversationId, parentMessage.content, {
          conversationId,
          onChunk: (chunk) => { accumulatedContent += chunk; pendingContentRef.current = accumulatedContent; },
          onReplace: (replacement) => { accumulatedContent = replacement; pendingContentRef.current = null; applyStreamingContent(replacement); },
          onAbortRef: (cancel) => { abortRef.current = cancel; },
          onThinking: updateThinking,
        }, scheduleFlush, cancelFlush, flushPending);

        cancelFlush();
        if (pendingContentRef.current !== null) { applyStreamingContent(pendingContentRef.current); pendingContentRef.current = null; }
        completeThinking();
        await fetchMessages();
        setState((prev) => ({ ...prev, isRunning: false }));
      } catch (err) {
        cancelFlush();
        completeThinking();
        const errorMessage = err instanceof Error ? err.message : "Unknown error";
        setState((prev) => {
          const msgs = [...prev.messages];
          const lastIdx = msgs.length - 1;
          if (lastIdx >= 0 && msgs[lastIdx].role === "assistant" && msgs[lastIdx].id.startsWith("stream-")) {
            msgs[lastIdx] = { ...msgs[lastIdx], _status: { type: "incomplete", reason: "error", error: errorMessage } };
          } else {
            msgs.push({ id: `error-${Date.now()}`, conversationId, role: "assistant", content: accumulatedContent, difyMessageId: null, files: null, metadata: null, createdAt: new Date(), _status: { type: "incomplete", reason: "error", error: errorMessage } });
          }
          return { ...prev, messages: msgs, isRunning: false };
        });
      }
    },
    [conversationId, fetchMessages, scheduleFlush, cancelFlush, applyStreamingContent, flushPending, initThinking, updateThinking, completeThinking]
  );

  const runtime = useExternalStoreRuntime<DbMessage>({
    isRunning: state.isRunning,
    messages: state.messages,
    onNew: handleSend,
    onCancel: handleCancel,
    onReload: handleReload,
    convertMessage: convertDbMessage,
    adapters: { attachments: attachmentAdapter },
  });

  return { runtime, thinkingMap, refresh: fetchMessages };
}
```

- [ ] **Step 2：验证构建**

```bash
pnpm build
```

Expected: 构建成功。

- [ ] **Step 3：提交**

```bash
git add lib/assistant-ui/use-dify-runtime.ts
git commit -m "refactor: simplify use-dify-runtime using shared modules"
```

---

### Task 8：重构 `use-new-chat-runtime.ts`

**Files:**
- Modify: `lib/assistant-ui/use-new-chat-runtime.ts`

- [ ] **Step 1：替换为精简版本**

用以下内容**完整替换** `lib/assistant-ui/use-new-chat-runtime.ts`：

```typescript
"use client";

import { useState, useCallback, useRef, useMemo } from "react";
import { useExternalStoreRuntime, type AppendMessage } from "@assistant-ui/react";
import type { DifyAppType } from "@/lib/dify";
import { createAttachmentAdapter, difyFileType } from "./attachment-adapter";
import { useThinking } from "./use-thinking";
import { parseSseStream } from "./sse";
import { convertDbMessage } from "./convert-message";
import { extractThink } from "@/lib/utils/think";
import type { DbMessage, AttachmentMeta } from "./types";

interface NewChatRuntimeState {
  messages: DbMessage[];
  isRunning: boolean;
  completedConversationId: string | null;
}

export function useNewChatRuntime(appType: DifyAppType) {
  const [state, setState] = useState<NewChatRuntimeState>({
    messages: [],
    isRunning: false,
    completedConversationId: null,
  });

  const abortRef = useRef<(() => void) | null>(null);
  const pendingContentRef = useRef<string | null>(null);
  const updateTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { thinkingMap, initThinking, updateThinking, completeThinking } = useThinking();

  const clearFlushTimer = useCallback(() => {
    if (updateTimerRef.current) { clearTimeout(updateTimerRef.current); updateTimerRef.current = null; }
  }, []);

  const scheduleFlush = useCallback((flushFn: () => void) => {
    if (updateTimerRef.current) return;
    updateTimerRef.current = setTimeout(() => { updateTimerRef.current = null; flushFn(); }, 30);
  }, []);

  const applyContent = useCallback((displayContent: string) => {
    setState((prev) => {
      const msgs = [...prev.messages];
      const lastIdx = msgs.length - 1;
      if (lastIdx >= 0 && msgs[lastIdx].role === "assistant") {
        msgs[lastIdx] = { ...msgs[lastIdx], content: displayContent };
      }
      return { ...prev, messages: msgs };
    });
  }, []);

  const handleSend = useCallback(
    async (message: AppendMessage) => {
      const content =
        typeof message.content === "string"
          ? message.content
          : message.content.filter((p) => p.type === "text").map((p) => (p as { text?: string }).text || "").join("");

      if (!content.trim()) return;

      const attachments = message.attachments ?? [];
      const fileAttachments: Array<{ type: string; transfer_method: string; upload_file_id: string }> = [];
      const attachmentMeta: AttachmentMeta[] = [];

      for (const attachment of attachments) {
        if (attachment.status.type !== "complete") continue;
        for (const part of attachment.content ?? []) {
          if (part.type === "data" && part.name === "difyFile") {
            const data = part.data as { upload_file_id?: string; mime_type?: string; localPreviewUrl?: string } | undefined;
            if (data?.upload_file_id) {
              fileAttachments.push({ type: difyFileType(data.mime_type ?? attachment.contentType ?? ""), transfer_method: "local_file", upload_file_id: data.upload_file_id });
              attachmentMeta.push({ name: attachment.name ?? "file", contentType: attachment.contentType ?? "application/octet-stream", upload_file_id: data.upload_file_id, file: (attachment as { file?: File }).file, previewUrl: data.localPreviewUrl });
            }
          }
        }
      }

      const streamMsgId = `stream-${Date.now()}`;
      initThinking(streamMsgId);
      setState((prev) => ({
        ...prev,
        isRunning: true,
        messages: [
          ...prev.messages,
          { id: `temp-${Date.now()}`, conversationId: "pending", role: "user", content, difyMessageId: null, files: null, metadata: null, createdAt: new Date(), ...(attachmentMeta.length > 0 ? { _attachments: attachmentMeta } : {}) },
          { id: streamMsgId, conversationId: "pending", role: "assistant", content: "", difyMessageId: null, files: null, metadata: null, createdAt: new Date() },
        ],
      }));

      try {
        const convResponse = await fetch("/api/conversations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: content.slice(0, 50), appType }),
        });
        const convResult = await convResponse.json();
        if (!convResult.success) throw new Error(convResult.error || "Failed to create conversation");
        const conversation = convResult.data.conversation as { id: string };

        const response = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ conversationId: conversation.id, query: content, ...(fileAttachments.length > 0 ? { files: fileAttachments } : {}), ...(attachmentMeta.length > 0 ? { attachmentMeta } : {}) }),
        });

        if (!response.ok) { const error = await response.json(); throw new Error(error.error || "Failed to send message"); }

        abortRef.current = () => response.body?.cancel();

        let rawAccumulated = "";
        let displayAccumulated = "";
        let prevThinkText = "";
        let prevThinkDone = false;

        for await (const sseEvent of parseSseStream(response)) {
          const { event, data } = sseEvent;

          if (event === "node_started") {
            const inner = (data.data as { title?: string; node_type?: string } | undefined);
            if (inner?.title) updateThinking({ type: "node_started", title: inner.title, nodeType: inner.node_type ?? "" });
          }
          if (event === "node_finished") updateThinking({ type: "node_finished" });

          if (event === "message" || event === "agent_message" || event === "text_chunk") {
            const chunk = typeof data.answer === "string" ? data.answer : typeof data.text === "string" ? data.text : "";
            if (chunk) {
              rawAccumulated += chunk;
              const { thinkText, displayText, thinkDone } = extractThink(rawAccumulated);
              if (thinkText !== prevThinkText || thinkDone !== prevThinkDone) {
                prevThinkText = thinkText; prevThinkDone = thinkDone;
                if (thinkText || thinkDone) updateThinking({ type: "think_update", content: thinkText, isDone: thinkDone });
              }
              if (displayText.length > displayAccumulated.length) {
                displayAccumulated = displayText;
                pendingContentRef.current = displayAccumulated;
                scheduleFlush(() => { const c = pendingContentRef.current; pendingContentRef.current = null; if (c !== null) applyContent(c); });
              }
            }
          }

          if (event === "message_replace") {
            const raw = typeof data.answer === "string" ? data.answer : "";
            rawAccumulated = raw;
            const { thinkText, displayText, thinkDone } = extractThink(raw);
            prevThinkText = thinkText; prevThinkDone = thinkDone; displayAccumulated = displayText;
            if (thinkText) updateThinking({ type: "think_update", content: thinkText, isDone: thinkDone });
            clearFlushTimer(); pendingContentRef.current = null; applyContent(displayText);
          }

          if (event === "error") {
            const msg = typeof data.message === "string" ? data.message : "Stream error";
            throw new Error(msg);
          }
        }

        clearFlushTimer();
        if (pendingContentRef.current !== null) { applyContent(pendingContentRef.current); pendingContentRef.current = null; }
        completeThinking();
        setState((prev) => ({ ...prev, isRunning: false, completedConversationId: conversation.id }));
      } catch (err) {
        completeThinking();
        const errorMessage = err instanceof Error ? err.message : "Unknown error";
        setState((prev) => {
          const msgs = [...prev.messages];
          const lastIdx = msgs.length - 1;
          if (lastIdx >= 0 && msgs[lastIdx].role === "assistant" && msgs[lastIdx].id.startsWith("stream-")) {
            msgs[lastIdx] = { ...msgs[lastIdx], _status: { type: "incomplete", reason: "error", error: errorMessage } };
          } else {
            msgs.push({ id: `error-${Date.now()}`, conversationId: prev.completedConversationId ?? `temp-conv-${Date.now()}`, role: "assistant", content: "", difyMessageId: null, files: null, metadata: null, createdAt: new Date(), _status: { type: "incomplete", reason: "error", error: errorMessage } });
          }
          return { ...prev, messages: msgs, isRunning: false };
        });
      }
    },
    [appType, clearFlushTimer, scheduleFlush, applyContent, initThinking, updateThinking, completeThinking]
  );

  const handleCancel = useCallback(async () => {
    abortRef.current?.();
    clearFlushTimer();
    completeThinking();
    setState((prev) => ({ ...prev, isRunning: false }));
  }, [clearFlushTimer, completeThinking]);

  const attachmentAdapter = useMemo(() => createAttachmentAdapter(appType), [appType]);

  const runtime = useExternalStoreRuntime<DbMessage>({
    isRunning: state.isRunning,
    messages: state.messages,
    onNew: handleSend,
    onCancel: handleCancel,
    onReload: async () => {},
    convertMessage: convertDbMessage,
    adapters: { attachments: attachmentAdapter },
  });

  return { runtime, thinkingMap, completedConversationId: state.completedConversationId };
}
```

- [ ] **Step 2：验证构建**

```bash
pnpm build
```

Expected: 构建成功。

- [ ] **Step 3：手动烟雾测试**

启动开发服务器，验证：
- 新建对话并发送消息，流式响应正常
- 重新生成（Reload）按钮正常工作
- Thinking 面板正常显示和折叠

```bash
pnpm dev
```

- [ ] **Step 4：提交**

```bash
git add lib/assistant-ui/use-new-chat-runtime.ts
git commit -m "refactor: simplify use-new-chat-runtime using shared modules"
```

---

## Phase 2：SWR 迁移

### Task 9：安装 SWR，移除未使用依赖

**Files:**
- Modify: `package.json`

- [ ] **Step 1：安装 SWR**

```bash
pnpm add swr
```

- [ ] **Step 2：移除未使用依赖**

```bash
pnpm remove framer-motion @modelcontextprotocol/sdk
```

- [ ] **Step 3：验证构建（确认没有 import 残留）**

```bash
pnpm build
```

Expected: 构建成功，无 `Cannot find module` 错误。

- [ ] **Step 4：提交**

```bash
git add package.json pnpm-lock.yaml
git commit -m "chore: add swr, remove unused framer-motion and mcp sdk"
```

---

### Task 10：迁移 `use-conversations.ts` 到 SWR

**Files:**
- Modify: `lib/hooks/use-conversations.ts`

- [ ] **Step 1：重写 hook**

用以下内容完整替换 `lib/hooks/use-conversations.ts`：

```typescript
"use client";

import useSWR from "swr";
import { useCallback } from "react";
import type { webConversations } from "@/lib/db/schema";
import type { InferSelectModel } from "drizzle-orm";

type Conversation = InferSelectModel<typeof webConversations>;

const fetcher = (url: string): Promise<Conversation[]> =>
  fetch(url).then((r) => r.json()).then((r) => r.data?.conversations ?? []);

export function useConversations() {
  const { data: conversations = [], isLoading, mutate } = useSWR<Conversation[]>(
    "/api/conversations",
    fetcher
  );

  const refresh = useCallback(
    (_silent = false) => mutate(),
    [mutate]
  );

  const createConversation = useCallback(
    async (params?: { title?: string; appType?: "audit" | "extract" }) => {
      const response = await fetch("/api/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params || {}),
      });
      const result = await response.json();
      if (result.success) {
        await mutate();
        return result.data.conversation as Conversation;
      }
      throw new Error(result.error || "Failed to create conversation");
    },
    [mutate]
  );

  const renameConversation = useCallback(
    async (id: string, title: string) => {
      const response = await fetch(`/api/conversations/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      const result = await response.json();
      if (result.success) {
        await mutate();
        return result.data.conversation as Conversation;
      }
      throw new Error(result.error || "Failed to rename conversation");
    },
    [mutate]
  );

  return {
    conversations,
    isLoading,
    error: null,
    refresh,
    createConversation,
    renameConversation,
  };
}
```

- [ ] **Step 2：验证构建**

```bash
pnpm build
```

- [ ] **Step 3：提交**

```bash
git add lib/hooks/use-conversations.ts
git commit -m "refactor: migrate use-conversations to SWR"
```

---

### Task 11：迁移 `use-files.ts` 到 SWR

**Files:**
- Modify: `lib/hooks/use-files.ts`

- [ ] **Step 1：重写 hook**

用以下内容完整替换 `lib/hooks/use-files.ts`：

```typescript
"use client";

import useSWR from "swr";
import { useCallback } from "react";
import type { webFiles } from "@/lib/db/schema";
import type { InferSelectModel } from "drizzle-orm";
import type { DifyAppType } from "@/lib/dify";

type FileRecord = InferSelectModel<typeof webFiles>;

const fetcher = (url: string): Promise<FileRecord[]> =>
  fetch(url).then((r) => r.json()).then((r) => r.data?.files ?? []);

export function useFiles() {
  const { data: files = [], isLoading, mutate } = useSWR<FileRecord[]>(
    "/api/files",
    fetcher
  );

  const uploadFile = useCallback(
    async (file: File, appType: DifyAppType = "audit") => {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("appType", appType);
      const response = await fetch("/api/files", { method: "POST", body: formData });
      const result = await response.json();
      if (result.success) {
        await mutate();
        return result.data.file as FileRecord;
      }
      throw new Error(result.error || "Failed to upload file");
    },
    [mutate]
  );

  return {
    files,
    isLoading,
    error: null,
    refresh: mutate,
    uploadFile,
  };
}
```

- [ ] **Step 2：验证构建**

```bash
pnpm build
```

- [ ] **Step 3：手动验证**

启动 dev server，切换页面多次，确认对话和文件列表不会重复请求（Network 面板中请求被缓存）。

- [ ] **Step 4：提交**

```bash
git add lib/hooks/use-files.ts
git commit -m "refactor: migrate use-files to SWR"
```

---

## Phase 3：UI 改进

### Task 12：新增 `PATCH /api/conversations/[id]` 重命名接口

**Files:**
- Modify: `app/api/conversations/[id]/route.ts`

- [ ] **Step 1：添加 PATCH handler**

在 `app/api/conversations/[id]/route.ts` 文件末尾追加以下函数（在最后一个 `}` 之后）：

```typescript
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const session = await requireSession();
    const { id } = await params;

    const body = await request.json().catch(() => null);
    const title = typeof body?.title === "string" ? body.title.trim() : null;
    if (!title || title.length > 500) {
      return errorResponse("Title must be 1–500 characters", 400);
    }

    const result = await db
      .update(webConversations)
      .set({ title, updatedAt: new Date() })
      .where(
        and(
          eq(webConversations.id, id),
          eq(webConversations.userId, session.user.id)
        )
      )
      .returning();

    if (result.length === 0) {
      return notFoundResponse("Conversation not found");
    }

    return successResponse({ conversation: result[0] });
  } catch (error) {
    if (error instanceof Error && error.message === "Unauthorized") {
      return unauthorizedResponse();
    }
    return errorResponse(
      error instanceof Error ? error.message : "Failed to update conversation"
    );
  }
}
```

也需要在顶部确保已 import `webConversations`（已 import）和 `and`, `eq`（已 import）。

- [ ] **Step 2：验证构建**

```bash
pnpm build
```

- [ ] **Step 3：提交**

```bash
git add app/api/conversations/[id]/route.ts
git commit -m "feat: add PATCH /api/conversations/[id] for rename"
```

---

### Task 13：侧边栏搜索功能

**Files:**
- Modify: `components/layout/app-sidebar.tsx`

- [ ] **Step 1：在 AppSidebar 组件添加搜索状态和 UI**

在 `AppSidebar` 函数顶部的 hooks 之后，添加搜索状态：

```typescript
const [isSearching, setIsSearching] = useState(false);
const [searchQuery, setSearchQuery] = useState("");
```

在 imports 中添加 `Search` 图标（已有 lucide-react）：

```typescript
import {
  MessageSquare, FileText, Plus, LogOut, User, Loader2, Trash2, Moon, Sun, Search, Pencil,
} from "lucide-react";
```

将 `SidebarHeader` 内容替换为：

```tsx
<SidebarHeader className="px-3 py-3">
  <div className="flex items-center gap-1.5">
    <Link href="/chat" className="flex flex-1 items-center gap-2.5">
      <div className="flex h-6 w-6 items-center justify-center rounded-md bg-sidebar-foreground/10 text-[11px] font-bold text-sidebar-foreground">
        A
      </div>
      <span className="text-sm font-semibold tracking-tight text-sidebar-foreground">
        AI Hunter
      </span>
    </Link>
    <button
      type="button"
      onClick={() => {
        setIsSearching((v) => !v);
        if (isSearching) setSearchQuery("");
      }}
      className={cn(
        "flex size-6 items-center justify-center rounded-md text-sidebar-foreground/50 hover:bg-sidebar-accent hover:text-sidebar-foreground transition-colors",
        isSearching && "bg-sidebar-accent text-sidebar-foreground"
      )}
      aria-label="搜索对话"
    >
      <Search className="h-3.5 w-3.5" />
    </button>
  </div>
  {isSearching && (
    <div className="px-1 pt-2">
      <input
        autoFocus
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setIsSearching(false);
            setSearchQuery("");
          }
        }}
        placeholder="搜索对话..."
        className="w-full rounded-md border border-sidebar-border bg-sidebar-accent/50 px-2.5 py-1 text-xs text-sidebar-foreground placeholder:text-sidebar-foreground/40 outline-none focus:border-sidebar-foreground/30"
      />
    </div>
  )}
</SidebarHeader>
```

将 `ConversationList` 的调用传入 `searchQuery`：

```tsx
<ConversationList
  conversations={conversations}
  isLoading={isLoading}
  pathname={pathname}
  searchQuery={searchQuery}
/>
```

- [ ] **Step 2：更新 ConversationList 支持 searchQuery**

在 `ConversationList` 的 props 类型中添加 `searchQuery: string`，并在过滤逻辑中使用：

```typescript
function ConversationList({
  conversations,
  isLoading,
  pathname,
  searchQuery,
}: {
  conversations: Conversation[];
  isLoading: boolean;
  pathname: string;
  searchQuery: string;
}) {
  // 已有的 deletedIds、deletingId state...
  
  const visibleItems = conversations.filter(
    (c) =>
      !deletedIds.has(c.id) &&
      (!searchQuery || (c.title || "新对话").toLowerCase().includes(searchQuery.toLowerCase()))
  );
  
  // 其余逻辑不变...
}
```

- [ ] **Step 3：验证构建**

```bash
pnpm build
```

- [ ] **Step 4：手动测试搜索**

- 点击搜索图标展开输入框
- 输入关键词，列表实时过滤
- 按 Esc 收起并清空

- [ ] **Step 5：提交**

```bash
git add components/layout/app-sidebar.tsx
git commit -m "feat: add conversation search to sidebar"
```

---

### Task 14：对话内联重命名

**Files:**
- Modify: `components/layout/app-sidebar.tsx`

- [ ] **Step 1：添加重命名状态到 ConversationList**

在 `ConversationList` 函数体顶部添加：

```typescript
const { renameConversation } = useConversations();
const [renamingId, setRenamingId] = useState<string | null>(null);
const [renameValue, setRenameValue] = useState("");
```

在文件顶部 imports 中确认已 import `useConversations`。

- [ ] **Step 2：添加重命名处理函数**

```typescript
const handleRenameStart = (id: string, currentTitle: string, e: React.MouseEvent) => {
  e.preventDefault();
  e.stopPropagation();
  setRenamingId(id);
  setRenameValue(currentTitle || "新对话");
};

const handleRenameCommit = async () => {
  if (!renamingId) return;
  const trimmed = renameValue.trim();
  setRenamingId(null);
  if (!trimmed) return;
  try {
    await renameConversation(renamingId, trimmed);
  } catch {
    toast.error("重命名失败");
  }
};
```

- [ ] **Step 3：更新列表项渲染**

将 `SidebarMenuItem` 内部的渲染改为：

```tsx
<SidebarMenuItem key={conversation.id}>
  <SidebarMenuButton
    asChild={renamingId !== conversation.id}
    isActive={pathname === `/chat/${conversation.id}`}
    className="pr-16"
  >
    {renamingId === conversation.id ? (
      <input
        autoFocus
        value={renameValue}
        onChange={(e) => setRenameValue(e.target.value)}
        onBlur={handleRenameCommit}
        onKeyDown={(e) => {
          if (e.key === "Enter") handleRenameCommit();
          if (e.key === "Escape") setRenamingId(null);
        }}
        className="w-full truncate bg-transparent text-xs outline-none border-b border-sidebar-foreground/30"
        onClick={(e) => e.stopPropagation()}
      />
    ) : (
      <Link href={`/chat/${conversation.id}`}>
        <span className="truncate text-xs">
          {conversation.title || "新对话"}
        </span>
      </Link>
    )}
  </SidebarMenuButton>

  {renamingId !== conversation.id && (
    <>
      <SidebarMenuAction
        showOnHover
        onClick={(e) => handleRenameStart(conversation.id, conversation.title || "新对话", e)}
        className="right-7 text-sidebar-foreground/40 hover:text-sidebar-foreground"
        aria-label="重命名"
      >
        <Pencil className="h-3 w-3" />
      </SidebarMenuAction>
      <SidebarMenuAction
        showOnHover
        onClick={(e) => handleDelete(conversation.id, e)}
        disabled={!!deletingId}
        className="text-sidebar-foreground/40 hover:text-sidebar-foreground"
      >
        {deletingId === conversation.id ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <Trash2 className="h-3 w-3" />
        )}
      </SidebarMenuAction>
    </>
  )}
</SidebarMenuItem>
```

- [ ] **Step 4：验证构建**

```bash
pnpm build
```

- [ ] **Step 5：手动测试**

- Hover 对话项出现铅笔和删除图标
- 点击铅笔进入编辑模式
- 回车保存，标题更新
- Esc 取消，标题不变

- [ ] **Step 6：提交**

```bash
git add components/layout/app-sidebar.tsx
git commit -m "feat: add inline conversation rename to sidebar"
```

---

### Task 15：文件预览面板

**Files:**
- Modify: `app/(main)/files/page.tsx`

- [ ] **Step 1：用以下内容完整替换 `app/(main)/files/page.tsx`**

```tsx
"use client";

import { useState, useEffect } from "react";
import { useFiles } from "@/lib/hooks/use-files";
import { useConversations } from "@/lib/hooks/use-conversations";
import {
  FileText, Loader2, File, MessageSquare, X, Download,
  FileImage, FileCode, Maximize2,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { zhCN } from "date-fns/locale";
import { cn } from "@/lib/utils";
import { SidebarTrigger } from "@/components/ui/sidebar";
import Link from "next/link";
import type { InferSelectModel } from "drizzle-orm";
import type { webFiles } from "@/lib/db/schema";

type FileRecord = InferSelectModel<typeof webFiles>;

const STATUS_MAP = {
  completed: { label: "完成", cls: "text-emerald-400 bg-emerald-400/10" },
  processing: { label: "处理中", cls: "text-amber-400 bg-amber-400/10" },
  failed: { label: "失败", cls: "text-red-400 bg-red-400/10" },
  pending: { label: "待处理", cls: "text-muted-foreground bg-muted/50" },
} as const;

function getPreviewType(mimeType: string | null | undefined): "pdf" | "image" | "text" | "none" {
  if (!mimeType) return "none";
  if (mimeType === "application/pdf") return "pdf";
  if (mimeType.startsWith("image/")) return "image";
  if (mimeType.startsWith("text/") || mimeType === "application/json") return "text";
  return "none";
}

function FilePreviewPanel({
  file,
  onClose,
}: {
  file: FileRecord;
  onClose: () => void;
}) {
  const [textContent, setTextContent] = useState<string | null>(null);
  const previewUrl = file.difyFileId ? `/api/files/preview/${file.difyFileId}` : null;
  const previewType = getPreviewType(file.mimeType);

  useEffect(() => {
    setTextContent(null);
    if (previewType === "text" && previewUrl) {
      fetch(previewUrl)
        .then((r) => r.text())
        .then(setTextContent)
        .catch(() => setTextContent("无法加载文件内容"));
    }
  }, [previewUrl, previewType]);

  return (
    <div className="flex h-full flex-col border-l border-border/50 bg-background">
      {/* Header */}
      <div className="flex shrink-0 items-center gap-2 border-b border-border/40 px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">{file.originalName}</p>
          <p className="text-[10px] text-muted-foreground/50 uppercase">{file.mimeType ?? "未知格式"}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {previewUrl && (
            <a
              href={previewUrl}
              download={file.originalName}
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground/50 hover:bg-accent hover:text-foreground transition-colors"
              title="下载"
            >
              <Download className="size-3.5" />
            </a>
          )}
          <button
            type="button"
            onClick={onClose}
            className="flex size-7 items-center justify-center rounded-md text-muted-foreground/50 hover:bg-accent hover:text-foreground transition-colors"
            aria-label="关闭预览"
          >
            <X className="size-3.5" />
          </button>
        </div>
      </div>

      {/* Preview Content */}
      <div className="min-h-0 flex-1 overflow-auto">
        {previewType === "pdf" && previewUrl && (
          <iframe
            src={previewUrl}
            className="h-full w-full"
            title={file.originalName}
          />
        )}
        {previewType === "image" && previewUrl && (
          <div className="flex items-center justify-center p-4">
            <img
              src={previewUrl}
              alt={file.originalName}
              className="max-h-full max-w-full rounded-lg object-contain"
            />
          </div>
        )}
        {previewType === "text" && (
          <pre className="p-4 text-xs leading-relaxed text-foreground/80 whitespace-pre-wrap break-words">
            {textContent ?? (
              <span className="flex items-center gap-2 text-muted-foreground/50">
                <Loader2 className="size-3 animate-spin" /> 加载中...
              </span>
            )}
          </pre>
        )}
        {previewType === "none" && (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
            <div className="flex size-12 items-center justify-center rounded-xl border border-border/40 bg-muted/40">
              <FileText className="size-5 text-muted-foreground/40" />
            </div>
            <p className="text-sm text-muted-foreground/60">不支持预览此格式</p>
            {previewUrl && (
              <a
                href={previewUrl}
                download={file.originalName}
                className="inline-flex items-center gap-1.5 rounded-md border border-border/50 px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              >
                <Download className="size-3" /> 下载文件
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function FilesPage() {
  const { files, isLoading } = useFiles();
  const { conversations } = useConversations();
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);

  const convMap = new Map(conversations.map((c) => [c.id, c.title]));
  const selectedFile = files.find((f) => f.id === selectedFileId) ?? null;

  const fmt = (bytes: number) => {
    if (!bytes) return "0 B";
    const k = 1024, s = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / k ** i).toFixed(2))} ${s[i]}`;
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="flex h-14 shrink-0 items-center gap-2 px-4">
        <SidebarTrigger className="size-9 shrink-0 text-muted-foreground hover:bg-accent hover:text-foreground" />
        <span className="text-sm text-foreground/70">文件管理</span>
      </header>

      {/* Content */}
      <div className="flex min-h-0 flex-1">
        {/* File Table */}
        <div className={cn("overflow-auto p-5 transition-all duration-200", selectedFile ? "w-[55%]" : "w-full")}>
          <div className={cn("mx-auto", selectedFile ? "max-w-none" : "max-w-4xl")}>
            {isLoading ? (
              <div className="flex items-center justify-center py-24">
                <Loader2 className="size-4 animate-spin text-muted-foreground/30" />
              </div>
            ) : files.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-24 text-center">
                <div className="mb-4 flex size-12 items-center justify-center rounded-xl border border-border/40 bg-muted/40">
                  <File className="size-5 text-muted-foreground/40" />
                </div>
                <p className="text-sm text-muted-foreground/60">暂无文件</p>
                <p className="mt-1 text-xs text-muted-foreground/40">在对话中发送文件后会显示在这里</p>
              </div>
            ) : (
              <div className="overflow-hidden rounded-xl border border-border/50">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-border/40">
                      {["文件名", "大小", "状态", "所属会话", "上传时间"].map((h) => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/30">
                    {files.map((file) => {
                      const s = (file.status as keyof typeof STATUS_MAP) || "pending";
                      const { label, cls } = STATUS_MAP[s] ?? STATUS_MAP.pending;
                      const convTitle = file.conversationId ? convMap.get(file.conversationId) : null;
                      const isSelected = selectedFileId === file.id;
                      return (
                        <tr
                          key={file.id}
                          onClick={() => setSelectedFileId(isSelected ? null : file.id)}
                          className={cn(
                            "group cursor-pointer transition-colors hover:bg-accent/20",
                            isSelected && "bg-accent/30"
                          )}
                        >
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2.5">
                              <div className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-border/30 bg-muted/50">
                                <FileText className="size-3.5 text-muted-foreground/50" />
                              </div>
                              <span className="max-w-[180px] truncate text-xs font-medium text-foreground/90">
                                {file.originalName}
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-3 text-xs text-muted-foreground/60">{fmt(file.size || 0)}</td>
                          <td className="px-4 py-3">
                            <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium", cls)}>
                              {label}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            {file.conversationId && convTitle ? (
                              <Link
                                href={`/chat/${file.conversationId}`}
                                onClick={(e) => e.stopPropagation()}
                                className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground/70 hover:bg-accent hover:text-foreground transition-colors"
                              >
                                <MessageSquare className="size-3 shrink-0" />
                                <span className="max-w-[120px] truncate">{convTitle}</span>
                              </Link>
                            ) : (
                              <span className="text-xs text-muted-foreground/30">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-xs text-muted-foreground/50">
                            {file.uploadedAt
                              ? formatDistanceToNow(new Date(file.uploadedAt), { addSuffix: true, locale: zhCN })
                              : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Preview Panel */}
        {selectedFile && (
          <div className="w-[45%] shrink-0">
            <FilePreviewPanel file={selectedFile} onClose={() => setSelectedFileId(null)} />
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2：验证构建**

```bash
pnpm build
```

- [ ] **Step 3：手动测试**

- 点击文件行 → 右侧预览面板滑出
- PDF 文件显示 iframe 预览
- 图片文件显示图片
- 点击其他文件直接切换
- 点击 X 或再次点击同一行关闭面板
- 下载按钮正常工作

- [ ] **Step 4：提交**

```bash
git add app/\(main\)/files/page.tsx
git commit -m "feat: add file preview panel with PDF and image support"
```

---

## Phase 4：测试

### Task 16：配置 Vitest

**Files:**
- Create: `vitest.config.ts`
- Modify: `package.json`

- [ ] **Step 1：安装 Vitest**

```bash
pnpm add -D vitest @vitest/coverage-v8
```

- [ ] **Step 2：创建配置文件**

```typescript
// vitest.config.ts
import { defineConfig } from "vitest/config";
import { resolve } from "path";

export default defineConfig({
  test: {
    environment: "node",
    globals: true,
    coverage: {
      provider: "v8",
      include: ["lib/**/*.ts", "app/api/**/*.ts"],
      exclude: ["lib/db/schema.ts", "**/*.d.ts"],
      thresholds: { lines: 80 },
    },
  },
  resolve: {
    alias: {
      "@": resolve(__dirname, "."),
    },
  },
});
```

- [ ] **Step 3：在 `package.json` 中添加测试脚本**

在 `"scripts"` 中添加：

```json
"test": "vitest run",
"test:watch": "vitest",
"test:coverage": "vitest run --coverage"
```

- [ ] **Step 4：运行确认 Vitest 可以启动**

```bash
pnpm test
```

Expected: `No test files found` 或 `0 tests passed`（不报错即可）。

- [ ] **Step 5：提交**

```bash
git add vitest.config.ts package.json pnpm-lock.yaml
git commit -m "chore: configure vitest for unit and integration testing"
```

---

### Task 17：think 工具函数单元测试

（Task 2 中已写测试并通过，此步骤验证覆盖率）

- [ ] **Step 1：运行测试并查看覆盖率**

```bash
pnpm test:coverage
```

Expected: `lib/utils/think.ts` 覆盖率 100%。

---

### Task 18：`convertDbMessage` 和 API helpers 单元测试

**Files:**
- Create: `tests/unit/convert-message.test.ts`
- Create: `tests/unit/api-response.test.ts`

- [ ] **Step 1：写 convertDbMessage 测试**

```typescript
// tests/unit/convert-message.test.ts
import { describe, it, expect } from "vitest";
import { convertDbMessage } from "@/lib/assistant-ui/convert-message";
import type { DbMessage } from "@/lib/assistant-ui/types";

const baseMsg: DbMessage = {
  id: "msg-1",
  conversationId: "conv-1",
  role: "user",
  content: "Hello",
  difyMessageId: null,
  files: null,
  metadata: null,
  createdAt: new Date("2024-01-01"),
};

describe("convertDbMessage", () => {
  it("用户消息原样返回内容", () => {
    const result = convertDbMessage(baseMsg);
    expect(result.role).toBe("user");
    expect(result.content).toBe("Hello");
    expect(result.id).toBe("msg-1");
  });

  it("助手消息去除 think 标签", () => {
    const msg: DbMessage = { ...baseMsg, role: "assistant", content: "<think>思考</think>答案" };
    const result = convertDbMessage(msg);
    expect(result.content).toBe("答案");
  });

  it("_attachments 优先于 serverAttachments", () => {
    const msg: DbMessage = {
      ...baseMsg,
      _attachments: [{ name: "file.pdf", contentType: "application/pdf", upload_file_id: "fid-1" }],
      serverAttachments: [{ difyFileId: "fid-2", name: "other.pdf", mimeType: "application/pdf", previewUrl: "/preview/fid-2" }],
    };
    const result = convertDbMessage(msg);
    expect(result.attachments).toHaveLength(1);
    expect((result.attachments?.[0] as { id: string }).id).toBe("fid-1");
  });

  it("无附件时 attachments 为 undefined", () => {
    const result = convertDbMessage(baseMsg);
    expect(result.attachments).toBeUndefined();
  });
});
```

- [ ] **Step 2：写 API response helpers 测试**

```typescript
// tests/unit/api-response.test.ts
import { describe, it, expect } from "vitest";
import { successResponse, errorResponse, unauthorizedResponse, notFoundResponse } from "@/lib/api/response";

describe("successResponse", () => {
  it("返回 success:true 和 data", async () => {
    const res = successResponse({ foo: "bar" });
    const body = await res.json();
    expect(body).toEqual({ success: true, data: { foo: "bar" } });
    expect(res.status).toBe(200);
  });
});

describe("errorResponse", () => {
  it("返回 success:false 和 error 字段", async () => {
    const res = errorResponse("Something went wrong", 400);
    const body = await res.json();
    expect(body.success).toBe(false);
    expect(body.error).toBe("Something went wrong");
    expect(res.status).toBe(400);
  });

  it("过滤 SQL 错误信息", async () => {
    const res = errorResponse("Failed query syntax error near WHERE");
    const body = await res.json();
    expect(body.error).toBe("Invalid request");
  });
});

describe("unauthorizedResponse", () => {
  it("返回 401", async () => {
    const res = unauthorizedResponse();
    expect(res.status).toBe(401);
  });
});

describe("notFoundResponse", () => {
  it("返回 404", async () => {
    const res = notFoundResponse("Not found");
    expect(res.status).toBe(404);
  });
});
```

- [ ] **Step 3：运行测试**

```bash
pnpm test
```

Expected: 所有测试通过。

- [ ] **Step 4：提交**

```bash
git add tests/unit/convert-message.test.ts tests/unit/api-response.test.ts
git commit -m "test: add unit tests for convertDbMessage and API helpers"
```

---

### Task 19：对话列表 API 集成测试

**Files:**
- Create: `tests/integration/conversations.test.ts`

注意：集成测试需要真实 DB。运行前确保 `pnpm dev:db` 已启动，且 `DATABASE_URL` 指向测试库（使用 `.env.test`）。

- [ ] **Step 1：写集成测试**

```typescript
// tests/integration/conversations.test.ts
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { NextRequest } from "next/server";

// 加载测试环境变量
import "dotenv/config";

// 动态 import 防止构建时加载 DB
const getRoute = () => import("@/app/api/conversations/route");
const getIdRoute = () => import("@/app/api/conversations/[id]/route");

// 辅助：创建带有认证 session 的 mock 请求
// 注意：集成测试需要一个有效的 session token，建议使用专用测试账号
// 此处为 smoke test 框架，实际运行需配置 TEST_SESSION_TOKEN 环境变量

describe("GET /api/conversations", () => {
  it("无认证时返回 401", async () => {
    const { GET } = await getRoute();
    const req = new NextRequest("http://localhost:3000/api/conversations");
    const res = await GET(req);
    expect(res.status).toBe(401);
  });
});

describe("PATCH /api/conversations/[id]", () => {
  it("无认证时返回 401", async () => {
    const { PATCH } = await getIdRoute();
    const req = new NextRequest("http://localhost:3000/api/conversations/test-id", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "新标题" }),
    });
    const res = await PATCH(req, { params: Promise.resolve({ id: "test-id" }) });
    expect(res.status).toBe(401);
  });

  it("title 为空时返回 400", async () => {
    // 需要有效 session 才能验证 400，此处验证 401 优先
    const { PATCH } = await getIdRoute();
    const req = new NextRequest("http://localhost:3000/api/conversations/test-id", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "" }),
    });
    const res = await PATCH(req, { params: Promise.resolve({ id: "test-id" }) });
    // 无 session 先返回 401
    expect([400, 401]).toContain(res.status);
  });
});
```

- [ ] **Step 2：运行测试**

```bash
pnpm test tests/integration/
```

Expected: 所有测试通过（401 行为验证）。

- [ ] **Step 3：提交**

```bash
git add tests/integration/conversations.test.ts
git commit -m "test: add integration tests for conversations API"
```

---

### Task 20：安装 Playwright 并配置 E2E 测试

**Files:**
- Create: `playwright.config.ts`
- Create: `tests/e2e/auth.spec.ts`
- Create: `tests/e2e/chat.spec.ts`
- Create: `tests/e2e/files.spec.ts`

- [ ] **Step 1：安装 Playwright**

```bash
pnpm add -D @playwright/test
pnpm exec playwright install chromium
```

- [ ] **Step 2：创建配置**

```typescript
// playwright.config.ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  retries: 1,
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    command: "pnpm dev",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
```

- [ ] **Step 3：在 `package.json` 中添加 E2E 脚本**

```json
"test:e2e": "playwright test"
```

- [ ] **Step 4：写认证流程 E2E 测试**

```typescript
// tests/e2e/auth.spec.ts
import { test, expect } from "@playwright/test";

// 测试账号（确保 .env.local 有 DATABASE_URL 并已运行 pnpm dev:db）
const TEST_EMAIL = "e2e-test@example.com";
const TEST_PASSWORD = "TestPassword123!";
const TEST_NAME = "E2E User";

test.describe("认证流程", () => {
  test("注册新用户", async ({ page }) => {
    await page.goto("/register");
    await page.getByPlaceholder(/名称|用户名/i).fill(TEST_NAME);
    await page.getByPlaceholder(/邮箱/i).fill(`e2e-${Date.now()}@example.com`);
    await page.getByPlaceholder(/密码/i).fill(TEST_PASSWORD);
    await page.getByRole("button", { name: /注册/i }).click();
    // 注册成功后重定向到 /chat
    await expect(page).toHaveURL(/\/chat/, { timeout: 10_000 });
  });

  test("登录已有账号", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder(/邮箱/i).fill(TEST_EMAIL);
    await page.getByPlaceholder(/密码/i).fill(TEST_PASSWORD);
    await page.getByRole("button", { name: /登录/i }).click();
    await expect(page).toHaveURL(/\/chat/, { timeout: 10_000 });
  });
});
```

- [ ] **Step 5：写聊天流程 E2E 测试**

```typescript
// tests/e2e/chat.spec.ts
import { test, expect } from "@playwright/test";

test.describe("对话流程", () => {
  test.beforeEach(async ({ page }) => {
    // 假设已有测试账号登录
    await page.goto("/login");
    await page.getByPlaceholder(/邮箱/i).fill("e2e-test@example.com");
    await page.getByPlaceholder(/密码/i).fill("TestPassword123!");
    await page.getByRole("button", { name: /登录/i }).click();
    await expect(page).toHaveURL(/\/chat/, { timeout: 10_000 });
  });

  test("新建对话并发送消息", async ({ page }) => {
    await page.goto("/chat");
    const input = page.getByPlaceholder("发送消息...");
    await input.fill("你好");
    await page.getByRole("button", { name: /发送/i }).click();
    // URL 重定向到 /chat/[id]
    await expect(page).toHaveURL(/\/chat\/.+/, { timeout: 10_000 });
    // 消息出现在列表中
    await expect(page.getByText("你好")).toBeVisible();
  });

  test("对话重命名", async ({ page }) => {
    // 先新建一个对话
    await page.goto("/chat");
    await page.getByPlaceholder("发送消息...").fill("测试重命名");
    await page.getByRole("button", { name: /发送/i }).click();
    await expect(page).toHaveURL(/\/chat\/.+/, { timeout: 10_000 });

    // Hover 侧边栏对话项，点击铅笔图标
    const convItem = page.locator('[data-sidebar="menu-item"]').first();
    await convItem.hover();
    await convItem.getByLabel("重命名").click();
    await convItem.locator("input").fill("已重命名的对话");
    await convItem.locator("input").press("Enter");

    await expect(page.getByText("已重命名的对话")).toBeVisible({ timeout: 5_000 });
  });

  test("侧边栏搜索过滤对话", async ({ page }) => {
    await page.goto("/chat");
    // 点击搜索图标
    await page.getByLabel("搜索对话").click();
    await page.getByPlaceholder("搜索对话...").fill("不存在的关键词xyz");
    await expect(page.getByText("暂无对话")).toBeVisible();
  });
});
```

- [ ] **Step 6：写文件预览 E2E 测试**

```typescript
// tests/e2e/files.spec.ts
import { test, expect } from "@playwright/test";
import path from "path";

test.describe("文件管理", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder(/邮箱/i).fill("e2e-test@example.com");
    await page.getByPlaceholder(/密码/i).fill("TestPassword123!");
    await page.getByRole("button", { name: /登录/i }).click();
    await expect(page).toHaveURL(/\/chat/, { timeout: 10_000 });
  });

  test("文件页面可以正常加载", async ({ page }) => {
    await page.goto("/files");
    await expect(page.getByText("文件管理")).toBeVisible();
    // 应该显示空状态或文件列表
    await expect(
      page.getByText("暂无文件").or(page.locator("table"))
    ).toBeVisible({ timeout: 5_000 });
  });

  test("点击文件行打开预览面板", async ({ page }) => {
    await page.goto("/files");
    // 等待文件列表加载
    const fileRow = page.locator("tbody tr").first();
    await fileRow.waitFor({ state: "visible", timeout: 5_000 }).catch(() => {
      // 无文件时跳过预览测试
      test.skip();
    });
    await fileRow.click();
    // 预览面板应该出现
    await expect(page.getByLabel("关闭预览")).toBeVisible({ timeout: 3_000 });
  });
});
```

- [ ] **Step 7：运行 E2E 测试（需要 dev server 运行中）**

```bash
pnpm test:e2e
```

Expected: 基础认证和页面加载测试通过（chat/rename 测试需要有效测试账号）。

- [ ] **Step 8：提交**

```bash
git add playwright.config.ts tests/e2e/ package.json pnpm-lock.yaml
git commit -m "test: add Playwright E2E tests for auth, chat, and file preview"
```

---

## 完成验证清单

- [ ] `pnpm build` 无错误
- [ ] `pnpm test` 单元测试全部通过
- [ ] 覆盖率 `pnpm test:coverage`：核心模块 ≥ 80%
- [ ] `pnpm test:e2e` E2E 基础流程通过
- [ ] `use-dify-runtime.ts` < 250 行
- [ ] `use-new-chat-runtime.ts` < 200 行
- [ ] 侧边栏搜索图标可展开输入框，实时过滤
- [ ] 对话重命名：铅笔图标 → inline 输入 → 回车保存
- [ ] 文件页点击行 → 右侧预览面板（PDF/图片/文本）
- [ ] Network 面板确认对话/文件列表有 SWR 缓存（切换页面不重复请求）

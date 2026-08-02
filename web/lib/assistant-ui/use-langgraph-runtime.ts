"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { useSWRConfig } from "swr";
import { useExternalStoreRuntime, type AppendMessage, type AttachmentAdapter } from "@assistant-ui/react";
import { ThinkingContext } from "./thinking-context";
import { useThinking } from "./use-thinking";
import { runStream, type StreamContentSnapshot } from "./sse";
import { convertDbMessage } from "./convert-message";
import {
  consumeFileItemsByAttachmentIds,
  primeFileItemsByAttachmentIds,
} from "./attachment-store";
import type { DbMessage } from "./types";
import type { FileItem } from "@/lib/types/chat-upload";
import { parsePendingPayload, pendingMessageKey } from "@/lib/utils/pending-chat-payload";
import { isThreadsListKey } from "@/lib/backend/langgraph";

export { ThinkingContext };

// handleSend 实际只读取 content 与 attachments;窄化入参,使自动发送(pending)路径
// 无需把整个对象 `as unknown as AppendMessage`。content 额外允许裸 string(pending payload),
// 真实 onNew 的 AppendMessage(content 为 parts)可结构兼容赋给本类型。
type SendInput = {
  content: string | AppendMessage["content"];
  attachments?: AppendMessage["attachments"];
};

interface RunTurnOptions {
  clientTurnId: string;
  regenerate?: boolean;
  selectedAssistantTurnId?: string;
}

function createClientTurnId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `turn-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function collectFileItems(message: SendInput): FileItem[] {
  const ids = (message.attachments ?? []).map((a) => a.id);
  return consumeFileItemsByAttachmentIds(ids);
}

interface LanggraphRuntimeState {
  messages: DbMessage[];
  isRunning: boolean;
  reportRef: string | null;
}

export function useLanggraphRuntime(
  threadId: string,
  caseId?: number,
  initialMessages?: DbMessage[],
  attachmentAdapter?: AttachmentAdapter,
  initialReportRef?: string
) {
  const { mutate } = useSWRConfig();
  // report_ref 是后端生成的不透明 UUID，不能从 threadId 派生。
  // 历史会话从最近一条 assistant 消息的 metadata.final_report_ref 还原。
  const historicalReportRef =
    [...(initialMessages ?? [])]
      .reverse()
      .find(
        (m) =>
          m.role === "assistant" &&
          typeof m.metadata?.final_report_ref === "string" &&
          m.metadata.final_report_ref.trim().length > 0
      )
      ?.metadata?.final_report_ref as string | undefined;
  const [state, setState] = useState<LanggraphRuntimeState>({
    messages: initialMessages ?? [],
    isRunning: false,
    reportRef: initialReportRef?.trim() || historicalReportRef || null,
  });

  const abortRef = useRef<(() => void) | null>(null);
  const messagesRef = useRef<DbMessage[]>([]);
  messagesRef.current = state.messages;

  const attachmentsRef = useRef<Map<string, FileItem[]>>(new Map());
  const seededInitialAttachmentsRef = useRef(false);
  if (!seededInitialAttachmentsRef.current) {
    for (const message of initialMessages ?? []) {
      const uploadedFiles = message.metadata?.uploaded_files;
      if (message.role === "user" && Array.isArray(uploadedFiles)) {
        attachmentsRef.current.set(message.id, uploadedFiles as FileItem[]);
      }
    }
    seededInitialAttachmentsRef.current = true;
  }

  const pendingContentRef = useRef<StreamContentSnapshot | null>(null);
  const updateTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { thinkingMap, streamIdRef, initThinking, updateThinking, completeThinking } = useThinking();

  const cancelFlush = useCallback(() => {
    if (updateTimerRef.current) {
      clearTimeout(updateTimerRef.current);
      updateTimerRef.current = null;
    }
  }, []);

  const applyStreamingContent = useCallback((snapshot: StreamContentSnapshot) => {
    setState((prev) => {
      const sid = streamIdRef.current;
      const msgs = [...prev.messages];
      const lastIdx = msgs.length - 1;
      if (lastIdx >= 0 && msgs[lastIdx].role === "assistant" && msgs[lastIdx].id.startsWith("stream-")) {
        msgs[lastIdx] = {
          ...msgs[lastIdx],
          content: snapshot.text,
          _contentParts: snapshot.parts,
        };
      } else {
        msgs.push({
          id: sid || `stream-${Date.now()}`,
          conversationId: threadId,
          role: "assistant",
          content: snapshot.text,
          metadata: null,
          createdAt: new Date(),
          _contentParts: snapshot.parts,
        });
      }
      return { ...prev, messages: msgs };
    });
  }, [threadId, streamIdRef]);

  const scheduleFlush = useCallback((flushFn: () => void) => {
    if (updateTimerRef.current) return;
    updateTimerRef.current = setTimeout(() => {
      updateTimerRef.current = null;
      flushFn();
    }, 30);
  }, []);

  const flushPending = useCallback(() => {
    const snapshot = pendingContentRef.current;
    pendingContentRef.current = null;
    if (snapshot !== null) applyStreamingContent(snapshot);
  }, [applyStreamingContent]);

  // 一次流式问答的执行核心:调用 runStream、节流刷新、收尾或错误标记。
  // handleSend / handleReload 仅在「播种消息」前缀不同,共享此后半段。
  const runTurn = useCallback(
    async (query: string, fileItems: FileItem[], options: RunTurnOptions) => {
      let accumulatedContent = "";
      try {
        await runStream(
          {
            threadId,
            query,
            caseId,
            uploadedFiles: fileItems,
            clientTurnId: options.clientTurnId,
            regenerate: options.regenerate,
            selectedAssistantTurnId: options.selectedAssistantTurnId,
          },
          {
            onChunk: (chunk) => {
              accumulatedContent += chunk;
              pendingContentRef.current = { text: accumulatedContent };
            },
            onReplace: (snapshot) => {
              accumulatedContent = snapshot.text;
              pendingContentRef.current = snapshot;
            },
            onAbortRef: (cancel) => { abortRef.current = cancel; },
            onThinking: updateThinking,
            onFinal: (ref) => setState((prev) => ({ ...prev, reportRef: ref })),
          },
          scheduleFlush,
          cancelFlush,
          flushPending
        );

        cancelFlush();
        if (pendingContentRef.current !== null) {
          applyStreamingContent(pendingContentRef.current);
          pendingContentRef.current = null;
        }
        completeThinking();

        setState((prev) => ({ ...prev, isRunning: false }));
        void mutate(isThreadsListKey);
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
            msgs.push({ id: `error-${Date.now()}`, conversationId: threadId, role: "assistant", content: accumulatedContent, metadata: null, createdAt: new Date(), _canReload: true, _status: { type: "incomplete", reason: "error", error: errorMessage } });
          }
          return { ...prev, messages: msgs, isRunning: false };
        });
      }
    },
    [threadId, caseId, scheduleFlush, cancelFlush, applyStreamingContent, flushPending, updateThinking, completeThinking, mutate]
  );

  const handleSend = useCallback(
    async (message: SendInput) => {
      const content =
        typeof message.content === "string"
          ? message.content
          : message.content.filter((p) => p.type === "text").map((p) => (p as { text?: string }).text ?? "").join("");

      if (!content.trim()) return;

      const streamMsgId = `stream-${Date.now()}`;
      const userMsgId = createClientTurnId();
      const userAttachments = (message.attachments ?? []) as DbMessage["_attachments"];
      initThinking(streamMsgId);
      setState((prev) => ({
        ...prev,
        reportRef: null,
        messages: [
          ...prev.messages,
          {
            id: userMsgId,
            conversationId: threadId,
            role: "user",
            content,
            metadata: { turn_id: userMsgId },
            createdAt: new Date(),
            _attachments: userAttachments,
            _clientTurnId: userMsgId,
          },
          { id: streamMsgId, conversationId: threadId, role: "assistant", content: "", metadata: null, createdAt: new Date(), _canReload: true },
        ],
        isRunning: true,
      }));

      const fileItems = collectFileItems(message);
      attachmentsRef.current.set(userMsgId, fileItems);

      await runTurn(content, fileItems, { clientTurnId: userMsgId });
    },
    [threadId, runTurn, initThinking]
  );

  // Auto-send pending message carried over from the /chat new-conversation flow
  const handleSendRef = useRef(handleSend);
  handleSendRef.current = handleSend;
  useEffect(() => {
    if (state.messages.length !== 0) return;
    const raw = sessionStorage.getItem(pendingMessageKey(threadId));
    const payload = parsePendingPayload(raw);
    if (!payload) return;

    const timer = setTimeout(() => {
      sessionStorage.removeItem(pendingMessageKey(threadId));
      if (payload.fileItemEntries && payload.fileItemEntries.length > 0) {
        primeFileItemsByAttachmentIds(payload.fileItemEntries);
      }
      handleSendRef.current({
        content: payload.content,
        // 序列化的 PendingAttachmentMeta 缺运行时字段(file Blob),与 CompleteAttachment 本质不同;
        // collectFileItems 只用到 id,此处对单字段断言,content 仍保留类型检查。
        attachments: payload.attachments as unknown as AppendMessage["attachments"],
      });
    }, 100);
    return () => clearTimeout(timer);
  }, [threadId, state.messages.length]);

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
      if (!parentMessage._clientTurnId) return;

      const previousAssistant = currentMessages[parentIndex + 1];
      const retryingFailedRequest =
        previousAssistant?.role === "assistant" &&
        previousAssistant._status?.type === "incomplete";

      const streamMsgId = `stream-${Date.now()}`;
      initThinking(streamMsgId);
      setState((prev) => ({
        ...prev,
        reportRef: null,
        messages: [
          ...currentMessages.slice(0, parentIndex + 1),
          { id: streamMsgId, conversationId: threadId, role: "assistant", content: "", metadata: null, createdAt: new Date(), _canReload: true },
        ],
        isRunning: true,
      }));

      const fileItems = attachmentsRef.current.get(parentId) ?? [];
      await runTurn(parentMessage.content, fileItems, {
        clientTurnId: parentMessage._clientTurnId,
        regenerate: !retryingFailedRequest,
      });
    },
    [threadId, runTurn, initThinking]
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

  return { runtime, thinkingMap, reportRef: state.reportRef };
}

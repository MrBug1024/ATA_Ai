// app/(main)/chat/[id]/page.tsx
"use client";

import { use, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AssistantChat, type SerializableMessage } from "@/components/chat/assistant-chat";
import { getThreadDetail, getThreadTurns } from "@/lib/backend/langgraph";
import { useChatUpload } from "@/lib/hooks/use-chat-upload";
import { createChatAttachmentAdapter } from "@/lib/assistant-ui/chat-attachment-adapter";
import { seedPreviewUrls } from "@/lib/assistant-ui/attachment-store";
import { uploadedFilesToAttachments } from "@/lib/assistant-ui/uploaded-files-to-attachments";
import { parsePendingPayload, pendingMessageKey } from "@/lib/utils/pending-chat-payload";
import type { ThreadDetailResponse } from "@/lib/types/langgraph-chat";

interface ChatDetailPageProps {
  params: Promise<{ id: string }>;
}

function positiveCaseId(value: string | null): number | undefined {
  if (value === null || value.trim() === "") return undefined;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}

export default function ChatDetailPage({ params }: ChatDetailPageProps) {
  const { id } = use(params);
  const searchParams = useSearchParams();
  const caseIdParam = searchParams.get("caseId");
  const [threadDetail, setThreadDetail] = useState<ThreadDetailResponse | null>(null);
  const caseId =
    positiveCaseId(caseIdParam) ??
    (Number.isInteger(threadDetail?.case_id) && (threadDetail?.case_id ?? 0) > 0
      ? threadDetail?.case_id
      : undefined);

  const [initialMessages, setInitialMessages] = useState<SerializableMessage[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const { upload } = useChatUpload();
  const attachmentAdapter = useMemo(() => {
    if (caseId == null) return undefined;
    return createChatAttachmentAdapter({ caseId, upload });
  }, [caseId, upload]);

  useEffect(() => {
    let cancelled = false;
    setThreadDetail(null);
    setInitialMessages(null);
    setLoadError(false);

    // A new conversation is persisted by its first /chat/invoke request. The
    // landing page leaves that first message in sessionStorage, so mount the
    // runtime immediately instead of requesting history for a thread that does
    // not exist yet. The runtime consumes the pending payload and sends it.
    const pendingPayload = parsePendingPayload(
      sessionStorage.getItem(pendingMessageKey(id))
    );
    if (pendingPayload) {
      setInitialMessages([]);
      return () => {
        cancelled = true;
      };
    }

    (async () => {
      try {
        const [detail, data] = await Promise.all([
          getThreadDetail(id),
          getThreadTurns(id),
        ]);
        const now = new Date().toISOString();
        const previewSeeds: { id: string; url: string }[] = [];
        const mapped: SerializableMessage[] = (data.turns ?? []).flatMap((turn, index) => {
          const turnId = turn.turn_id || turn.user.turn_id || `legacy-turn-${index}`;
          const userMessage: SerializableMessage = {
            id: turnId,
            conversationId: id,
            role: "user",
            content: turn.user.content,
            metadata: {
              turn_id: turnId,
              uploaded_files: turn.user.uploaded_files ?? [],
            },
            createdAt: turn.user.created_at || now,
          };
          if (turn.user.uploaded_files?.length) {
            const { attachments, seeds } = uploadedFilesToAttachments(turn.user.uploaded_files);
            previewSeeds.push(...seeds);
            userMessage._attachments = attachments;
          }

          const assistant = turn.assistants?.at(-1);
          if (!assistant) return [userMessage];
          const assistantMessage: SerializableMessage = {
            id: `assistant-${turnId}-${assistant.version || turn.assistants.length}`,
            conversationId: id,
            role: "assistant",
            content: assistant.content,
            metadata: {
              turn_id: turnId,
              assistant_turn_id: assistant.turn_id,
              version: assistant.version,
              final_report_ref: assistant.final_report_ref,
              intent: assistant.intent,
            },
            createdAt: assistant.created_at || now,
          };
          return [userMessage, assistantMessage];
        });
        if (!cancelled) {
          seedPreviewUrls(previewSeeds);
          setThreadDetail(detail);
          setInitialMessages(mapped);
        }
      } catch {
        if (!cancelled) setLoadError(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, reloadKey]);

  if (loadError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <p className="text-sm text-muted-foreground">会话加载失败</p>
        <Button variant="outline" size="sm" onClick={() => setReloadKey((k) => k + 1)}>
          重试
        </Button>
      </div>
    );
  }

  if (initialMessages === null) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="size-4 animate-spin text-muted-foreground/40" />
      </div>
    );
  }

  const attachmentDisabled = caseId == null;
  const attachmentDisabledReason = attachmentDisabled
    ? "需先选择年审项目才能上传文件"
    : undefined;

  return (
    <AssistantChat
      key={id}
      threadId={id}
      caseId={caseId}
      initialMessages={initialMessages}
      initialReportRef={threadDetail?.final_report_ref || undefined}
      attachmentAdapter={attachmentAdapter}
      attachmentDisabled={attachmentDisabled}
      attachmentDisabledReason={attachmentDisabledReason}
      title={threadDetail?.title}
    />
  );
}

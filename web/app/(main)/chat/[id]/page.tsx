// app/(main)/chat/[id]/page.tsx
"use client";

import { use, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AssistantChat, type SerializableMessage } from "@/components/chat/assistant-chat";
import { getThreadDetail, getThreadTurns } from "@/lib/backend/langgraph";
import { BackendError } from "@/lib/backend/http";
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

const UNSAFE_ERROR_FALLBACK = "服务返回了无法安全展示的错误信息，请重试或联系管理员。";
const HISTORICAL_AUDIT_HISTORY_UNAVAILABLE =
  "该历史会话在当前年审存储中不可用。请在对应年审项目内重新发起会话；未在当前存储中可追溯的历史内容不能作为审计依据。";
const LEGACY_THREAD_NOT_FOUND = /^thread(?:\s+.+?)?\s+not found$/i;

/**
 * The history endpoint can return a useful, user-actionable API error. Keep
 * that text visible, but never render an HTML error page or a stack trace.
 */
export function safeHistoryLoadErrorMessage(error: unknown): string | null {
  if (!(error instanceof BackendError) && !(error instanceof Error)) return null;

  const raw = error.message.trim();
  if (!raw) return null;
  if (/<\/?(?:html|head|body|script|style)\b|<!doctype\b/i.test(raw)) {
    return UNSAFE_ERROR_FALLBACK;
  }

  // Error.stack is normally separate from message, but callers can still put
  // it in message. Only expose the first line, then collapse odd whitespace.
  const firstLine = raw.split(/\r?\n/, 1)[0]?.replace(/\s+/g, " ").trim() ?? "";
  if (!firstLine || /^(?:traceback|stack trace)\b/i.test(firstLine)) {
    return UNSAFE_ERROR_FALLBACK;
  }

  // Older deployments returned `Thread <id> not found`. Convert it to the
  // current audit-safe guidance rather than displaying a potentially sensitive
  // thread identifier. Access-denied responses are intentionally unchanged:
  // they remain ambiguous between a missing and an unauthorized conversation.
  if (LEGACY_THREAD_NOT_FOUND.test(firstLine)) {
    return HISTORICAL_AUDIT_HISTORY_UNAVAILABLE;
  }

  // Do not leak credentials should a proxy or database client include them.
  const redacted = firstLine
    .replace(/([a-z][a-z0-9+.-]*:\/\/)[^@\s/]+@/gi, "$1[凭据已隐藏]@")
    .replace(/\b(password|token|secret|api[_-]?key)\s*([=:])\s*[^\s,;]+/gi, "$1$2[已隐藏]");
  return redacted.slice(0, 320) || UNSAFE_ERROR_FALLBACK;
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
  const [loadErrorMessage, setLoadErrorMessage] = useState<string | null>(null);
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
    setLoadErrorMessage(null);

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
              // These are response-scoped snapshots from /turns.  Do not use
              // threadDetail.final_report_ref here: a historical reply must
              // retain the citations and unresolved items that belonged to
              // that exact assistant version.
              route_decision: assistant.route_decision ?? null,
              trace_items: assistant.trace_items ?? [],
              citation_coverage: assistant.citation_coverage ?? {},
              // Preserve undefined for replies stored before response-scoped
              // analysis-run metadata was introduced.  It is intentionally
              // different from a current, valid empty array.
              response_analysis_runs: assistant.response_analysis_runs,
              unresolved_relations: assistant.unresolved_relations ?? [],
              unresolved_claims: assistant.unresolved_claims ?? [],
              audit_review_stage: assistant.audit_review_stage ?? "",
              active_template_versions: assistant.active_template_versions ?? {},
              attachment_package: assistant.attachment_package ?? {},
              custom: {
                finalReportRef: assistant.final_report_ref || null,
                routeDecision: assistant.route_decision ?? null,
                traceItems: assistant.trace_items ?? [],
                citationCoverage: assistant.citation_coverage ?? {},
                responseAnalysisRuns: assistant.response_analysis_runs,
                unresolvedRelations: assistant.unresolved_relations ?? [],
                unresolvedClaims: assistant.unresolved_claims ?? [],
                auditReviewStage: assistant.audit_review_stage ?? "",
                activeTemplateVersions: assistant.active_template_versions ?? {},
                attachmentPackage: assistant.attachment_package ?? {},
              },
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
      } catch (error) {
        if (!cancelled) {
          setLoadErrorMessage(safeHistoryLoadErrorMessage(error));
          setLoadError(true);
        }
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
        {loadErrorMessage && (
          <p role="status" className="max-w-xl text-xs text-muted-foreground">
            {loadErrorMessage}
          </p>
        )}
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

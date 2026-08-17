import type { ThreadMessageLike } from "@assistant-ui/react";
import { stripThink } from "@/lib/utils/think";
import type { DbMessage } from "./types";

export function convertDbMessage(msg: DbMessage): ThreadMessageLike {
  const localCustom =
    msg.metadata?.custom &&
    typeof msg.metadata.custom === "object" &&
    !Array.isArray(msg.metadata.custom)
      ? (msg.metadata.custom as Record<string, unknown>)
      : {};
  const localFinalReportRef = localCustom.finalReportRef;
  const reportRefCandidate =
    msg.metadata?.final_report_ref ?? localFinalReportRef;
  const finalReportRef =
    msg.role === "assistant" &&
    typeof reportRefCandidate === "string" &&
    reportRefCandidate.trim().length > 0
      ? reportRefCandidate
      : null;

  return {
    role: msg.role,
    content: msg._contentParts ?? (msg.role === "assistant" ? stripThink(msg.content) : msg.content),
    id: msg.id,
    createdAt: msg.createdAt ? new Date(msg.createdAt) : undefined,
    status: msg._status,
    attachments: msg._attachments,
    // A thread can contain many generated reports. Keep the evidence reference
    // with this exact assistant message rather than using a thread-global ref.
    metadata: {
      custom: {
        // History hydration and the terminal SSE event both attach the rest
        // of the response snapshot here (traceItems, coverage and unresolved
        // items).  Preserve it verbatim for this individual message.
        ...localCustom,
        canReload: msg._canReload === true,
        finalReportRef,
      },
    },
  };
}

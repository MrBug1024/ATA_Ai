import type { FileItem } from "@/lib/types/chat-upload";

/**
 * Serializable shape of an AUI `CompleteAttachment` (sans the runtime `file`
 * Blob, which can't survive sessionStorage). The `id` must match the
 * corresponding FileItem entry below so that the runtime's adapter store can
 * be primed before auto-send.
 */
export interface PendingAttachmentMeta {
  id: string;
  type: string;
  name: string;
  contentType?: string;
  content: [];
  status: { type: "complete" };
}

export interface PendingChatPayload {
  content: string;
  attachments?: PendingAttachmentMeta[];
  /** Tuples of `[attachmentId, FileItem]` to seed the adapter file store. */
  fileItemEntries?: Array<[string, FileItem]>;
}

const SESSION_KEY_PREFIX = "pending-message-";

export function pendingMessageKey(threadId: string): string {
  return `${SESSION_KEY_PREFIX}${threadId}`;
}

/**
 * Parse a sessionStorage value back into a `PendingChatPayload`.
 *
 * Backward-compatible: a plain string (legacy, pre-attachment) is treated as
 * `{ content: <string> }`. Returns `null` for empty / whitespace-only inputs.
 */
export function parsePendingPayload(raw: string | null): PendingChatPayload | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("{")) {
    try {
      const obj = JSON.parse(trimmed) as unknown;
      if (
        obj &&
        typeof obj === "object" &&
        "content" in obj &&
        typeof (obj as { content: unknown }).content === "string"
      ) {
        return obj as PendingChatPayload;
      }
    } catch {
      // fall through to plain-string interpretation
    }
  }
  return { content: raw };
}

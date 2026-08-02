import type { MessageStatus, ThreadMessageLike } from "@assistant-ui/react";

export type DbMessageContentParts = Exclude<ThreadMessageLike["content"], string>;

export interface DbMessage {
  id: string;
  conversationId: string;
  role: "user" | "assistant";
  content: string;
  metadata: Record<string, unknown> | null;
  createdAt: string | Date;
  // Local-only: never persisted to DB, used for streaming/error UI state
  _status?: MessageStatus;
  // Local-only: attachments shown alongside user messages after send
  _attachments?: ThreadMessageLike["attachments"];
  // Local-only: structured assistant-ui parts for streaming reasoning/section UI.
  _contentParts?: DbMessageContentParts;
  // Local-only: the unhashed id originally submitted as client_turn_id.
  _clientTurnId?: string;
  // Local-only: history cannot be regenerated until the backend returns client_turn_id.
  _canReload?: boolean;
}

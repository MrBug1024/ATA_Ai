import type { ThreadMessageLike } from "@assistant-ui/react";
import { stripThink } from "@/lib/utils/think";
import type { DbMessage } from "./types";

export function convertDbMessage(msg: DbMessage): ThreadMessageLike {
  return {
    role: msg.role,
    content: msg._contentParts ?? (msg.role === "assistant" ? stripThink(msg.content) : msg.content),
    id: msg.id,
    createdAt: msg.createdAt ? new Date(msg.createdAt) : undefined,
    status: msg._status,
    attachments: msg._attachments,
    metadata: { custom: { canReload: msg._canReload === true } },
  };
}

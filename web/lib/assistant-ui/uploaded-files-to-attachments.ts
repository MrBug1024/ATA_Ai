import type { FileItem } from "@/lib/types/chat-upload";
import type { DbMessage } from "./types";

type Attachments = NonNullable<DbMessage["_attachments"]>;

export interface AttachmentSeed {
  id: string;
  url: string;
}

export interface MappedAttachments {
  attachments: Attachments;
  seeds: AttachmentSeed[];
}

function attachmentType(contentType: string): "image" | "document" | "file" {
  if (contentType.startsWith("image/")) return "image";
  if (contentType === "application/pdf") return "document";
  return "file";
}

/**
 * Convert the backend `uploaded_files` (FileItem[]) carried on a persisted user
 * message into assistant-ui attachment objects plus the (id → url) preview
 * seeds the renderer needs. The seeds must be fed into the attachment adapter's
 * preview store (`seedPreviewUrls`) so `MessageAttachmentItem` can resolve a
 * thumbnail for history messages, where the in-memory upload store is empty.
 */
export function uploadedFilesToAttachments(files: readonly FileItem[]): MappedAttachments {
  const attachments: Attachments[number][] = [];
  const seeds: AttachmentSeed[] = [];

  files.forEach((f, i) => {
    const id = `att-${f.file_hash || f.name || i}`;
    attachments.push({
      id,
      type: attachmentType(f.content_type),
      name: f.name,
      contentType: f.content_type,
      content: [],
      status: { type: "complete" },
    } as Attachments[number]);
    if (f.url) seeds.push({ id, url: f.url });
  });

  return { attachments, seeds };
}

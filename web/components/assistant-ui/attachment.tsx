"use client";

import { AttachmentPrimitive, ComposerPrimitive, MessagePrimitive, useAuiState } from "@assistant-ui/react";
import { AlertCircle, Loader2, Paperclip, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useEffect, useRef, useState } from "react";
import { usePreview } from "@/lib/assistant-ui/preview-context";
import { getAttachmentPreviewUrl } from "@/lib/assistant-ui/attachment-store";
import { getFileTypeInfo } from "@/lib/utils/file-type";

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

export function ComposerAttachments() {
  return (
    <ComposerPrimitive.Attachments>
      {() => <ComposerAttachmentItem />}
    </ComposerPrimitive.Attachments>
  );
}

export function UserMessageAttachments() {
  return (
    <MessagePrimitive.Attachments>
      {({ attachment }) => (
        <MessageAttachmentItem attachment={attachment as unknown as AttachmentLike} />
      )}
    </MessagePrimitive.Attachments>
  );
}

interface AttachmentStatus {
  type: "requires-action" | "running" | "complete" | "incomplete" | "pending";
  reason?: string;
  progress?: number;
}

interface AttachmentContent {
  type: string;
  name?: string;
  data?: unknown;
}

interface AttachmentLike {
  id?: string;
  name?: string;
  contentType?: string;
  file?: File;
  previewUrl?: string;
  status?: AttachmentStatus;
  content?: AttachmentContent[];
}

function useImagePreview(attachment: AttachmentLike): string | null {
  const [src, setSrc] = useState<string | null>(null);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    const isImage =
      attachment.contentType?.startsWith("image/") ||
      /\.(png|jpe?g|gif|webp|svg)$/i.test(attachment.name ?? "");

    if (!isImage) {
      setSrc(null);
      return;
    }

    if (!attachment.file && attachment.previewUrl) {
      setSrc(attachment.previewUrl);
      return;
    }

    if (!attachment.file) {
      setSrc(null);
      return;
    }

    const url = URL.createObjectURL(attachment.file);
    urlRef.current = url;
    setSrc(url);

    return () => {
      URL.revokeObjectURL(url);
      urlRef.current = null;
    };
  }, [attachment.file, attachment.contentType, attachment.name, attachment.previewUrl]);

  return src;
}

// ── Composer (未发送) ─────────────────────────────────────────────────────────

function ComposerAttachmentItem() {
  // Read directly from the attachment scope set up by ComposerAttachmentByIndexProvider.
  // This avoids the lazy-getter caching issue in RenderChildrenWithAccessor.
  const attachment = useAuiState((s) => s.attachment) as AttachmentLike | null;
  const preview = useImagePreview(attachment ?? {});
  if (!attachment) return null;
  const isUploading = attachment.status?.type === "running";
  const isError = attachment.status?.type === "incomplete";

  if (preview) {
    return (
      <div
        className={cn(
          "group relative size-16 shrink-0 overflow-hidden rounded-md border bg-muted",
          isError ? "border-destructive/60" : "border-border",
        )}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={preview}
          alt={attachment.name ?? "attachment"}
          className={cn("size-full object-cover", (isUploading || isError) && "opacity-50")}
        />
        {isUploading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30">
            <Loader2 className="size-4 animate-spin text-white" />
          </div>
        )}
        {isError && (
          <div className="absolute inset-0 flex items-center justify-center bg-destructive/20">
            <AlertCircle className="size-4 text-destructive" />
          </div>
        )}
        <span className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[9px] truncate px-1 py-0.5 leading-tight">
          {attachment.name}
        </span>
        <AttachmentPrimitive.Remove asChild>
          <button
            type="button"
            className="absolute right-0.5 top-0.5 flex size-4 items-center justify-center rounded-full bg-black/70 text-white opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
            aria-label="删除附件"
          >
            <X className="size-2.5" />
          </button>
        </AttachmentPrimitive.Remove>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group relative flex items-center gap-1.5 rounded-md px-2 py-1 text-xs max-w-[160px]",
        isError
          ? "border border-destructive/40 bg-destructive/8 text-destructive"
          : "bg-muted text-muted-foreground",
      )}
    >
      {isUploading ? (
        <Loader2 className="size-3 shrink-0 animate-spin" />
      ) : isError ? (
        <AlertCircle className="size-3 shrink-0" />
      ) : (() => {
        const { icon: Icon, color } = getFileTypeInfo(attachment.name, attachment.contentType);
        return <Icon className={cn("size-3 shrink-0", color)} />;
      })()}
      <span className="truncate">{attachment.name}</span>
      {isError && <span className="shrink-0 text-[10px]">上传失败</span>}
      <AttachmentPrimitive.Remove asChild>
        <button
          type="button"
          className="ml-0.5 shrink-0 rounded-full text-current/60 hover:text-current"
          aria-label="删除附件"
        >
          <X className="size-3" />
        </button>
      </AttachmentPrimitive.Remove>
    </div>
  );
}

// ── 已发送消息 ─────────────────────────────────────────────────────────────────

export function MessageAttachmentItem({ attachment }: { attachment: AttachmentLike }) {
  const id = attachment.id;
  const cachedUrl = id ? getAttachmentPreviewUrl(id) : undefined;
  const resolved: AttachmentLike = {
    ...attachment,
    previewUrl: attachment.previewUrl ?? cachedUrl,
  };

  const imgSrc = useImagePreview(resolved);
  const { openPreview } = usePreview();
  const previewUrl = resolved.previewUrl;
  const fileName = attachment.name ?? "附件";

  if (imgSrc) {
    return (
      <button
        type="button"
        onClick={() =>
          openPreview({
            name: fileName,
            contentType: attachment.contentType,
            previewUrl: imgSrc,
          })
        }
        className="size-36 shrink-0 overflow-hidden rounded-xl border border-border bg-muted focus:outline-none focus:ring-2 focus:ring-ring"
        aria-label={`预览图片: ${fileName}`}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={imgSrc}
          alt={fileName}
          className="size-full object-cover transition-opacity hover:opacity-90"
        />
      </button>
    );
  }

  const { icon: Icon, color } = getFileTypeInfo(attachment.name, attachment.contentType);

  // 统一走预览面板:可渲染的(PDF/文本/图片)内嵌预览,其余在面板里降级为下载。
  return (
    <button
      type="button"
      onClick={() =>
        openPreview({
          name: fileName,
          contentType: attachment.contentType,
          previewUrl,
        })
      }
      aria-label={`预览文件: ${fileName}`}
      className="flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
    >
      <Icon className={cn("size-3 shrink-0", color)} />
      <span className="max-w-[150px] truncate">{fileName}</span>
    </button>
  );
}

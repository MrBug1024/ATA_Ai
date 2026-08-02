"use client";

import { useState, useRef, useEffect, useCallback, type ChangeEvent } from "react";
import { toast } from "sonner";
import { useChatUpload } from "@/lib/hooks/use-chat-upload";
import type { FileItem } from "@/lib/types/chat-upload";

export interface PendingAttachment {
  id: string;
  file: File;
  status: "uploading" | "complete" | "error";
  errorReason?: string;
  fileItem?: FileItem;
  previewUrl?: string;
}

/**
 * 新建对话输入框的附件上传状态机:上传/预览 URL 生命周期、切换案件清空、增删与文件选择。
 * 从 chat/page 抽出,使页面只剩布局与提交编排。caseId 为 null 时禁用上传。
 */
export function useChatComposerAttachments(caseId: number | null) {
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { upload } = useChatUpload();
  const isUploading = attachments.some((a) => a.status === "uploading");

  // 图片预览的 object-URL 生命周期:卸载或附件变更时释放当时存在的 URL。
  useEffect(() => {
    const urls = attachments.map((a) => a.previewUrl).filter((u): u is string => !!u);
    return () => {
      for (const u of urls) URL.revokeObjectURL(u);
    };
  }, [attachments]);

  // 切换案件后,旧案件的上传不再适用 — 清空。
  const activeCaseIdRef = useRef<number | null>(caseId);
  useEffect(() => {
    if (activeCaseIdRef.current !== caseId) {
      activeCaseIdRef.current = caseId;
      setAttachments([]);
    }
  }, [caseId]);

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const uploadFiles = useCallback(
    async (files: File[]) => {
      const cid = activeCaseIdRef.current;
      if (cid == null || files.length === 0) return;
      const pending: PendingAttachment[] = files.map((f) => ({
        id: crypto.randomUUID(),
        file: f,
        status: "uploading",
        previewUrl: f.type.startsWith("image/") ? URL.createObjectURL(f) : undefined,
      }));
      setAttachments((prev) => [...prev, ...pending]);

      await Promise.all(
        pending.map(async (p) => {
          try {
            const res = await upload({ caseId: cid }, [p.file]);
            const matched = res.files.find((f) => f.name === p.file.name);
            if (res.duplicate_files.includes(p.file.name)) {
              toast.warning(`重复文件已忽略: ${p.file.name}`);
              setAttachments((prev) => prev.filter((a) => a.id !== p.id));
              return;
            }
            if (!matched) {
              setAttachments((prev) =>
                prev.map((a) =>
                  a.id === p.id ? { ...a, status: "error", errorReason: "上传响应缺少文件" } : a
                )
              );
              return;
            }
            setAttachments((prev) =>
              prev.map((a) => (a.id === p.id ? { ...a, status: "complete", fileItem: matched } : a))
            );
          } catch (err) {
            const reason = err instanceof Error ? err.message : "上传失败";
            setAttachments((prev) =>
              prev.map((a) => (a.id === p.id ? { ...a, status: "error", errorReason: reason } : a))
            );
          }
        })
      );
    },
    [upload]
  );

  const handleAttachClick = useCallback(() => {
    if (caseId == null) return;
    fileInputRef.current?.click();
  }, [caseId]);

  const handleFileInputChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const list = e.target.files;
      if (!list || list.length === 0) return;
      void uploadFiles(Array.from(list));
      e.target.value = "";
    },
    [uploadFiles]
  );

  return {
    attachments,
    isUploading,
    fileInputRef,
    removeAttachment,
    handleAttachClick,
    handleFileInputChange,
  };
}

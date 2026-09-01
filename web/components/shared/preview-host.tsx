"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  PreviewContext,
  usePreview,
  type PreviewableFile,
} from "@/lib/assistant-ui/preview-context";
import { useEvidenceDrawerStore } from "@/lib/stores/evidence-drawer";
import { FilePreviewPanel } from "./file-preview-panel";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";

/**
 * 附件预览状态的宿主。包住聊天区,使 MessageAttachmentItem 的 openPreview 生效。
 * 右侧只有一个抽屉位:附件预览与证据抽屉(角标)互斥,打开任一方会关闭另一方。
 */
export function PreviewProvider({ children }: { children: ReactNode }) {
  const [previewFile, setPreviewFile] = useState<PreviewableFile | null>(null);
  const evidenceOpen = useEvidenceDrawerStore((s) => s.open);
  const closeEvidenceDrawer = useEvidenceDrawerStore((s) => s.closeDrawer);

  useEffect(() => {
    if (evidenceOpen) setPreviewFile(null);
  }, [evidenceOpen]);

  const value = useMemo(
    () => ({
      previewFile,
      openPreview: (f: PreviewableFile) => {
        closeEvidenceDrawer();
        setPreviewFile(f);
      },
      closePreview: () => setPreviewFile(null),
    }),
    [previewFile, closeEvidenceDrawer]
  );
  return <PreviewContext.Provider value={value}>{children}</PreviewContext.Provider>;
}

/** 与对话并排的预览分栏;无预览文件时不渲染。必须放在 PreviewProvider 内。 */
export function PreviewSidePanel() {
  const { previewFile, closePreview } = usePreview();
  const isMobile = useIsMobile();
  if (!previewFile) return null;
  if (isMobile) {
    return (
      <Sheet open onOpenChange={(open) => { if (!open) closePreview(); }}>
        <SheetContent
          side="right"
          className="w-screen max-w-none gap-0 p-0 sm:max-w-none"
          showCloseButton={false}
        >
          <SheetTitle className="sr-only">{previewFile.name}</SheetTitle>
          <SheetDescription className="sr-only">附件只读预览</SheetDescription>
          <FilePreviewPanel file={previewFile} onClose={closePreview} />
        </SheetContent>
      </Sheet>
    );
  }
  return (
    <aside
      data-testid="file-preview-panel"
      className="w-[420px] max-w-[45vw] shrink-0 overflow-hidden"
    >
      <FilePreviewPanel file={previewFile} onClose={closePreview} />
    </aside>
  );
}

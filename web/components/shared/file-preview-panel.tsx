// components/shared/file-preview-panel.tsx
"use client";

import { useState, useEffect } from "react";
import { X, Download, FileText, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import type { PreviewableFile } from "@/lib/assistant-ui/preview-context";
import { resolvePreviewType } from "@/lib/utils/file-type";
import { useElementSize } from "@/lib/hooks/use-element-size";
import { cn } from "@/lib/utils";
import { PdfPageView } from "./pdf-page-view";

interface PdfViewerProps {
  url: string;
  onPageClick?: () => void;
  /** width:分栏内按宽度铺满(默认);page:全屏弹层内整页适配高度。 */
  fit?: "width" | "page";
}

function PdfViewer({ url, onPageClick, fit = "width" }: PdfViewerProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [page, setPage] = useState(1);
  const [containerRef, { width, height }] = useElementSize<HTMLDivElement>();

  // 预留分页行的高度,保证整页 + 翻页控件同屏可见
  const sizeProps =
    fit === "page"
      ? { height: Math.max(200, height - 48) }
      : { width: Math.max(200, width - 32) };

  const pageView = (
    <PdfPageView
      url={url}
      pageNumber={page}
      {...sizeProps}
      renderTextLayer
      renderAnnotationLayer
      onLoadSuccess={(n) => { setNumPages(n); setPage(1); }}
      errorFallback={
        <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
          <FileText className="size-8 text-muted-foreground/40" />
          <p className="text-sm text-muted-foreground/60">PDF 加载失败</p>
          <a
            href={url}
            download
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1.5 rounded-md border border-border/50 px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          >
            <Download className="size-3" /> 下载文件
          </a>
        </div>
      }
    />
  );

  return (
    <div
      ref={containerRef}
      className={cn("flex flex-col items-center gap-2 p-4", fit === "page" && "h-full")}
    >
      {onPageClick ? (
        <div
          role="button"
          tabIndex={0}
          aria-label="放大查看 PDF"
          onClick={onPageClick}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") onPageClick();
          }}
          className="cursor-zoom-in"
          title="点击放大查看"
        >
          {pageView}
        </div>
      ) : (
        pageView
      )}
      {numPages > 1 && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="flex size-6 items-center justify-center rounded hover:bg-accent disabled:opacity-30"
          >
            <ChevronLeft className="size-3.5" />
          </button>
          <span className="tabular-nums">{page} / {numPages}</span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(numPages, p + 1))}
            disabled={page >= numPages}
            className="flex size-6 items-center justify-center rounded hover:bg-accent disabled:opacity-30"
          >
            <ChevronRight className="size-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}

interface FilePreviewPanelProps {
  file: PreviewableFile;
  onClose: () => void;
}

export function FilePreviewPanel({ file, onClose }: FilePreviewPanelProps) {
  const type = resolvePreviewType(file.name, file.contentType);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [imgSrc, setImgSrc] = useState<string | null>(null);
  const [zoomOpen, setZoomOpen] = useState(false);

  useEffect(() => {
    setZoomOpen(false);
  }, [file]);

  useEffect(() => {
    if (type !== "image") { setImgSrc(null); return; }
    if (file.previewUrl) { setImgSrc(file.previewUrl); return; }
    if (!file.file) { setImgSrc(null); return; }
    const url = URL.createObjectURL(file.file);
    setImgSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [file.previewUrl, file.file, type]);

  useEffect(() => {
    setTextContent(null);
    if (type === "text" && file.previewUrl) {
      const controller = new AbortController();
      fetch(file.previewUrl, { signal: controller.signal })
        .then((r) => r.text())
        .then(setTextContent)
        .catch((err: unknown) => {
          if (err instanceof Error && err.name !== "AbortError") {
            setTextContent("无法加载文件内容");
          }
        });
      return () => controller.abort();
    }
  }, [file.previewUrl, type]);

  return (
    <div className="flex h-full flex-col border-l border-border/50 bg-background">
      <div className="flex shrink-0 items-center gap-2 border-b border-border/40 px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">{file.name}</p>
          <p className="text-[10px] uppercase text-muted-foreground/50">{file.contentType ?? "未知格式"}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {file.previewUrl && (
            <a
              href={file.previewUrl}
              download={file.name}
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground/50 hover:bg-accent hover:text-foreground transition-colors"
              title="下载"
            >
              <Download className="size-3.5" />
            </a>
          )}
          <button
            type="button"
            onClick={onClose}
            className="flex size-7 items-center justify-center rounded-md text-muted-foreground/50 hover:bg-accent hover:text-foreground transition-colors"
            aria-label="关闭预览"
          >
            <X className="size-3.5" />
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {type === "image" && imgSrc && (
          <div className="flex items-center justify-center p-4">
            <button
              type="button"
              onClick={() => setZoomOpen(true)}
              aria-label={`放大查看: ${file.name}`}
              title="点击查看大图"
              className="cursor-zoom-in focus:outline-none focus:ring-2 focus:ring-ring rounded-lg"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={imgSrc}
                alt={file.name}
                className="max-h-full max-w-full rounded-lg object-contain"
              />
            </button>
          </div>
        )}
        {type === "pdf" && file.previewUrl && (
          <PdfViewer url={file.previewUrl} onPageClick={() => setZoomOpen(true)} />
        )}
        {type === "text" && file.previewUrl && (
          <pre className="p-4 text-xs leading-relaxed text-foreground/80 whitespace-pre-wrap break-words">
            {textContent ?? (
              <span className="flex items-center gap-2 text-muted-foreground/50">
                <Loader2 className="size-3 animate-spin" /> 加载中...
              </span>
            )}
          </pre>
        )}
        {(type === "none" ||
          (type === "image" && !imgSrc) ||
          ((type === "pdf" || type === "text") && !file.previewUrl)) && (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
            <div className="flex size-12 items-center justify-center rounded-xl border border-border/40 bg-muted/40">
              <FileText className="size-5 text-muted-foreground/40" />
            </div>
            <p className="text-sm text-muted-foreground/60">
              {type === "none" ? "不支持预览此格式" : "暂无预览"}
            </p>
            {file.previewUrl && (
              <a
                href={file.previewUrl}
                download={file.name}
                className="inline-flex items-center gap-1.5 rounded-md border border-border/50 px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              >
                <Download className="size-3" /> 下载文件
              </a>
            )}
          </div>
        )}
      </div>

      {/* 放大查看:图片大图 / PDF 全屏阅读 */}
      {(type === "image" || type === "pdf") && (
        <Dialog open={zoomOpen} onOpenChange={setZoomOpen}>
          <DialogContent className="flex h-[92vh] w-[92vw] max-w-[92vw] flex-col gap-0 overflow-hidden p-0 sm:max-w-[92vw]">
            <DialogTitle className="shrink-0 truncate border-b px-4 py-2.5 pr-12 text-sm font-medium">
              {file.name}
            </DialogTitle>
            <div className="min-h-0 flex-1 overflow-auto">
              {type === "image" && imgSrc && (
                <div className="flex h-full items-center justify-center p-4">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={imgSrc}
                    alt={`${file.name} 大图`}
                    className="max-h-full max-w-full object-contain"
                  />
                </div>
              )}
              {type === "pdf" && file.previewUrl && (
                <PdfViewer url={file.previewUrl} fit="page" />
              )}
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

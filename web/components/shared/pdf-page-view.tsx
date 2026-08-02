"use client";

import { useState, useEffect } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { ImageOff, Loader2 } from "lucide-react";
import { BboxOverlay } from "@/components/knowledge-graph/bbox-overlay";
import type { BBox } from "@/lib/types/knowledge-graph";

// 全项目唯一的 pdf.js worker 配置点。
pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

interface PdfPageViewProps {
  url: string;
  pageNumber: number;
  /** 二选一:按宽度渲染(分栏)或按高度渲染(全屏整页适配);同时传时宽度优先。 */
  width?: number;
  height?: number;
  /** 证据高亮框;不传则不渲染 overlay。 */
  bboxes?: BBox[];
  renderTextLayer?: boolean;
  renderAnnotationLayer?: boolean;
  /** Document 加载完成回调(总页数),供外层做分页 UI。 */
  onLoadSuccess?: (numPages: number) => void;
  /** 加载失败时的自定义 UI;默认为简单错误提示。 */
  errorFallback?: React.ReactNode;
}

/**
 * Client-only PDF page renderer with optional bbox highlight overlay. Isolated
 * into its own module so `react-pdf` / `pdfjs-dist` (which reference DOMMatrix
 * at module eval) never enter the SSR bundle — load via next/dynamic({ ssr: false })
 * from server-rendered routes.
 */
export function PdfPageView({
  url,
  pageNumber,
  width,
  height,
  bboxes,
  renderTextLayer = false,
  renderAnnotationLayer = false,
  onLoadSuccess,
  errorFallback,
}: PdfPageViewProps) {
  const [renderedSize, setRenderedSize] = useState<{ w: number; h: number } | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    setRenderedSize(null);
    setError(false);
  }, [url, pageNumber]);

  if (error) {
    return (
      errorFallback ?? (
        <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
          <ImageOff className="h-4 w-4" /> PDF 加载失败
        </div>
      )
    );
  }

  return (
    <Document
      file={url}
      onLoadSuccess={({ numPages }) => onLoadSuccess?.(numPages)}
      onLoadError={() => setError(true)}
      loading={
        <div className="flex items-center gap-2 py-8 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载中…
        </div>
      }
    >
      <div className="relative inline-block">
        <Page
          pageNumber={pageNumber}
          width={width}
          height={height}
          renderTextLayer={renderTextLayer}
          renderAnnotationLayer={renderAnnotationLayer}
          onRenderSuccess={(p) => setRenderedSize({ w: p.width, h: p.height })}
          onRenderError={() => setError(true)}
        />
        {renderedSize && bboxes && bboxes.length > 0 && (
          <div className="pointer-events-none absolute inset-0">
            <BboxOverlay
              bboxes={bboxes}
              containerWidth={renderedSize.w}
              containerHeight={renderedSize.h}
            />
          </div>
        )}
      </div>
    </Document>
  );
}

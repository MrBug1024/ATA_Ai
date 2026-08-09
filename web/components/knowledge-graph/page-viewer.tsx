"use client";

import { useState, useEffect } from "react";
import dynamic from "next/dynamic";
import { ChevronLeft, ChevronRight, ImageOff, FileText, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { BboxOverlay } from "./bbox-overlay";
import { usePageAnchors } from "@/lib/hooks/use-page-anchors";
import { useElementSize } from "@/lib/hooks/use-element-size";
import { apiFetch } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import type { BBox, EvidenceItem, PageAnchorsResponse } from "@/lib/types/knowledge-graph";

// react-pdf / pdfjs reference DOMMatrix at module eval → must stay out of SSR.
const PdfPageView = dynamic(
  () => import("@/components/shared/pdf-page-view").then((m) => m.PdfPageView),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center gap-2 py-8 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载中…
      </div>
    ),
  }
);

interface PageViewerProps {
  // 抽屉打开时的首屏页；用户用上/下页导航后，PageViewer 通过 usePageAnchors 接管
  initialPage: PageAnchorsResponse | null;
  selectedEvidence: EvidenceItem | null;
}

type RenderMode = "image" | "pdf" | "spreadsheet" | "text" | "none";

function resolveFileExtension(fileName: string): string {
  const cleanName = fileName.split(/[?#]/, 1)[0];
  const match = cleanName.match(/\.([a-z0-9]+)(?=\s|$)/i);
  return match?.[1]?.toLowerCase() ?? "";
}

function resolveMode(contentType: string | undefined, url: string | undefined, fileName: string): RenderMode {
  const mime = contentType ?? "";
  const ext = resolveFileExtension(fileName);
  if (mime.startsWith("text/")) return "text";
  if (
    mime.includes("spreadsheet") ||
    mime.includes("excel") ||
    /^(xlsx?|xlsm|csv)$/.test(ext)
  ) {
    return "spreadsheet";
  }
  if (mime === "application/pdf" || ext === "pdf") return url ? "pdf" : "none";
  if (mime.startsWith("image/") || /^(png|jpe?g|gif|webp|svg|bmp)$/.test(ext)) return url ? "image" : "none";
  return url ? "image" : "none";
}

interface ImageWithBboxesProps {
  src: string;
  alt: string;
  bboxes: BBox[];
  onError?: () => void;
  wrapperClassName?: string;
  imgClassName?: string;
}

/** 页面原图 + 证据高亮框;自测渲染尺寸供 bbox 换算。 */
function ImageWithBboxes({
  src,
  alt,
  bboxes,
  onError,
  wrapperClassName,
  imgClassName,
}: ImageWithBboxesProps) {
  const [wrapRef, size] = useElementSize<HTMLDivElement>();
  return (
    <div ref={wrapRef} className={cn("relative inline-block", wrapperClassName)}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} className={cn("block max-w-full", imgClassName)} onError={onError} />
      {size.width > 0 && size.height > 0 && (
        <div className="pointer-events-none absolute inset-0">
          <BboxOverlay bboxes={bboxes} containerWidth={size.width} containerHeight={size.height} />
        </div>
      )}
    </div>
  );
}

/** 全屏弹层内的 PDF 页:按可用高度整页适配。 */
function ZoomedPdfPage({ url, pageNumber, bboxes }: { url: string; pageNumber: number; bboxes: BBox[] }) {
  const [ref, { height }] = useElementSize<HTMLDivElement>();
  return (
    <div ref={ref} className="flex h-full items-start justify-center overflow-auto p-2">
      <PdfPageView url={url} pageNumber={pageNumber} height={Math.max(200, height - 16)} bboxes={bboxes} />
    </div>
  );
}

function SpreadsheetEvidenceView({
  evidence,
  fileName,
  sourceUrl,
}: {
  evidence: EvidenceItem | null;
  fileName: string;
  sourceUrl?: string;
}) {
  return (
    <div className="flex h-full w-full max-w-3xl flex-col gap-3 overflow-auto rounded-md border bg-background p-4 text-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b pb-3 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">{fileName}</span>
        {evidence?.sheet_name && <span>工作表：{evidence.sheet_name}</span>}
        {(evidence?.row_start ?? 0) > 0 && (
          <span>
            行：{evidence?.row_start}
            {evidence?.row_end && evidence.row_end !== evidence.row_start ? `-${evidence.row_end}` : ""}
          </span>
        )}
        {evidence?.cell_range && <span>单元格：{evidence.cell_range}</span>}
      </div>
      <div className="whitespace-pre-wrap rounded bg-muted/30 p-3 font-mono text-xs leading-6">
        {evidence?.quote_text || "当前表格定位暂无原文片段"}
      </div>
      {sourceUrl && (
        <a
          href={sourceUrl}
          download={fileName.split(" 路 ")[0] || fileName}
          target="_blank"
          rel="noreferrer"
          className="inline-flex w-fit items-center rounded-md border px-2.5 py-1.5 text-xs text-primary hover:bg-primary/5"
        >
          打开原始文件
        </a>
      )}
      <div className="text-xs text-muted-foreground">
        这是按工作表、行和单元格定位的表格证据，不将 Excel 行号冒充 PDF 页码。
      </div>
    </div>
  );
}

export function PageViewer({ initialPage, selectedEvidence }: PageViewerProps) {
  const [containerRef, { width: containerRawWidth }] = useElementSize<HTMLDivElement>();
  const containerWidth = Math.max(120, containerRawWidth - 16);
  const [mediaError, setMediaError] = useState(false);
  const [zoomOpen, setZoomOpen] = useState(false);

  // 本地翻页：null 表示用 initialPage / selectedEvidence 所在页
  const [navOverride, setNavOverride] = useState<{ fileId: number; pageNo: number } | null>(null);
  useEffect(() => {
    setNavOverride(null);
  }, [selectedEvidence?.chunk_id]);

  const { data: navPage } = usePageAnchors(
    navOverride?.fileId ?? null,
    navOverride?.pageNo ?? null
  );
  const currentPage = navPage ?? initialPage;

  // 有效页:手动翻页 > 选中证据所在页 > 首屏页。
  // 角标多证据时第 2+ 条证据的 page_no 必须参与取页,否则视图停留在首屏页。
  const pageNo =
    navOverride && navPage
      ? navPage.page_no
      : selectedEvidence?.page_no ?? currentPage?.page_no ?? 0;
  const fileId =
    navOverride && navPage
      ? navPage.file_id
      : selectedEvidence?.file_id ?? currentPage?.file_id ?? 0;

  const sourceUrl =
    navOverride && navPage
      ? navPage.source_file_url ?? selectedEvidence?.source_file_url
      : selectedEvidence?.source_file_url ?? currentPage?.source_file_url;
  const contentType = selectedEvidence?.content_type ?? currentPage?.content_type;
  const fileName = selectedEvidence?.file_name ?? currentPage?.file_name ?? `文件 ${fileId}`;
  const mode = resolveMode(contentType, sourceUrl, fileName);

  useEffect(() => {
    setMediaError(false);
    setZoomOpen(false);
  }, [fileId, pageNo]);

  // Object storage URLs are not guaranteed to be reachable from the browser
  // and cannot carry the app's bearer token. Materialize the authorized API
  // file route as a blob URL before handing it to img/PDF.js.
  const [browserSourceUrl, setBrowserSourceUrl] = useState<string | undefined>(sourceUrl);
  const [sourceLoading, setSourceLoading] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | undefined;
    const isApiFileUrl = /\/files\/source-files\/\d+\/content(?:[?#]|$)/.test(sourceUrl ?? "");

    setSourceLoading(isApiFileUrl && !!sourceUrl);
    if (!sourceUrl || !isApiFileUrl) {
      setBrowserSourceUrl(sourceUrl);
      return () => undefined;
    }

    setBrowserSourceUrl(undefined);
    const controller = new AbortController();
    apiFetch(sourceUrl, { signal: controller.signal }, { auth: true })
      .then((response) => {
        if (!response.ok) throw new Error(`file preview failed (${response.status})`);
        return response.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setBrowserSourceUrl(objectUrl);
        setSourceLoading(false);
      })
      .catch((error: unknown) => {
        if (cancelled || (error instanceof Error && error.name === "AbortError")) return;
        setSourceLoading(false);
        setMediaError(true);
      });

    return () => {
      cancelled = true;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [sourceUrl]);

  if (!currentPage) {
    return (
      <div className="flex flex-1 items-center justify-center text-muted-foreground text-sm">
        选择左侧证据查看页面
      </div>
    );
  }

  // bbox：浏览其它页时用该页 anchors，否则用选中证据自身的框
  const bboxes =
    navOverride && navPage
      ? navPage.anchors.flatMap((a) => a.bbox_list)
      : selectedEvidence
        ? selectedEvidence.bbox_list
        : currentPage.anchors.flatMap((a) => a.bbox_list);

  const pageAlt = `${fileName} 第 ${pageNo} 页`;
  const zoomable = (mode === "image" || mode === "pdf") && !!browserSourceUrl && !mediaError;

  function goToPage(delta: number) {
    setNavOverride({ fileId, pageNo: pageNo + delta });
  }

  return (
    <div className="flex flex-1 flex-col gap-2 overflow-hidden p-2">
      <div
        ref={containerRef}
        className="flex flex-1 items-start justify-center overflow-auto rounded-md bg-muted/20 p-2"
      >
        {mode === "text" && (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-sm text-muted-foreground">
            <FileText className="h-5 w-5 opacity-50" />
            <p>文本类材料没有页面版式，以下为证据原文片段：</p>
            <p className="max-w-xl whitespace-pre-wrap rounded bg-muted/40 p-3 text-left text-xs leading-6 text-foreground">
              {selectedEvidence?.quote_text || currentPage.anchors[0]?.quote_text || "暂无原文片段"}
            </p>
          </div>
        )}

        {sourceLoading && (
          <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> 加载原始文件中…
          </div>
        )}

        {mode === "spreadsheet" && !sourceLoading && (
          <SpreadsheetEvidenceView
            evidence={selectedEvidence}
            fileName={fileName}
            sourceUrl={browserSourceUrl}
          />
        )}

        {mode === "none" && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
            <ImageOff className="h-5 w-5 opacity-50" />
            该证据暂无可预览的原始文件
          </div>
        )}

        {mode === "image" && !sourceLoading && mediaError && (
          <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
            <ImageOff className="h-4 w-4" /> 图片加载失败
          </div>
        )}

        {zoomable && browserSourceUrl && (
          <div
            role="button"
            tabIndex={0}
            aria-label="全屏查看页面"
            title="点击全屏查看"
            className="cursor-zoom-in"
            onClick={() => setZoomOpen(true)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") setZoomOpen(true);
            }}
          >
            {mode === "image" ? (
              <ImageWithBboxes
                key={`${fileId}-${pageNo}`}
                src={browserSourceUrl}
                alt={pageAlt}
                bboxes={bboxes}
                onError={() => setMediaError(true)}
              />
            ) : (
              <PdfPageView
                url={browserSourceUrl}
                pageNumber={pageNo}
                width={containerWidth}
                bboxes={bboxes}
              />
            )}
          </div>
        )}
      </div>

      {mode !== "text" && mode !== "spreadsheet" && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            disabled={pageNo <= 1}
            onClick={() => goToPage(-1)}
          >
            <ChevronLeft className="h-3 w-3" />
          </Button>
          <span className="truncate px-2">{fileName} — 第 {pageNo} 页</span>
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => goToPage(1)}>
            <ChevronRight className="h-3 w-3" />
          </Button>
        </div>
      )}

      {/* 全屏查看(z 高于 GraphModal 内的证据 Sheet) */}
      {zoomable && browserSourceUrl && (
        <Dialog open={zoomOpen} onOpenChange={setZoomOpen}>
          <DialogContent className="z-[70] flex h-[92vh] w-[92vw] max-w-[92vw] flex-col gap-0 overflow-hidden p-0 sm:max-w-[92vw]">
            <DialogTitle className="shrink-0 truncate border-b px-4 py-2.5 pr-12 text-sm font-medium">
              {fileName} — 第 {pageNo} 页
            </DialogTitle>
            <div className="min-h-0 flex-1 overflow-auto">
              {mode === "image" ? (
                <div className="flex h-full items-center justify-center p-4">
                  <ImageWithBboxes
                    src={browserSourceUrl}
                    alt={pageAlt}
                    bboxes={bboxes}
                    wrapperClassName="max-h-full"
                    imgClassName="max-h-full max-w-full object-contain"
                  />
                </div>
              ) : (
                <ZoomedPdfPage
                  url={browserSourceUrl}
                  pageNumber={pageNo}
                  bboxes={bboxes}
                />
              )}
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

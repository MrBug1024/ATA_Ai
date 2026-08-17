"use client";

import { useEffect } from "react";
import { Loader2, X } from "lucide-react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useEvidenceDrawerStore } from "@/lib/stores/evidence-drawer";
import { useGraphModalStore } from "@/lib/stores/graph-modal";
import { useEvidenceResolve } from "@/lib/hooks/use-evidence-resolve";
import { PageViewer } from "./page-viewer";
import type { EvidenceItem } from "@/lib/types/knowledge-graph";

interface EvidenceDrawerProps {
  /**
   * inline：作为对话区的并排面板，打开时挤压对话往左（聊天页默认）。
   * overlay：Sheet 浮层，用于全屏 GraphModal 内（盖在图谱之上）。
   */
  variant?: "inline" | "overlay";
}

function evidenceLocationLabel(evidence: EvidenceItem): string {
  const isSheetRow =
    evidence.locator_kind === "sheet_row" ||
    Boolean(evidence.sheet_name) ||
    (evidence.row_start ?? 0) > 0;

  if (!isSheetRow) {
    return `第 ${evidence.page_no} 页`;
  }

  const worksheet = evidence.sheet_name ? `工作表：${evidence.sheet_name}` : "工作表";
  const rowStart = evidence.row_start ?? 0;
  const rowEnd = evidence.row_end ?? rowStart;
  if (rowStart <= 0) {
    return worksheet;
  }
  return `${worksheet} · 行：${rowStart}${rowEnd > rowStart ? `-${rowEnd}` : ""}`;
}

export function EvidenceDrawer({ variant = "overlay" }: EvidenceDrawerProps) {
  const open = useEvidenceDrawerStore((s) => s.open);
  const caseId = useEvidenceDrawerStore((s) => s.caseId);
  const reportRef = useEvidenceDrawerStore((s) => s.reportRef);
  const citationId = useEvidenceDrawerStore((s) => s.citationId);
  const selectedIndex = useEvidenceDrawerStore((s) => s.selectedEvidenceIndex);
  const currentPage = useEvidenceDrawerStore((s) => s.currentPage);
  const closeDrawer = useEvidenceDrawerStore((s) => s.closeDrawer);
  const setSelectedIndex = useEvidenceDrawerStore((s) => s.setSelectedEvidenceIndex);
  const setCurrentPage = useEvidenceDrawerStore((s) => s.setCurrentPage);
  const graphOpen = useGraphModalStore((s) => s.open);

  // inline 实例在 GraphModal 打开时让位给 Modal 内的 overlay 实例，避免双重请求/重复渲染。
  const active = !(variant === "inline" && graphOpen);

  const { data, isMutating, error, resolve, reset } = useEvidenceResolve();

  useEffect(() => {
    if (!open || !active) {
      reset();
      return;
    }
    resolve({ case_id: caseId, report_ref: reportRef, citation_id: citationId })
      .then((res) => {
        if (res?.primary_page) setCurrentPage(res.primary_page);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, active, caseId, reportRef, citationId]);

  const evidences: EvidenceItem[] = data?.evidences ?? [];
  const selectedEvidence = evidences[selectedIndex] ?? null;

  if (!open || !active) return null;

  const body = (
    <>
      {/* Header */}
      <div className="flex items-start justify-between gap-2 border-b px-4 py-3">
        <div className="min-w-0 flex-1 text-sm font-medium leading-snug">
          {isMutating ? "加载中…" : (data?.claim_text || `角标 [${citationId}]`)}
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" onClick={closeDrawer}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      {isMutating && (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      )}

      {error && !isMutating && (
        <div className="flex flex-1 items-center justify-center px-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {data && !isMutating && (
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* 上：证据内容列表 */}
          <div className="max-h-[38%] shrink-0 overflow-y-auto border-b p-2">
            {evidences.length === 0 && (
              <p className="px-1 py-2 text-xs text-muted-foreground">暂无页图证据</p>
            )}
            {evidences.map((ev, i) => (
              <button
                key={`${ev.chunk_id}-${ev.file_id}-${ev.page_no}-${i}`}
                onClick={() => setSelectedIndex(i)}
                className={cn(
                  "mb-1.5 w-full rounded-md p-2 text-left text-xs transition-colors",
                  i === selectedIndex
                    ? "bg-primary/15 text-primary"
                    : "text-muted-foreground hover:bg-muted"
                )}
              >
                <div className="flex items-baseline gap-1.5">
                  <span className="truncate font-medium">{ev.file_name}</span>
                  <span className="shrink-0 opacity-70">{evidenceLocationLabel(ev)}</span>
                </div>
                {ev.quote_text && (
                  <div className="mt-0.5 line-clamp-2 opacity-60">{ev.quote_text}</div>
                )}
              </button>
            ))}
          </div>

          {/* 下：页图 */}
          <PageViewer
            initialPage={currentPage ?? data.primary_page}
            selectedEvidence={selectedEvidence}
          />
        </div>
      )}
    </>
  );

  if (variant === "inline") {
    return (
      <aside
        data-testid="evidence-drawer-content"
        className="flex w-[360px] max-w-[80vw] shrink-0 flex-col border-l bg-background"
      >
        {body}
      </aside>
    );
  }

  return (
    <Sheet open onOpenChange={(v) => !v && closeDrawer()}>
      <SheetContent
        side="right"
        className="z-[60] flex w-[480px] max-w-[90vw] flex-col gap-0 p-0"
        data-testid="evidence-drawer-content"
      >
        <SheetTitle className="sr-only">证据详情</SheetTitle>
        {body}
      </SheetContent>
    </Sheet>
  );
}

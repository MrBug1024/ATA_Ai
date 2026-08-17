// components/knowledge-graph/citation-button.tsx
"use client";

import { useEvidenceDrawerStore } from "@/lib/stores/evidence-drawer";
import { useEvidenceContext } from "@/lib/assistant-ui/evidence-context";

interface CitationButtonProps {
  citationId: string;
}

export function CitationButton({ citationId }: CitationButtonProps) {
  const { caseId, reportRef } = useEvidenceContext();
  const openDrawer = useEvidenceDrawerStore((s) => s.openDrawer);

  function handleClick() {
    if (caseId === null || !reportRef) return;
    openDrawer({ caseId, reportRef, citationId });
  }

  const disabled = caseId === null || !reportRef;

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled}
      className="mx-0.5 inline-flex h-4 cursor-pointer items-center justify-center rounded bg-primary/15 px-1 text-[10px] font-semibold text-primary hover:bg-primary/25 disabled:cursor-default disabled:opacity-50 transition-colors"
      title={disabled ? `角标 [${citationId}]` : `查看角标 [${citationId}] 的证据`}
    >
      [{citationId}]
    </button>
  );
}

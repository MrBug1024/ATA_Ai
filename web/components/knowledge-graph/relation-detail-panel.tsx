"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { riskBadgeClass } from "@/lib/utils/risk-style";
import { useRelationEvidence } from "@/lib/hooks/use-relation-evidence";
import { useEvidenceDrawerStore } from "@/lib/stores/evidence-drawer";
import type { EvidenceItem } from "@/lib/types/knowledge-graph";

type NodeSelection = {
  type: "node";
  nodeId: string;
  entityId: number;
  label: string;
  entityType: string;
  riskLevel: string;
};

type ClusterRelation = {
  relationId: number;
  label: string;
  confidence: number;
};

export type EdgeSelection = {
  type: "edge";
  edgeId: string;
  relationId: number;
  label: string;
  relations?: ClusterRelation[];
};

export type PanelSelection = NodeSelection | EdgeSelection | null;

const RISK_LABELS: Record<string, string> = {
  high: "高风险", medium: "中风险", low: "低风险", unknown: "未知",
};

interface RelationDetailPanelProps {
  selection: PanelSelection;
  caseId: number;
  reportRef: string | null;
  onRecenter?: (entityId: number) => void;
  onClose?: () => void;
}

export function RelationDetailPanel({
  selection,
  caseId,
  reportRef,
  onRecenter,
  onClose,
}: RelationDetailPanelProps) {
  const { data, isMutating, error, fetch, reset } = useRelationEvidence();
  const openDrawer = useEvidenceDrawerStore((s) => s.openDrawer);
  const [activeRelationId, setActiveRelationId] = useState<number | null>(null);

  const relations = useMemo(
    () => (selection?.type === "edge" ? selection.relations ?? [] : []),
    [selection],
  );
  const activeRelation = relations.find((relation) => relation.relationId === activeRelationId);

  useEffect(() => {
    if (!selection) {
      setActiveRelationId(null);
      reset();
      return;
    }
    if (selection.type === "edge") {
      setActiveRelationId(selection.relationId);
      reset();
      fetch({ case_id: caseId, relation_id: selection.relationId }).catch(() => {});
    } else {
      setActiveRelationId(null);
      reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection, caseId]);

  if (!selection) return null;

  return (
    <div className="flex max-h-[45%] w-full shrink-0 flex-col overflow-hidden border-t sm:max-h-none sm:w-80 sm:border-l sm:border-t-0">
      <div className="border-b px-4 py-3">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="text-xs text-muted-foreground">
              {selection.type === "node"
                ? "节点详情"
                : relations.length > 1
                  ? `关系详情 · ${relations.length} 条关系`
                  : "关系详情"}
            </div>
            <div className="mt-0.5 truncate text-sm font-medium">
              {selection.type === "edge" ? activeRelation?.label ?? selection.label : selection.label}
            </div>
          </div>
          {onClose && (
            <Button variant="ghost" size="icon-xs" aria-label="关闭详情" onClick={onClose}>
              <X />
            </Button>
          )}
        </div>
        {selection.type === "edge" && relations.length > 1 && (
          <RelationSelect
            relations={relations}
            value={activeRelationId ?? selection.relationId}
            onValueChange={(relationId) => {
              setActiveRelationId(relationId);
              reset();
              fetch({ case_id: caseId, relation_id: relationId }).catch(() => {});
            }}
          />
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {selection.type === "node" && (
          <div className="space-y-2 text-sm">
            <div className="flex gap-2 text-xs">
              <span className="text-muted-foreground">类型</span>
              <span>{selection.entityType}</span>
            </div>
            <div className="flex gap-2 text-xs">
              <span className="text-muted-foreground">风险</span>
              <span className={cn("rounded px-1.5 py-0.5 text-xs", riskBadgeClass(selection.riskLevel))}>
                {RISK_LABELS[selection.riskLevel] ?? selection.riskLevel}
              </span>
            </div>
            {onRecenter && (
              <button
                type="button"
                onClick={() => onRecenter(selection.entityId)}
                className="mt-2 w-full rounded-md border px-2 py-1.5 text-xs text-primary hover:bg-primary/10 transition-colors"
              >
                以此为中心展开
              </button>
            )}
          </div>
        )}

        {selection.type === "edge" && (
          <>
            {isMutating && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            {error && <p className="text-xs text-destructive">{error}</p>}
            {data?.trace_items.map((item) => (
              <div key={item.claim_id} className="mb-3 rounded-md border p-2">
                <p className="text-xs leading-snug text-foreground">{item.claim_text}</p>
                <div className="mt-2 space-y-1">
                  {item.evidences.map((ev) => (
                    <EvidenceChip
                      key={ev.chunk_id}
                      evidence={ev}
                      caseId={caseId}
                      reportRef={reportRef}
                      citationId={item.citation_id}
                      onOpen={openDrawer}
                    />
                  ))}
                </div>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}

interface RelationSelectProps {
  relations: ClusterRelation[];
  value: number;
  onValueChange: (relationId: number) => void;
}

function RelationSelect({ relations, value, onValueChange }: RelationSelectProps) {
  const labelCounts = new Map<string, number>();
  for (const relation of relations) {
    const label = relation.label.trim();
    labelCounts.set(label, (labelCounts.get(label) ?? 0) + 1);
  }

  return (
    <Select value={String(value)} onValueChange={(nextValue) => onValueChange(Number(nextValue))}>
      <SelectTrigger size="sm" className="mt-2 w-full" aria-label="选择具体关系">
        <SelectValue />
      </SelectTrigger>
      <SelectContent position="popper" align="start">
        <SelectGroup>
          {relations.map((relation) => {
            const label = relation.label.trim();
            const isDuplicate = (labelCounts.get(label) ?? 0) > 1;
            const confidenceValue = relation.confidence <= 1
              ? relation.confidence * 100
              : relation.confidence;
            const confidence = `${Math.round(confidenceValue)}%`;
            const optionLabel = isDuplicate
              ? `${label} · #${relation.relationId} · 置信度 ${confidence}`
              : `${label} · 置信度 ${confidence}`;

            return (
              <SelectItem key={relation.relationId} value={String(relation.relationId)}>
                {optionLabel}
              </SelectItem>
            );
          })}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

interface EvidenceChipProps {
  evidence: EvidenceItem;
  caseId: number;
  reportRef: string | null;
  citationId: string;
  onOpen: (params: { caseId: number; reportRef: string; citationId: string }) => void;
}

function EvidenceChip({ evidence, caseId, reportRef, citationId, onOpen }: EvidenceChipProps) {
  const disabled = !reportRef;
  return (
    <button
      type="button"
      disabled={disabled}
      className="flex w-full items-center gap-1.5 rounded bg-muted/50 px-2 py-1 text-left text-xs hover:bg-muted transition-colors disabled:opacity-50"
      onClick={() => {
        if (!reportRef) return;
        onOpen({ caseId, reportRef, citationId });
      }}
    >
      <span className="truncate text-muted-foreground">{evidence.file_name}</span>
      <span className="shrink-0 text-muted-foreground/60">P.{evidence.page_no}</span>
    </button>
  );
}

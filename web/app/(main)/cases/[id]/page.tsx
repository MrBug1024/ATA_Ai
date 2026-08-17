"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { MessageSquare, Network } from "lucide-react";
import { getThreadDetail } from "@/lib/backend/langgraph";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { useCases } from "@/lib/hooks/use-cases";
import { useCaseMaterialEvents } from "@/lib/hooks/use-case-material-events";
import { useCaseDocCategories } from "@/lib/hooks/use-case-doc-categories";
import { useEvolutionItems } from "@/lib/hooks/use-evolution-items";
import { useUnresolvedItems } from "@/lib/hooks/use-unresolved-items";
import { useConversations } from "@/lib/hooks/use-conversations";
import { useGraphModalStore } from "@/lib/stores/graph-modal";
import { useAuth } from "@/lib/hooks/use-auth";
import { canAccessModule } from "@/lib/auth/authorization";
import { DemoValidationGate } from "@/components/knowledge-graph/demo-validation-gate";
import { MaterialEventTimeline } from "@/components/knowledge-graph/material-event-timeline";
import { EvolutionTimeline } from "@/components/knowledge-graph/evolution-timeline";
import { UnresolvedItemsPanel } from "@/components/knowledge-graph/unresolved-items-panel";
import { CorrectionsPanel } from "@/components/cases/corrections-panel";
import { AnnualAuditExecutionPanel } from "@/components/cases/annual-audit-execution-panel";

export default function CaseDetailPage() {
  const params = useParams();
  const caseId = Number(params?.id);
  const { user } = useAuth();
  const canUseGraph = canAccessModule(user, "graph");
  const canUseCorrections = canAccessModule(user, "corrections");
  const needsReportRef = canUseGraph;

  const { cases } = useCases();
  const caseItem = cases.find((c) => c.case_id === caseId) ?? null;

  const {
    events,
    isLoading: eventsLoading,
    error: eventsError,
    refresh: refreshEvents,
  } = useCaseMaterialEvents(caseId);
  const { items: evolutionItems, isLoading: evolutionLoading } = useEvolutionItems(caseId);
  const { data: unresolvedData, isLoading: unresolvedLoading } = useUnresolvedItems(caseId);
  const {
    caseDocCategories,
    isLoading: docCategoriesLoading,
  } = useCaseDocCategories(caseId);
  const { conversations } = useConversations({
    caseId,
    limit: 200,
  }, needsReportRef);
  const openGraph = useGraphModalStore((s) => s.openModal);

  // 后端未声明排序保证，因此在最大单页范围内按 updated_at 自行选择最近会话。
  const latestThreadId = useMemo(
    () =>
      [...conversations].sort(
        (a, b) =>
          (Date.parse(b.updated_at ?? "") || 0) - (Date.parse(a.updated_at ?? "") || 0)
      )[0]?.thread_id ?? null,
    [conversations]
  );

  const [reportRef, setReportRef] = useState<string | null>(null);
  useEffect(() => {
    if (!needsReportRef || !latestThreadId) {
      setReportRef(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await getThreadDetail(latestThreadId);
        const ref = data.final_report_ref || null;
        if (!cancelled) setReportRef(ref);
      } catch {
        if (!cancelled) setReportRef(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [latestThreadId, needsReportRef]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3 border-b px-4 py-3">
        <SidebarTrigger className="shrink-0" />
        <div className="min-w-0 flex-1">
          <h1 className="text-base font-semibold">{caseItem?.case_name ?? `年审项目 ${caseId}`}</h1>
          {caseItem?.entity_name && (
            <p className="text-xs text-muted-foreground">{caseItem.entity_name}</p>
          )}
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          <Button asChild size="sm">
            <Link href={`/chat?caseId=${caseId}`}>
              <MessageSquare data-icon="inline-start" />
              进入 AI 对话
            </Link>
          </Button>
          {canUseGraph && (
            <>
              <DemoValidationGate caseId={caseId} reportRef={reportRef} />
              <Button
                variant="outline"
                size="sm"
                onClick={() => openGraph({ caseId, reportRef })}
              >
                <Network data-icon="inline-start" />
                查看图谱
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="events" className="flex flex-1 flex-col overflow-hidden">
        <div className="overflow-x-auto px-4 pt-3">
          <TabsList variant="line" className="min-w-max justify-start">
            <TabsTrigger value="events">资料处理记录</TabsTrigger>
            <TabsTrigger value="evolution">审计结论演进</TabsTrigger>
            <TabsTrigger value="unresolved">待补资料</TabsTrigger>
            <TabsTrigger value="execution">审计执行</TabsTrigger>
            {canUseCorrections && <TabsTrigger value="corrections">审计调整</TabsTrigger>}
          </TabsList>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          <TabsContent value="events" className="mt-0">
            <MaterialEventTimeline
              events={events}
              isLoading={eventsLoading}
              error={eventsError}
              onRetried={refreshEvents}
            />
          </TabsContent>
          <TabsContent value="evolution" className="mt-0">
            <EvolutionTimeline items={evolutionItems} isLoading={evolutionLoading} />
          </TabsContent>
          <TabsContent value="unresolved" className="mt-0">
            <UnresolvedItemsPanel
              data={unresolvedData}
              isLoading={unresolvedLoading}
              caseDocCategories={caseDocCategories ?? null}
              docCategoriesLoading={docCategoriesLoading}
            />
          </TabsContent>
          <TabsContent value="execution" className="mt-0">
            <AnnualAuditExecutionPanel caseId={caseId} />
          </TabsContent>
          {canUseCorrections && (
            <TabsContent value="corrections" className="mt-0">
              <CorrectionsPanel caseId={caseId} />
            </TabsContent>
          )}
        </div>
      </Tabs>
    </div>
  );
}

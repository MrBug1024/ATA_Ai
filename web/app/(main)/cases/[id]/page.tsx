"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Network } from "lucide-react";
import { getThreadDetail } from "@/lib/backend/langgraph";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { useCases } from "@/lib/hooks/use-cases";
import { useCaseMaterialEvents } from "@/lib/hooks/use-case-material-events";
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
import { useCaseProgress } from "@/lib/hooks/use-case-progress";
import { ProgressBoardPanel } from "@/components/cases/progress-board";
import { RecoveryPanel } from "@/components/cases/recovery-panel";
import { ForecastPanel } from "@/components/cases/forecast-panel";
import { ReviewDialog } from "@/components/cases/review-dialog";
import { CorrectionsPanel } from "@/components/cases/corrections-panel";
import { DeadlineBoard } from "@/components/cases/deadline-board";

export default function CaseDetailPage() {
  const params = useParams();
  const caseId = Number(params?.id);
  const { user } = useAuth();
  const canUseGraph = canAccessModule(user, "graph");
  const canUseProgress = canAccessModule(user, "progress");
  const canUseReview = canAccessModule(user, "review");
  const canUseDeadline = canAccessModule(user, "deadline");
  const canUseCorrections = canAccessModule(user, "corrections");
  const needsReportRef = canUseGraph || canUseProgress;

  const { cases } = useCases();
  const caseItem = cases.find((c) => c.case_id === caseId) ?? null;

  const {
    events,
    isLoading: eventsLoading,
    refresh: refreshEvents,
  } = useCaseMaterialEvents(caseId);
  const { items: evolutionItems, isLoading: evolutionLoading } = useEvolutionItems(caseId);
  const { data: unresolvedData, isLoading: unresolvedLoading } = useUnresolvedItems(caseId);
  const {
    progress,
    isLoading: progressLoading,
    error: progressError,
    refresh: refreshProgress,
  } = useCaseProgress(canUseProgress ? caseId : null);
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
          <h1 className="text-base font-semibold">{caseItem?.case_name ?? `案件 ${caseId}`}</h1>
          {caseItem?.debtor_names && (
            <p className="text-xs text-muted-foreground">{caseItem.debtor_names}</p>
          )}
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          {canUseReview && <ReviewDialog caseId={caseId} />}
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
            <TabsTrigger value="events">材料事件</TabsTrigger>
            <TabsTrigger value="evolution">结论演进</TabsTrigger>
            <TabsTrigger value="unresolved">未决补件</TabsTrigger>
            {canUseProgress && <TabsTrigger value="progress">进度看板</TabsTrigger>}
            {canUseProgress && <TabsTrigger value="recovery">回款管理</TabsTrigger>}
            {canUseDeadline && <TabsTrigger value="deadline">时效看板</TabsTrigger>}
            {canUseCorrections && <TabsTrigger value="corrections">权威订正</TabsTrigger>}
          </TabsList>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          <TabsContent value="events" className="mt-0">
            <MaterialEventTimeline
              events={events}
              isLoading={eventsLoading}
              onRetried={refreshEvents}
            />
          </TabsContent>
          <TabsContent value="evolution" className="mt-0">
            <EvolutionTimeline items={evolutionItems} isLoading={evolutionLoading} />
          </TabsContent>
          <TabsContent value="unresolved" className="mt-0">
            <UnresolvedItemsPanel data={unresolvedData} isLoading={unresolvedLoading} />
          </TabsContent>
          {canUseProgress && (
            <TabsContent value="progress" className="mt-0">
              <ProgressBoardPanel
                progress={progress}
                isLoading={progressLoading}
                error={progressError}
                onRetry={() => refreshProgress()}
              />
            </TabsContent>
          )}
          {canUseProgress && (
            <TabsContent value="recovery" className="mt-0">
              <div className="grid gap-6 lg:grid-cols-2">
                <div>
                  <h3 className="mb-3 text-sm font-medium">实际回款</h3>
                  <RecoveryPanel caseId={caseId} />
                </div>
                <div>
                  <h3 className="mb-3 text-sm font-medium">预期回款</h3>
                  <ForecastPanel caseId={caseId} reportRef={reportRef} />
                </div>
              </div>
            </TabsContent>
          )}
          {canUseDeadline && (
            <TabsContent value="deadline" className="mt-0">
              <DeadlineBoard caseId={caseId} />
            </TabsContent>
          )}
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

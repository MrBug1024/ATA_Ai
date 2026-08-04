"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import {
  ListTree,
  Loader2,
  Minus,
  Network,
  RotateCcw,
  ScanLine,
  Search,
  Tags,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useGraphModalStore } from "@/lib/stores/graph-modal";
import { useGraphSubgraph } from "@/lib/hooks/use-graph-subgraph";
import { useGraphEntities } from "@/lib/hooks/use-graph-entities";
import { computeVisibleGraph } from "./graph-expansion";
import {
  graphEntityTypeLabel,
  prepareGraphVisualization,
} from "./graph-visualization";
import { RelationDetailPanel, type PanelSelection } from "./relation-detail-panel";
import { EvidenceDrawer } from "./evidence-drawer";
import type { GraphNode, GraphEdge, GraphEntityItem } from "@/lib/types/knowledge-graph";

// G6 画布只在浏览器渲染(canvas/webgl),保持在 SSR bundle 之外
const GraphCanvas = dynamic(() => import("./graph-canvas").then((m) => m.GraphCanvas), {
  ssr: false,
  loading: () => (
    <div className="flex flex-1 items-center justify-center gap-2 text-xs text-muted-foreground">
      <Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载画布…
    </div>
  ),
});

// 子图接口的最大深度。一次拉全量,展开/收起完全在前端做(见 graph-expansion.ts)。
const FULL_DEPTH = 3;

export function GraphModal() {
  const open = useGraphModalStore((s) => s.open);
  const caseId = useGraphModalStore((s) => s.caseId);
  const storeCenterEntityId = useGraphModalStore((s) => s.centerEntityId);
  const reportRef = useGraphModalStore((s) => s.reportRef);
  const closeModal = useGraphModalStore((s) => s.closeModal);

  const { fetch, reset } = useGraphSubgraph();
  const { entities, isLoading: entitiesLoading } = useGraphEntities(open ? caseId : null);
  const [center, setCenter] = useState<number | undefined>(storeCenterEntityId);
  const [selection, setSelection] = useState<PanelSelection>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);
  const [fitRequestKey, setFitRequestKey] = useState(0);
  // 已展开的节点集合;可见部分 = 展开节点 ∪ 其直接邻居
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<string>>(new Set());
  const requestSequenceRef = useRef(0);

  // 打开时同步 store 指定的中心实体（来自证据抽屉「在图谱中查看」）
  useEffect(() => {
    if (open) setCenter(storeCenterEntityId);
  }, [open, storeCenterEntityId]);

  const loadGraph = useCallback(
    async (entityId: number) => {
      const requestSequence = ++requestSequenceRef.current;
      setGraphError(null);
      setGraphLoading(true);
      setNodes([]);
      setEdges([]);
      setExpandedIds(new Set([`entity_${entityId}`]));
      try {
        const response = await fetch({
          case_id: caseId,
          center_entity_id: entityId,
          depth: FULL_DEPTH,
        });
        if (requestSequence !== requestSequenceRef.current) return;
        setNodes(response.nodes ?? []);
        setEdges(response.edges ?? []);
      } catch (cause) {
        if (requestSequence !== requestSequenceRef.current) return;
        setGraphError(cause instanceof Error ? cause.message : "图谱加载失败");
      } finally {
        if (requestSequence === requestSequenceRef.current) setGraphLoading(false);
      }
    },
    [caseId, fetch]
  );

  useEffect(() => {
    if (!open) {
      requestSequenceRef.current += 1;
      reset();
      setNodes([]);
      setEdges([]);
      setGraphError(null);
      setGraphLoading(false);
      setSelection(null);
      setExpandedIds(new Set());
      setShowEdgeLabels(false);
      return;
    }
    if (center === undefined) {
      requestSequenceRef.current += 1;
      setNodes([]);
      setEdges([]);
      setGraphError(null);
      setGraphLoading(false);
      setSelection(null);
      setExpandedIds(new Set());
      return;
    }
    setSelection(null);
    void loadGraph(center);
  }, [open, center, loadGraph, reset]);

  const visible = useMemo(
    () => computeVisibleGraph(nodes, edges, expandedIds),
    [nodes, edges, expandedIds]
  );

  const visualization = useMemo(
    () =>
      prepareGraphVisualization(
        visible.nodes,
        visible.edges,
        center === undefined ? null : `entity_${center}`
      ),
    [visible.nodes, visible.edges, center]
  );

  const expandNode = useCallback((nodeId: string) => {
    setExpandedIds((prev) => {
      if (prev.has(nodeId)) return prev;
      const next = new Set(prev);
      next.add(nodeId);
      return next;
    });
  }, []);

  function recenter(entityId: number) {
    setSelection(null);
    setCenter(entityId);
  }

  const centerNodeId = center === undefined ? undefined : `entity_${center}`;
  const selectedNodeId = selection?.type === "node" ? selection.nodeId : null;
  const selectedHiddenCount = selectedNodeId
    ? visible.hiddenNeighborCounts.get(selectedNodeId) ?? 0
    : 0;
  const selectedIsExpanded = selectedNodeId ? expandedIds.has(selectedNodeId) : false;
  const canCollapseSelected = Boolean(
    selectedNodeId && selectedNodeId !== centerNodeId && selectedIsExpanded
  );

  function toggleSelectedExpansion() {
    if (!selectedNodeId) return;
    setExpandedIds((previous) => {
      const next = new Set(previous);
      if (next.has(selectedNodeId) && selectedNodeId !== centerNodeId) {
        next.delete(selectedNodeId);
      } else {
        next.add(selectedNodeId);
      }
      return next;
    });
  }

  function resetToFirstHop() {
    if (!centerNodeId) return;
    setExpandedIds(new Set([centerNodeId]));
    setSelection(null);
    setFitRequestKey((key) => key + 1);
  }

  const centerLabel =
    center !== undefined ? entities.find((e) => e.entity_id === center)?.label : undefined;

  return (
    <DialogPrimitive.Root
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) closeModal();
      }}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className="fixed inset-0 z-50 flex flex-col bg-background outline-none"
        >
          <DialogPrimitive.Title className="sr-only">
            审计关系图谱 · 年审项目 {caseId}
          </DialogPrimitive.Title>
      {/* Toolbar */}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
        <div className="flex shrink-0 items-center gap-2 text-sm font-medium">
          <Network className="size-4 text-primary" />
          <span>知识图谱</span>
          <span className="hidden text-muted-foreground sm:inline">年审项目 {caseId}</span>
        </div>
        {center !== undefined && (
          <>
            {centerLabel && (
              <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                中心：{centerLabel}
              </span>
            )}
            <Button
              variant="ghost"
              size="xs"
              className="shrink-0 text-muted-foreground"
              onClick={() => {
                setCenter(undefined);
                setSelection(null);
              }}
            >
              切换实体
            </Button>
          </>
        )}
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {center !== undefined &&
            selectedNodeId &&
            (selectedHiddenCount > 0 || canCollapseSelected) && (
              <Button variant="outline" size="sm" onClick={toggleSelectedExpansion}>
                {canCollapseSelected ? <Minus /> : <ListTree />}
                <span className="hidden sm:inline">
                  {canCollapseSelected ? "收起" : `展开 +${selectedHiddenCount}`}
                </span>
              </Button>
            )}
          {center !== undefined && (
            <>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant={showEdgeLabels ? "secondary" : "ghost"}
                    size="icon-sm"
                    aria-pressed={showEdgeLabels}
                    onClick={() => setShowEdgeLabels((value) => !value)}
                  >
                    <Tags />
                    <span className="sr-only">
                      {showEdgeLabels ? "隐藏关系标签" : "显示关系标签"}
                    </span>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  {showEdgeLabels ? "隐藏关系标签" : "显示关系标签"}
                </TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    disabled={expandedIds.size <= 1}
                    onClick={resetToFirstHop}
                  >
                    <RotateCcw />
                    <span className="sr-only">恢复一跳视图</span>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>恢复一跳视图</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => setFitRequestKey((key) => key + 1)}
                  >
                    <ScanLine />
                    <span className="sr-only">适配画布</span>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>适配画布</TooltipContent>
              </Tooltip>
            </>
          )}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" onClick={closeModal}>
                <X />
                <span className="sr-only">关闭图谱</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>关闭图谱</TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* Body */}
      {center === undefined ? (
        <EntityPicker entities={entities} isLoading={entitiesLoading} onPick={recenter} />
      ) : (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden sm:flex-row">
          <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
            {!graphError && !graphLoading && visualization.nodes.length > 0 && (
              <div className="pointer-events-none absolute left-3 top-3 z-10 rounded border bg-background/85 px-2.5 py-1.5 text-[11px] text-muted-foreground shadow-sm backdrop-blur-sm">
                <span className="font-medium text-foreground">
                  {visualization.stats.visualNodeCount}/{nodes.length} 实体
                </span>
                <span> · {visualization.stats.visualEdgeCount} 组关系</span>
                {visualization.stats.mergedParallelEdgeCount > 0 && (
                  <span>
                    {" "}· 合并 {visualization.stats.mergedParallelEdgeCount} 条平行关系
                  </span>
                )}
                {visualization.stats.removedSelfLoopCount > 0 && (
                  <span> · 忽略 {visualization.stats.removedSelfLoopCount} 条自关联</span>
                )}
              </div>
            )}
            {graphLoading ? (
              <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> 加载图谱…
              </div>
            ) : graphError ? (
              <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
                <p className="text-sm text-destructive">{graphError}</p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void loadGraph(center)}
                >
                  重试
                </Button>
              </div>
            ) : (
              <GraphCanvas
                key={centerNodeId}
                nodes={visualization.nodes}
                edges={visualization.edges}
                hiddenNeighborCounts={visible.hiddenNeighborCounts}
                centerEntityId={centerNodeId}
                showEdgeLabels={showEdgeLabels}
                fitRequestKey={fitRequestKey}
                onNodeClick={(nodeId, entityId, label, entityType, riskLevel) => {
                  setSelection({
                    type: "node",
                    nodeId,
                    entityId,
                    label,
                    entityType,
                    riskLevel,
                  });
                }}
                onNodeExpand={expandNode}
                onEdgeClick={(edgeId, relationId, label, relations) =>
                  setSelection({ type: "edge", edgeId, relationId, label, relations })
                }
              />
            )}
          </div>
          <RelationDetailPanel
            selection={selection}
            caseId={caseId}
            reportRef={reportRef}
            onRecenter={recenter}
            onClose={() => setSelection(null)}
          />
        </div>
      )}

      {/* 全屏图谱内点证据 chip 时，证据抽屉以浮层盖在图谱之上 */}
      <EvidenceDrawer variant="overlay" />
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

interface EntityPickerProps {
  entities: GraphEntityItem[];
  isLoading: boolean;
  onPick: (entityId: number) => void;
}

function EntityPicker({ entities, isLoading, onPick }: EntityPickerProps) {
  const [query, setQuery] = useState("");
  const duplicateTypeKeys = useMemo(() => {
    const counts = new Map<string, number>();
    for (const entity of entities) {
      const key = `${entity.label.trim().toLowerCase()}\u0000${graphEntityTypeLabel(
        entity.entity_type
      )}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [entities]);
  const filteredEntities = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return [...entities]
      .sort(
        (left, right) =>
          right.degree - left.degree ||
          left.label.localeCompare(right.label, "zh-CN") ||
          left.entity_id - right.entity_id
      )
      .filter((entity) => {
        if (!normalizedQuery) return true;
        const typeLabel = graphEntityTypeLabel(entity.entity_type);
        return `${entity.label} ${entity.entity_type} ${typeLabel} ${entity.entity_id}`
          .toLowerCase()
          .includes(normalizedQuery);
      });
  }, [entities, query]);

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> 加载实体…
      </div>
    );
  }
  if (entities.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        该年审项目暂无可展示的实体
      </div>
    );
  }
  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex flex-col gap-2 border-b px-4 py-3 sm:flex-row sm:items-center sm:px-6">
        <div className="shrink-0 text-sm font-medium">
          中心实体
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {filteredEntities.length}/{entities.length}
          </span>
        </div>
        <div className="relative sm:ml-auto sm:w-72">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="搜索实体"
            placeholder="名称、类型或实体 ID"
            className="h-8 pl-8 text-xs"
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {filteredEntities.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            没有匹配的实体
          </div>
        ) : (
          <div className="mx-auto grid max-w-3xl grid-cols-1 gap-2 sm:grid-cols-2">
            {filteredEntities.map((entity) => {
              const typeLabel = graphEntityTypeLabel(entity.entity_type);
              const duplicateKey = `${entity.label.trim().toLowerCase()}\u0000${typeLabel}`;
              const showEntityId = (duplicateTypeKeys.get(duplicateKey) ?? 0) > 1;
              return (
                <button
                  key={entity.entity_id}
                  type="button"
                  onClick={() => onPick(entity.entity_id)}
                  className="flex items-center justify-between gap-3 rounded-md border p-3 text-left transition-colors hover:border-primary/50 hover:bg-muted"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{entity.label}</div>
                    <div className="text-xs text-muted-foreground">
                      {typeLabel}
                      {showEntityId ? ` · #${entity.entity_id}` : ""}
                    </div>
                  </div>
                  <span className="flex shrink-0 items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                    <Network className="h-3 w-3" /> {entity.degree}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import {
  EdgeEvent,
  Graph,
  NodeEvent,
  type GraphData,
  type GraphOptions,
  type IElementEvent,
  type EdgeData,
  type NodeData,
} from "@antv/g6";
import { useTheme } from "next-themes";
import type {
  VisualGraphEdge,
  VisualGraphNode,
  VisualGraphRelation,
} from "./graph-visualization";

type CanvasTheme = {
  edge: string;
  edgeActive: string;
  label: string;
  labelBackground: string;
  nodeStroke: string;
  categoryColors: Record<EntityCategory, string>;
};

type EntityCategory =
  | "organization"
  | "person"
  | "justice"
  | "professional"
  | "asset"
  | "document"
  | "event"
  | "other";

const DARK_CANVAS_THEME: CanvasTheme = {
  edge: "#7c8798",
  edgeActive: "#60a5fa",
  label: "#e2e8f0",
  labelBackground: "#2d3037",
  nodeStroke: "#cbd5e1",
  categoryColors: {
    organization: "#3b82f6",
    person: "#22c55e",
    justice: "#f59e0b",
    professional: "#a78bfa",
    asset: "#14b8a6",
    document: "#f43f5e",
    event: "#06b6d4",
    other: "#64748b",
  },
};

const LIGHT_CANVAS_THEME: CanvasTheme = {
  edge: "#64748b",
  edgeActive: "#2563eb",
  label: "#334155",
  labelBackground: "#f8fafc",
  nodeStroke: "#475569",
  categoryColors: {
    organization: "#2563eb",
    person: "#15803d",
    justice: "#b45309",
    professional: "#7e22ce",
    asset: "#0f766e",
    document: "#be123c",
    event: "#0e7490",
    other: "#64748b",
  },
};

interface NodeDatum {
  entityId: number;
  fullLabel: string;
  displayLabel: string;
  typeLabel: string;
  entityType: string;
  riskLevel: string;
  isCenter: boolean;
  hiddenCount: number;
}

interface EdgeDatum {
  relationId: number;
  label: string;
  confidence: number;
  relationCount: number;
}

type HoverSummary =
  | { type: "node"; label: string; meta: string }
  | { type: "edge"; label: string; meta: string }
  | null;

function normalizeType(value: string): string {
  return value.trim().toLowerCase().replace(/[\s-]+/g, "_");
}

function entityCategory(entityType: string): EntityCategory {
  const type = normalizeType(entityType);
  if (
    ["person", "individual", "natural_person", "judge", "自然人", "个人"].includes(
      type
    )
  ) {
    return "person";
  }
  if (
    ["court", "procuratorate", "public_security", "法院", "检察院", "公安机关"].includes(
      type
    )
  ) {
    return "justice";
  }
  if (
    [
      "law_firm",
      "lawyer_office",
      "valuation_institution",
      "audit_institution",
      "administrator",
    ].includes(type)
  ) {
    return "professional";
  }
  if (
    ["asset", "money", "mine", "mine_right", "mining_right", "资产", "矿业权"].includes(
      type
    )
  ) {
    return "asset";
  }
  if (
    ["document", "court_ruling", "legal_provision", "law", "法律文书", "法律法规"].includes(
      type
    )
  ) {
    return "document";
  }
  if (["event", "meeting", "creditors_meeting", "venue", "会议", "地点"].includes(type)) {
    return "event";
  }
  if (
    [
      "company",
      "enterprise",
      "organization",
      "legal_person",
      "government",
      "government_agency",
      "企业",
      "机构",
      "组织",
    ].includes(type)
  ) {
    return "organization";
  }
  return "other";
}

function nodeDatum(d: { data?: unknown }): NodeDatum {
  return d.data as NodeDatum;
}

function edgeDatum(d: { data?: unknown }): EdgeDatum {
  return d.data as EdgeDatum;
}

/** 清洗后的业务图数据 -> G6 GraphData。完整名称仍保留在 data 中供悬停与详情使用。 */
export function buildGraphData(
  nodes: VisualGraphNode[],
  edges: VisualGraphEdge[],
  hiddenNeighborCounts?: Map<string, number>
): GraphData {
  return {
    nodes: nodes.map(({ node, displayLabel, typeLabel, isCenter }) => ({
      id: node.id,
      data: {
        entityId: node.entity_id,
        fullLabel: node.label,
        displayLabel,
        typeLabel,
        entityType: node.entity_type,
        riskLevel: node.risk_level ?? "unknown",
        isCenter,
        hiddenCount: hiddenNeighborCounts?.get(node.id) ?? 0,
      } satisfies NodeDatum as unknown as Record<string, unknown>,
    })),
    edges: edges.map(({ edge, displayLabel, relationCount }) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      data: {
        relationId: edge.relation_id,
        label: displayLabel,
        confidence: edge.confidence ?? 0,
        relationCount,
      } satisfies EdgeDatum as unknown as Record<string, unknown>,
    })),
  };
}

export interface GraphCanvasProps {
  nodes: VisualGraphNode[];
  edges: VisualGraphEdge[];
  centerEntityId?: string;
  /** 节点 id -> 未展开邻居数；>0 的节点标签带 +N。 */
  hiddenNeighborCounts?: Map<string, number>;
  showEdgeLabels?: boolean;
  /** 每次递增都强制重新适配视图。 */
  fitRequestKey?: number;
  onNodeClick?: (
    nodeId: string,
    entityId: number,
    label: string,
    entityType: string,
    riskLevel: string
  ) => void;
  onNodeExpand?: (nodeId: string) => void;
  onEdgeClick?: (
    edgeId: string,
    relationId: number,
    label: string,
    relations: VisualGraphRelation[]
  ) => void;
}

function nodeOptions(theme: CanvasTheme): NonNullable<GraphOptions["node"]> {
  return {
    style: {
      size: (d) => (nodeDatum(d).isCenter ? 58 : 42),
      fill: (d) => theme.categoryColors[entityCategory(nodeDatum(d).entityType)],
      stroke: (d) => {
        const risk = nodeDatum(d).riskLevel;
        if (risk === "high") return "#ef4444";
        if (risk === "medium") return "#f97316";
        return theme.nodeStroke;
      },
      lineWidth: (d) => (nodeDatum(d).isCenter ? 3 : 1.5),
      cursor: "pointer",
      labelText: (d) => {
        const node = nodeDatum(d);
        return node.hiddenCount > 0
          ? `${node.displayLabel}  +${node.hiddenCount}`
          : node.displayLabel;
      },
      labelPlacement: "bottom",
      labelFontSize: 11,
      labelFontWeight: (d) => (nodeDatum(d).isCenter ? 600 : 400),
      labelFill: theme.label,
      labelOffsetY: 6,
      labelMaxWidth: 116,
      labelWordWrap: true,
      labelTextOverflow: "...",
      labelBackground: true,
      labelBackgroundFill: theme.labelBackground,
      labelBackgroundOpacity: 0.9,
      labelBackgroundPadding: [2, 4],
      labelBackgroundRadius: 3,
    },
    state: {
      active: { halo: true, haloLineWidth: 10, haloStrokeOpacity: 0.18 },
      highlight: { fillOpacity: 1, labelOpacity: 1, strokeOpacity: 1 },
      selected: {
        halo: true,
        haloLineWidth: 14,
        haloStroke: theme.edgeActive,
        haloStrokeOpacity: 0.2,
        lineWidth: 3,
      },
      inactive: {
        fillOpacity: 0.18,
        labelOpacity: 0.18,
        strokeOpacity: 0.18,
      },
    },
  };
}

function edgeOptions(
  theme: CanvasTheme,
  showEdgeLabels: boolean
): NonNullable<GraphOptions["edge"]> {
  return {
    style: {
      stroke: theme.edge,
      strokeOpacity: (d) =>
        0.35 + Math.min(Math.max(edgeDatum(d).confidence, 0), 1) * 0.4,
      lineWidth: (d) => 1 + Math.min(edgeDatum(d).relationCount - 1, 5) * 0.28,
      endArrow: true,
      cursor: "pointer",
      labelText: (d) => (showEdgeLabels ? edgeDatum(d).label : ""),
      labelFontSize: 9,
      labelFill: theme.label,
      labelAutoRotate: true,
      labelBackground: true,
      labelBackgroundFill: theme.labelBackground,
      labelBackgroundOpacity: 0.92,
      labelBackgroundPadding: [2, 3],
    },
    state: {
      active: { stroke: theme.edgeActive, strokeOpacity: 0.9, lineWidth: 2.2 },
      highlight: { strokeOpacity: 0.75 },
      selected: {
        halo: true,
        haloStroke: theme.edgeActive,
        haloStrokeOpacity: 0.18,
        stroke: theme.edgeActive,
        strokeOpacity: 1,
        lineWidth: 3,
      },
      inactive: { strokeOpacity: 0.08, labelOpacity: 0.08 },
    },
  };
}

function radialLayout(
  centerEntityId: string | undefined
): NonNullable<GraphOptions["layout"]> {
  return {
    type: "radial",
    focusNode: centerEntityId ?? null,
    unitRadius: 176,
    linkDistance: 132,
    nodeSize: 104,
    preventOverlap: true,
    strictRadial: false,
    sortBy: "data",
    sortStrength: 20,
    maxIteration: 600,
    animation: false,
  };
}

export function GraphCanvas({
  nodes,
  edges,
  centerEntityId,
  hiddenNeighborCounts,
  showEdgeLabels = false,
  fitRequestKey = 0,
  onNodeClick,
  onNodeExpand,
  onEdgeClick,
}: GraphCanvasProps) {
  const { resolvedTheme } = useTheme();
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const graphOperationRef = useRef<Promise<void> | null>(null);
  const renderedRef = useRef(false);
  const lastFitRequestRef = useRef(fitRequestKey);
  const [hoverSummary, setHoverSummary] = useState<HoverSummary>(null);

  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;
  const edgesRef = useRef(edges);
  edgesRef.current = edges;
  const onNodeClickRef = useRef(onNodeClick);
  onNodeClickRef.current = onNodeClick;
  const onNodeExpandRef = useRef(onNodeExpand);
  onNodeExpandRef.current = onNodeExpand;
  const onEdgeClickRef = useRef(onEdgeClick);
  onEdgeClickRef.current = onEdgeClick;
  const themeRef = useRef(resolvedTheme);
  themeRef.current = resolvedTheme;
  const showEdgeLabelsRef = useRef(showEdgeLabels);
  showEdgeLabelsRef.current = showEdgeLabels;

  useEffect(() => {
    if (!containerRef.current || nodes.length === 0) return;

    const canvasTheme = resolvedTheme === "dark" ? DARK_CANVAS_THEME : LIGHT_CANVAS_THEME;
    const data = buildGraphData(nodes, edges, hiddenNeighborCounts);
    let graph = graphRef.current;
    const isInitialRender = !graph;

    if (!graph) {
      graph = new Graph({
        container: containerRef.current,
        data,
        padding: 48,
        zoomRange: [0.28, 2.4],
        animation: { duration: 220 },
        node: nodeOptions(canvasTheme),
        edge: edgeOptions(canvasTheme, showEdgeLabels),
        layout: radialLayout(centerEntityId),
        behaviors: [
          "drag-canvas",
          "zoom-canvas",
          "drag-element",
          {
            type: "hover-activate",
            degree: 1,
            state: "active",
            inactiveState: "inactive",
            animation: false,
          },
          {
            type: "click-select",
            degree: 1,
            state: "selected",
            neighborState: "highlight",
            unselectedState: "inactive",
            animation: false,
          },
          {
            type: "auto-adapt-label",
            padding: 6,
            throttle: 32,
            sortNode: (left: NodeData, right: NodeData) => {
              const leftCenter = nodeDatum(left).isCenter;
              const rightCenter = nodeDatum(right).isCenter;
              if (leftCenter === rightCenter) return 0;
              return leftCenter ? -1 : 1;
            },
            sortEdge: (left: EdgeData, right: EdgeData) => {
              const difference = edgeDatum(right).confidence - edgeDatum(left).confidence;
              return difference === 0 ? 0 : difference > 0 ? 1 : -1;
            },
          },
        ],
      });
      graphRef.current = graph;

      graph.on(NodeEvent.CLICK, (event: IElementEvent) => {
        const visualNode = nodesRef.current.find(({ node }) => node.id === event.target.id);
        if (!visualNode) return;
        const { node } = visualNode;
        onNodeClickRef.current?.(
          node.id,
          node.entity_id,
          node.label,
          node.entity_type,
          node.risk_level ?? "unknown"
        );
      });
      graph.on(NodeEvent.DBLCLICK, (event: IElementEvent) => {
        onNodeExpandRef.current?.(event.target.id);
      });
      graph.on(EdgeEvent.CLICK, (event: IElementEvent) => {
        const visualEdge = edgesRef.current.find(({ edge }) => edge.id === event.target.id);
        if (!visualEdge) return;
        onEdgeClickRef.current?.(
          visualEdge.edge.id,
          visualEdge.edge.relation_id,
          visualEdge.displayLabel,
          visualEdge.relations
        );
      });
      graph.on(NodeEvent.POINTER_ENTER, (event: IElementEvent) => {
        const visualNode = nodesRef.current.find(({ node }) => node.id === event.target.id);
        if (visualNode) {
          setHoverSummary({
            type: "node",
            label: visualNode.node.label,
            meta: visualNode.typeLabel,
          });
        }
      });
      graph.on(NodeEvent.POINTER_LEAVE, () => setHoverSummary(null));
      graph.on(EdgeEvent.POINTER_ENTER, (event: IElementEvent) => {
        const visualEdge = edgesRef.current.find(({ edge }) => edge.id === event.target.id);
        if (visualEdge) {
          setHoverSummary({
            type: "edge",
            label: visualEdge.relationLabels.join(" / "),
            meta:
              visualEdge.relationCount > 1
                ? `${visualEdge.relationCount} 条关系`
                : "1 条关系",
          });
        }
      });
      graph.on(EdgeEvent.POINTER_LEAVE, () => setHoverSummary(null));
    } else {
      graph.setLayout(radialLayout(centerEntityId));
      graph.setData(data);
    }

    const activeGraph = graph;
    const previousOperation = graphOperationRef.current ?? Promise.resolve();
    const operation = previousOperation.catch(() => {}).then(async () => {
      if (graphRef.current !== activeGraph || activeGraph.destroyed) return;
      await activeGraph.render();
      if (graphRef.current !== activeGraph || activeGraph.destroyed) return;
      renderedRef.current = true;
      const latestTheme =
        themeRef.current === "dark" ? DARK_CANVAS_THEME : LIGHT_CANVAS_THEME;
      activeGraph.setNode(nodeOptions(latestTheme));
      activeGraph.setEdge(edgeOptions(latestTheme, showEdgeLabelsRef.current));
      await activeGraph.draw();
      if (graphRef.current !== activeGraph || activeGraph.destroyed) return;
      await activeGraph.fitView({ when: isInitialRender ? "always" : "overflow" }, false);
    });
    graphOperationRef.current = operation;
    void operation.catch(() => {});
  }, [nodes, edges, centerEntityId, hiddenNeighborCounts]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || !renderedRef.current) return;
    const canvasTheme = resolvedTheme === "dark" ? DARK_CANVAS_THEME : LIGHT_CANVAS_THEME;
    graph.setNode(nodeOptions(canvasTheme));
    graph.setEdge(edgeOptions(canvasTheme, showEdgeLabels));
    void graph.draw();
  }, [resolvedTheme, showEdgeLabels]);

  useEffect(() => {
    if (fitRequestKey === lastFitRequestRef.current) return;
    lastFitRequestRef.current = fitRequestKey;
    const graph = graphRef.current;
    if (!graph) return;
    graph.resize();
    void graph.fitView({ when: "always" }, { duration: 220 });
  }, [fitRequestKey]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === "undefined") return;
    let frame = 0;
    const observer = new ResizeObserver(([entry]) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const graph = graphRef.current;
        const width = Math.floor(entry.contentRect.width);
        const height = Math.floor(entry.contentRect.height);
        if (!graph || width <= 0 || height <= 0) return;
        graph.resize(width, height);
        void graph.fitView({ when: "overflow" }, false);
      });
    });
    observer.observe(container);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    return () => {
      const graph = graphRef.current;
      graphRef.current = null;
      renderedRef.current = false;
      const pendingOperation = graphOperationRef.current;
      graphOperationRef.current = null;
      if (!graph) return;
      if (!pendingOperation) {
        graph.destroy();
        return;
      }
      void pendingOperation.catch(() => {}).finally(() => {
        if (!graph.destroyed) graph.destroy();
      });
    };
  }, []);

  if (nodes.length === 0) {
    return (
      <div className="flex min-h-0 min-w-0 flex-1 items-center justify-center text-sm text-muted-foreground">
        该实体暂无关联关系
      </div>
    );
  }

  return (
    <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden">
      <div ref={containerRef} className="absolute inset-0" />
      {hoverSummary && (
        <div className="pointer-events-none absolute bottom-3 left-1/2 z-10 max-w-[min(34rem,calc(100%-1.5rem))] -translate-x-1/2 rounded-md border bg-background/95 px-3 py-2 text-center shadow-sm backdrop-blur-sm">
          <div className="truncate text-xs font-medium text-foreground">
            {hoverSummary.label}
          </div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">{hoverSummary.meta}</div>
        </div>
      )}
    </div>
  );
}

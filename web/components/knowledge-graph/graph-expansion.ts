import type { GraphNode, GraphEdge } from "@/lib/types/knowledge-graph";

export interface VisibleGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** 可见节点 id → 其未展开(不可见)邻居数,供画布渲染「+N」角标。 */
  hiddenNeighborCounts: Map<string, number>;
}

/**
 * 渐进展开:全量图谱在本地,可见部分 = 已展开节点 ∪ 它们的直接邻居;
 * 边仅在两端都可见时显示。用户点击节点将其加入展开集合,逐跳揭示。
 */
export function computeVisibleGraph(
  allNodes: GraphNode[],
  allEdges: GraphEdge[],
  expandedIds: ReadonlySet<string>
): VisibleGraph {
  const neighbors = new Map<string, Set<string>>();
  for (const e of allEdges) {
    if (!neighbors.has(e.source)) neighbors.set(e.source, new Set());
    if (!neighbors.has(e.target)) neighbors.set(e.target, new Set());
    neighbors.get(e.source)!.add(e.target);
    neighbors.get(e.target)!.add(e.source);
  }

  const visibleIds = new Set<string>();
  for (const id of expandedIds) {
    visibleIds.add(id);
    for (const n of neighbors.get(id) ?? []) visibleIds.add(n);
  }

  const nodes = allNodes.filter((n) => visibleIds.has(n.id));
  const edges = allEdges.filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target));

  const hiddenNeighborCounts = new Map<string, number>();
  for (const n of nodes) {
    let hidden = 0;
    for (const nb of neighbors.get(n.id) ?? []) {
      if (!visibleIds.has(nb)) hidden += 1;
    }
    hiddenNeighborCounts.set(n.id, hidden);
  }

  return { nodes, edges, hiddenNeighborCounts };
}

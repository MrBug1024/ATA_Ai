import { describe, it, expect } from "vitest";
import { computeVisibleGraph } from "@/components/knowledge-graph/graph-expansion";
import type { GraphNode, GraphEdge } from "@/lib/types/knowledge-graph";

function node(id: string): GraphNode {
  return { id, entity_id: Number(id.replace("e", "")), label: id, entity_type: "company", risk_level: "low" };
}

function edge(source: string, target: string): GraphEdge {
  return {
    id: `${source}-${target}`,
    relation_id: 1,
    source,
    target,
    label: "关联",
    relation_type: "rel",
    confidence: 0.9,
  };
}

// 链式图谱: e1 - e2 - e3 - e4,外加 e1 - e5
const NODES = [node("e1"), node("e2"), node("e3"), node("e4"), node("e5")];
const EDGES = [edge("e1", "e2"), edge("e2", "e3"), edge("e3", "e4"), edge("e1", "e5")];

describe("computeVisibleGraph", () => {
  it("仅展开中心时:显示中心 + 直接邻居,边只含两端可见的", () => {
    const { nodes, edges } = computeVisibleGraph(NODES, EDGES, new Set(["e1"]));
    expect(nodes.map((n) => n.id).sort()).toEqual(["e1", "e2", "e5"]);
    expect(edges.map((e) => e.id).sort()).toEqual(["e1-e2", "e1-e5"]);
  });

  it("展开邻居节点后:再显示一跳", () => {
    const { nodes, edges } = computeVisibleGraph(NODES, EDGES, new Set(["e1", "e2"]));
    expect(nodes.map((n) => n.id).sort()).toEqual(["e1", "e2", "e3", "e5"]);
    expect(edges.map((e) => e.id).sort()).toEqual(["e1-e2", "e1-e5", "e2-e3"]);
  });

  it("统计每个可见节点的未展开邻居数(供 +N 角标)", () => {
    const { hiddenNeighborCounts } = computeVisibleGraph(NODES, EDGES, new Set(["e1"]));
    // e2 的邻居 e3 不可见 → 1;e1/e5 的邻居全可见 → 不出现或为 0
    expect(hiddenNeighborCounts.get("e2")).toBe(1);
    expect(hiddenNeighborCounts.get("e1") ?? 0).toBe(0);
    expect(hiddenNeighborCounts.get("e5") ?? 0).toBe(0);
  });

  it("全部展开时:显示全图且无隐藏计数", () => {
    const all = new Set(NODES.map((n) => n.id));
    const { nodes, edges, hiddenNeighborCounts } = computeVisibleGraph(NODES, EDGES, all);
    expect(nodes).toHaveLength(5);
    expect(edges).toHaveLength(4);
    expect([...hiddenNeighborCounts.values()].every((v) => v === 0)).toBe(true);
  });

  it("展开集合为空时退化为空图", () => {
    const { nodes, edges } = computeVisibleGraph(NODES, EDGES, new Set());
    expect(nodes).toEqual([]);
    expect(edges).toEqual([]);
  });
});

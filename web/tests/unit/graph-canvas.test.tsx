// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { buildGraphData } from "@/components/knowledge-graph/graph-canvas";
import { prepareGraphVisualization } from "@/components/knowledge-graph/graph-visualization";
import type { GraphNode, GraphEdge } from "@/lib/types/knowledge-graph";

const nodes: GraphNode[] = [
  { id: "entity_1", entity_id: 1, label: "晨光煤矿", entity_type: "company", risk_level: "high" },
  { id: "entity_2", entity_id: 2, label: "张三", entity_type: "person", risk_level: "low" },
];
const edges: GraphEdge[] = [
  {
    id: "r-1",
    relation_id: 1,
    source: "entity_1",
    target: "entity_2",
    label: "担保",
    relation_type: "guarantee",
    confidence: 0.9,
  },
];

describe("buildGraphData", () => {
  it("把 GraphNode/GraphEdge 映射为 G6 数据,中心与隐藏计数写入 data", () => {
    const counts = new Map([["entity_2", 3]]);
    const visual = prepareGraphVisualization(nodes, edges, "entity_1");
    const data = buildGraphData(visual.nodes, visual.edges, counts);

    const n1 = data.nodes?.find((n) => n.id === "entity_1");
    expect(n1?.data).toMatchObject({
      entityId: 1,
      fullLabel: "晨光煤矿",
      displayLabel: "晨光煤矿",
      typeLabel: "公司",
      entityType: "company",
      riskLevel: "high",
      isCenter: true,
      hiddenCount: 0,
    });
    const n2 = data.nodes?.find((n) => n.id === "entity_2");
    expect(n2?.data).toMatchObject({ isCenter: false, hiddenCount: 3 });

    const e = data.edges?.[0];
    expect(e).toMatchObject({ id: "r-1", source: "entity_1", target: "entity_2" });
    expect(e?.data).toMatchObject({
      relationId: 1,
      label: "担保",
      confidence: 0.9,
      relationCount: 1,
    });
  });

  it("不传计数与中心时使用安全默认值", () => {
    const visual = prepareGraphVisualization(nodes, edges);
    const data = buildGraphData(visual.nodes, visual.edges);
    expect(data.nodes?.every((n) => n.data?.isCenter === false)).toBe(true);
    expect(data.nodes?.every((n) => n.data?.hiddenCount === 0)).toBe(true);
  });
});

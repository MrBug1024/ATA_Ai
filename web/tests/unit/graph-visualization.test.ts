import { describe, expect, it } from "vitest";
import {
  graphEntityTypeLabel,
  prepareGraphVisualization,
  truncateGraphLabel,
  type GraphEdgeInput,
  type GraphNodeInput,
} from "@/components/knowledge-graph/graph-visualization";

function node(
  id: string,
  label: string,
  entityType: string,
  entityId = Number(id.replace(/\D/g, ""))
): GraphNodeInput {
  return {
    id,
    entity_id: entityId,
    label,
    entity_type: entityType,
  };
}

function edge(
  id: string,
  source: string,
  target: string,
  relationId: number,
  label: string,
  confidence?: number
): GraphEdgeInput {
  return {
    id,
    relation_id: relationId,
    source,
    target,
    label,
    relation_type: "related_to",
    ...(confidence === undefined ? {} : { confidence }),
  };
}

describe("prepareGraphVisualization", () => {
  it("清理自环和悬空边，并按方向合并平行关系", () => {
    const nodes = [
      node("entity_18", "贵州省六盘水市中级人民法院", "court", 18),
      node("entity_2", "示例供应链有限公司", "company", 2),
    ];
    const edges = [
      edge("edge_b", "entity_18", "entity_2", 102, "宣告", 0.8),
      edge("edge_a", "entity_18", "entity_2", 101, " 裁定  受理 ", 0.95),
      edge("edge_c", "entity_18", "entity_2", 103, "裁定 受理"),
      edge("edge_reverse", "entity_2", "entity_18", 104, "申请", 0.7),
      edge("edge_loop", "entity_2", "entity_2", 105, "案件主体", 1),
      edge("edge_dangling", "entity_404", "entity_2", 106, "未知", 0.5),
    ];

    const result = prepareGraphVisualization(nodes, edges, "entity_18");

    expect(result.nodes[0]).toMatchObject({
      node: { id: "entity_18" },
      isCenter: true,
    });
    expect(result.edges).toHaveLength(2);

    const grouped = result.edges.find(
      ({ edge: item }) => item.source === "entity_18" && item.target === "entity_2"
    );
    expect(grouped).toMatchObject({
      edge: { id: "edge_a", relation_id: 101, confidence: 0.95 },
      displayLabel: "裁定 受理 +1",
      relationCount: 3,
      relationIds: [101, 102, 103],
    });
    expect(grouped?.relationLabels).toEqual(["宣告", "裁定 受理"]);
    expect(grouped?.relations).toEqual([
      { relationId: 101, label: "裁定 受理", confidence: 0.95 },
      { relationId: 102, label: "宣告", confidence: 0.8 },
      { relationId: 103, label: "裁定 受理", confidence: 0 },
    ]);

    expect(result.stats).toMatchObject({
      inputEdgeCount: 6,
      visualEdgeCount: 2,
      removedSelfLoopCount: 1,
      droppedDanglingEdgeCount: 1,
      mergedParallelEdgeCount: 2,
      parallelGroupCount: 1,
    });
  });

  it("同名实体优先用本地化类型消歧，同类型时追加实体 id", () => {
    const result = prepareGraphVisualization([
      node("entity_2", "示例供应链有限公司", "company", 2),
      node("entity_16", " 示例供应链有限公司 ", "organization", 16),
      node("entity_66", "示例供应链有限公司", "enterprise", 66),
      node("entity_4", "同名主体", "company", 4),
      node("entity_5", "同名主体", "company", 5),
    ], []);

    const labels = Object.fromEntries(
      result.nodes.map(({ node: item, displayLabel }) => [item.id, displayLabel])
    );
    expect(labels).toEqual({
      entity_4: "同名主体（公司 · #4）",
      entity_5: "同名主体（公司 · #5）",
      entity_2: "示例供应链有限公司（公司）",
      entity_66: "示例供应链有限公司（企业）",
      entity_16: "示例供应链有限公司（组织）",
    });
    expect(new Set(Object.values(labels)).size).toBe(5);
    expect(result.stats).toMatchObject({
      duplicateLabelGroupCount: 2,
      disambiguatedNodeCount: 5,
    });
  });

  it("截短画布标签但保留原始节点和边文本", () => {
    const longNodeLabel = "这是一个用于验证图谱画布标签截断行为的非常非常长的实体名称";
    const longEdgeLabel = "这是一个用于验证边标签截断行为的非常长的关系名称";
    const result = prepareGraphVisualization(
      [node("entity_1", longNodeLabel, "legal_provision", 1), node("entity_2", "B", "person", 2)],
      [edge("edge_1", "entity_1", "entity_2", 1, longEdgeLabel, 0.5)],
      undefined,
      { maxNodeLabelLength: 10, maxEdgeLabelLength: 8 }
    );

    const longNode = result.nodes.find(({ node: item }) => item.id === "entity_1");
    expect(Array.from(longNode?.displayLabel ?? "")).toHaveLength(10);
    expect(longNode?.displayLabel.endsWith("…")).toBe(true);
    expect(longNode?.node.label).toBe(longNodeLabel);
    expect(Array.from(result.edges[0].displayLabel)).toHaveLength(8);
    expect(result.edges[0].displayLabel.endsWith("…")).toBe(true);
    expect(result.edges[0].edge.label).toBe(longEdgeLabel);
  });

  it("输入顺序变化时输出和代表边选择保持一致", () => {
    const nodes = [
      node("entity_1", "甲", "company", 1),
      node("entity_2", "乙", "person", 2),
      node("entity_3", "丙", "court", 3),
    ];
    const edges = [
      edge("edge_z", "entity_1", "entity_2", 12, "投资", 0.9),
      edge("edge_a", "entity_1", "entity_2", 11, "控制", 0.9),
      edge("edge_3", "entity_3", "entity_1", 13, "裁定", 0.8),
    ];

    const forward = prepareGraphVisualization(nodes, edges, "entity_2");
    const reversed = prepareGraphVisualization(
      [...nodes].reverse(),
      [...edges].reverse(),
      "entity_2"
    );

    expect(reversed).toEqual(forward);
    expect(forward.edges.find(({ edge: item }) => item.source === "entity_1")?.edge.id)
      .toBe("edge_a");
  });

  it("容忍空数组、缺少风险等级和缺少置信度", () => {
    expect(prepareGraphVisualization(undefined, null)).toEqual({
      nodes: [],
      edges: [],
      stats: {
        inputNodeCount: 0,
        visualNodeCount: 0,
        droppedDuplicateNodeCount: 0,
        inputEdgeCount: 0,
        visualEdgeCount: 0,
        removedSelfLoopCount: 0,
        droppedDanglingEdgeCount: 0,
        mergedParallelEdgeCount: 0,
        parallelGroupCount: 0,
        duplicateLabelGroupCount: 0,
        disambiguatedNodeCount: 0,
      },
    });

    const result = prepareGraphVisualization(
      [node("entity_1", "甲", "company", 1), node("entity_2", "乙", "person", 2)],
      [edge("edge_1", "entity_1", "entity_2", 1, "关联")]
    );
    expect(result.nodes[0].node.risk_level).toBeUndefined();
    expect(result.edges[0].edge.confidence).toBeUndefined();
    expect(result.edges[0].relations[0].confidence).toBe(0);
  });

  it("重复节点 id 选择稳定且不会让画布生成重复元素", () => {
    const duplicateA = node("entity_1", "乙名称", "company", 1);
    const duplicateB = node("entity_1", "甲名称", "company", 1);

    const forward = prepareGraphVisualization([duplicateA, duplicateB], []);
    const reversed = prepareGraphVisualization([duplicateB, duplicateA], []);

    expect(forward).toEqual(reversed);
    expect(forward.nodes).toHaveLength(1);
    expect(forward.nodes[0].node.label).toBe("乙名称");
    expect(forward.stats.droppedDuplicateNodeCount).toBe(1);
  });
});

describe("graph label helpers", () => {
  it("按 Unicode 字符而非 UTF-16 code unit 截断", () => {
    expect(truncateGraphLabel("甲😀乙丙", 4)).toBe("甲😀乙丙");
    expect(truncateGraphLabel("甲😀乙丙丁", 4)).toBe("甲😀乙…");
  });

  it("本地化已知类型并规范化未知英文类型", () => {
    expect(graphEntityTypeLabel("law-firm")).toBe("律师事务所");
    expect(graphEntityTypeLabel("Custom Entity")).toBe("custom entity");
    expect(graphEntityTypeLabel("未知类型")).toBe("未知类型");
    expect(graphEntityTypeLabel(undefined)).toBe("未分类");
  });
});

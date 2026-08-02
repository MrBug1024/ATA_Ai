import type { GraphEdge, GraphNode } from "@/lib/types/knowledge-graph";

export type GraphNodeInput = Omit<GraphNode, "risk_level"> &
  Partial<Pick<GraphNode, "risk_level">>;

export type GraphEdgeInput = Omit<GraphEdge, "confidence"> &
  Partial<Pick<GraphEdge, "confidence">>;

export interface VisualGraphNode {
  /** 原始后端节点。完整 label 保留在这里，displayLabel 仅用于画布。 */
  node: GraphNodeInput;
  displayLabel: string;
  typeLabel: string;
  isCenter: boolean;
  isDuplicateLabel: boolean;
}

export interface VisualGraphRelation {
  relationId: number;
  label: string;
  confidence: number;
}

export interface VisualGraphEdge {
  /** 确定性的代表边：置信度最高，置信度相同时按原始边 id 排序。 */
  edge: GraphEdgeInput;
  displayLabel: string;
  relationCount: number;
  relationIds: number[];
  relationLabels: string[];
  relations: VisualGraphRelation[];
}

export interface GraphVisualizationStats {
  inputNodeCount: number;
  visualNodeCount: number;
  droppedDuplicateNodeCount: number;
  inputEdgeCount: number;
  visualEdgeCount: number;
  removedSelfLoopCount: number;
  droppedDanglingEdgeCount: number;
  mergedParallelEdgeCount: number;
  parallelGroupCount: number;
  duplicateLabelGroupCount: number;
  disambiguatedNodeCount: number;
}

export interface GraphVisualization {
  nodes: VisualGraphNode[];
  edges: VisualGraphEdge[];
  stats: GraphVisualizationStats;
}

export interface GraphVisualizationOptions {
  maxNodeLabelLength?: number;
  maxEdgeLabelLength?: number;
}

const DEFAULT_MAX_NODE_LABEL_LENGTH = 18;
const DEFAULT_MAX_EDGE_LABEL_LENGTH = 16;

const ENTITY_TYPE_LABELS: Record<string, string> = {
  address: "地址",
  asset: "资产",
  bank: "银行",
  case: "案件",
  company: "公司",
  contract: "合同",
  court: "法院",
  date: "日期",
  document: "文书",
  enterprise: "企业",
  government: "政府机构",
  government_agency: "政府机构",
  individual: "个人",
  law: "法律法规",
  law_firm: "律师事务所",
  legal_provision: "法律条文",
  location: "地点",
  mine: "矿山",
  mine_right: "矿业权",
  mining_right: "矿业权",
  organization: "组织",
  person: "个人",
  procuratorate: "检察院",
  public_security: "公安机关",
};

function compareText(left: string, right: string): number {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function normalizeWhitespace(value: unknown): string {
  return String(value ?? "")
    .normalize("NFKC")
    .trim()
    .replace(/\s+/g, " ");
}

function normalizeForComparison(value: unknown): string {
  return normalizeWhitespace(value).toLowerCase();
}

function normalizeEntityType(value: unknown): string {
  return normalizeForComparison(value).replace(/[\s-]+/g, "_");
}

function confidenceValue(edge: GraphEdgeInput): number {
  return typeof edge.confidence === "number" && Number.isFinite(edge.confidence)
    ? edge.confidence
    : 0;
}

function compareNumbers(left: number, right: number): number {
  return left === right ? 0 : left < right ? -1 : 1;
}

function compareNodes(left: GraphNodeInput, right: GraphNodeInput): number {
  return (
    compareText(normalizeForComparison(left.label), normalizeForComparison(right.label)) ||
    compareText(normalizeEntityType(left.entity_type), normalizeEntityType(right.entity_type)) ||
    compareText(String(left.id), String(right.id)) ||
    compareNumbers(left.entity_id, right.entity_id) ||
    compareText(String(left.risk_level ?? ""), String(right.risk_level ?? ""))
  );
}

function compareEdgesByRepresentativePriority(
  left: GraphEdgeInput,
  right: GraphEdgeInput
): number {
  return (
    compareNumbers(confidenceValue(right), confidenceValue(left)) ||
    compareText(String(left.id), String(right.id)) ||
    compareNumbers(left.relation_id, right.relation_id) ||
    compareText(normalizeForComparison(left.label), normalizeForComparison(right.label)) ||
    compareText(normalizeForComparison(left.relation_type), normalizeForComparison(right.relation_type))
  );
}

function positiveInteger(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : fallback;
}

/** 按 Unicode 字符截断，避免中文和 emoji 被切成无效的半个字符。 */
export function truncateGraphLabel(value: unknown, maxLength: number): string {
  const normalized = normalizeWhitespace(value);
  const characters = Array.from(normalized);
  if (characters.length <= maxLength) return normalized;
  if (maxLength <= 1) return "…";
  return `${characters.slice(0, maxLength - 1).join("")}…`;
}

/** 后端 entity_type 可能中英混用；已知英文类型本地化，其余做稳定格式化。 */
export function graphEntityTypeLabel(entityType: unknown): string {
  const normalized = normalizeEntityType(entityType);
  if (!normalized || normalized === "unknown") return "未分类";
  const localized = ENTITY_TYPE_LABELS[normalized];
  if (localized) return localized;

  const original = normalizeWhitespace(entityType);
  if (/[^\u0000-\u007f]/.test(original)) return original;
  return normalized.replace(/_/g, " ");
}

function truncateWithSuffix(base: string, suffix: string, maxLength: number): string {
  const suffixLength = Array.from(suffix).length;
  if (suffixLength >= maxLength) return truncateGraphLabel(suffix, maxLength);
  return `${truncateGraphLabel(base, maxLength - suffixLength)}${suffix}`;
}

function duplicateSuffix(
  node: GraphNodeInput,
  group: readonly GraphNodeInput[],
  typeLabel: string
): string {
  const matchingTypeCount = group.filter(
    (item) => graphEntityTypeLabel(item.entity_type) === typeLabel
  ).length;
  if (matchingTypeCount === 1) return `（${typeLabel}）`;

  const sameEntityIdCount = group.filter((item) => item.entity_id === node.entity_id).length;
  const identifier = sameEntityIdCount === 1 ? node.entity_id : node.id;
  return `（${typeLabel} · #${identifier}）`;
}

function isCenterNode(node: GraphNodeInput, centerNodeId: string | number | null | undefined): boolean {
  if (centerNodeId === null || centerNodeId === undefined) return false;
  return typeof centerNodeId === "number"
    ? node.entity_id === centerNodeId
    : node.id === centerNodeId;
}

function buildVisualNodes(
  inputNodes: readonly GraphNodeInput[],
  centerNodeId: string | number | null | undefined,
  maxLabelLength: number
): {
  nodes: VisualGraphNode[];
  duplicateLabelGroupCount: number;
  disambiguatedNodeCount: number;
  droppedDuplicateNodeCount: number;
} {
  const nodesById = new Map<string, GraphNodeInput>();
  for (const node of [...inputNodes].sort(compareNodes)) {
    if (!nodesById.has(node.id)) nodesById.set(node.id, node);
  }

  const uniqueNodes = [...nodesById.values()];
  const duplicateGroups = new Map<string, GraphNodeInput[]>();
  for (const node of uniqueNodes) {
    const key = normalizeForComparison(node.label);
    const group = duplicateGroups.get(key) ?? [];
    group.push(node);
    duplicateGroups.set(key, group);
  }

  const duplicateLabelGroupCount = [...duplicateGroups.values()].filter(
    (group) => group.length > 1
  ).length;
  let disambiguatedNodeCount = 0;

  const nodes = uniqueNodes.map((node): VisualGraphNode => {
    const fullLabel = normalizeWhitespace(node.label) || "未命名实体";
    const typeLabel = graphEntityTypeLabel(node.entity_type);
    const group = duplicateGroups.get(normalizeForComparison(node.label)) ?? [node];
    const isDuplicateLabel = group.length > 1;
    if (isDuplicateLabel) disambiguatedNodeCount += 1;

    return {
      node,
      displayLabel: isDuplicateLabel
        ? truncateWithSuffix(
            fullLabel,
            duplicateSuffix(node, group, typeLabel),
            maxLabelLength
          )
        : truncateGraphLabel(fullLabel, maxLabelLength),
      typeLabel,
      isCenter: isCenterNode(node, centerNodeId),
      isDuplicateLabel,
    };
  });

  nodes.sort((left, right) => {
    if (left.isCenter !== right.isCenter) return left.isCenter ? -1 : 1;
    return compareNodes(left.node, right.node);
  });

  return {
    nodes,
    duplicateLabelGroupCount,
    disambiguatedNodeCount,
    droppedDuplicateNodeCount: inputNodes.length - uniqueNodes.length,
  };
}

function uniqueRelationLabels(edges: readonly GraphEdgeInput[]): string[] {
  const labelsByKey = new Map<string, string>();
  for (const edge of edges) {
    const label = normalizeWhitespace(edge.label) || "未命名关系";
    const key = normalizeForComparison(label);
    const current = labelsByKey.get(key);
    if (!current || compareText(label, current) < 0) labelsByKey.set(key, label);
  }
  return [...labelsByKey.values()].sort(compareText);
}

function edgeDisplayLabel(
  representative: GraphEdgeInput,
  labels: readonly string[],
  relationCount: number,
  maxLength: number
): string {
  const representativeLabel = normalizeWhitespace(representative.label) || labels[0] || "未命名关系";
  const otherLabelCount = labels.filter(
    (label) => normalizeForComparison(label) !== normalizeForComparison(representativeLabel)
  ).length;
  const suffix = otherLabelCount > 0
    ? ` +${otherLabelCount}`
    : relationCount > 1
      ? ` ×${relationCount}`
      : "";
  return truncateWithSuffix(representativeLabel, suffix, maxLength);
}

function buildVisualEdge(
  groupedEdges: readonly GraphEdgeInput[],
  maxLabelLength: number
): VisualGraphEdge {
  const sortedEdges = [...groupedEdges].sort(compareEdgesByRepresentativePriority);
  const representative = sortedEdges[0];
  const relationLabels = uniqueRelationLabels(sortedEdges);

  return {
    edge: representative,
    displayLabel: edgeDisplayLabel(
      representative,
      relationLabels,
      sortedEdges.length,
      maxLabelLength
    ),
    relationCount: sortedEdges.length,
    relationIds: sortedEdges.map((edge) => edge.relation_id),
    relationLabels,
    relations: sortedEdges.map((edge) => ({
      relationId: edge.relation_id,
      label: normalizeWhitespace(edge.label) || "未命名关系",
      confidence: confidenceValue(edge),
    })),
  };
}

/**
 * 把后端子图清洗为稳定的画布数据。分组保留方向，A→B 与 B→A 不会合并。
 */
export function prepareGraphVisualization(
  inputNodes: readonly GraphNodeInput[] | null | undefined,
  inputEdges: readonly GraphEdgeInput[] | null | undefined,
  centerNodeId?: string | number | null,
  options: GraphVisualizationOptions = {}
): GraphVisualization {
  const rawNodes = inputNodes ?? [];
  const rawEdges = inputEdges ?? [];
  const maxNodeLabelLength = positiveInteger(
    options.maxNodeLabelLength,
    DEFAULT_MAX_NODE_LABEL_LENGTH
  );
  const maxEdgeLabelLength = positiveInteger(
    options.maxEdgeLabelLength,
    DEFAULT_MAX_EDGE_LABEL_LENGTH
  );

  const visualNodes = buildVisualNodes(rawNodes, centerNodeId, maxNodeLabelLength);
  const nodeIds = new Set(visualNodes.nodes.map(({ node }) => node.id));
  let removedSelfLoopCount = 0;
  let droppedDanglingEdgeCount = 0;
  const groupedEdges = new Map<string, GraphEdgeInput[]>();

  for (const edge of rawEdges) {
    if (edge.source === edge.target) {
      removedSelfLoopCount += 1;
      continue;
    }
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
      droppedDanglingEdgeCount += 1;
      continue;
    }

    const key = JSON.stringify([edge.source, edge.target]);
    const group = groupedEdges.get(key) ?? [];
    group.push(edge);
    groupedEdges.set(key, group);
  }

  const edges = [...groupedEdges.values()]
    .map((group) => buildVisualEdge(group, maxEdgeLabelLength))
    .sort((left, right) => (
      compareText(left.edge.source, right.edge.source) ||
      compareText(left.edge.target, right.edge.target) ||
      compareEdgesByRepresentativePriority(left.edge, right.edge)
    ));
  const retainedRawEdgeCount = edges.reduce((sum, edge) => sum + edge.relationCount, 0);

  return {
    nodes: visualNodes.nodes,
    edges,
    stats: {
      inputNodeCount: rawNodes.length,
      visualNodeCount: visualNodes.nodes.length,
      droppedDuplicateNodeCount: visualNodes.droppedDuplicateNodeCount,
      inputEdgeCount: rawEdges.length,
      visualEdgeCount: edges.length,
      removedSelfLoopCount,
      droppedDanglingEdgeCount,
      mergedParallelEdgeCount: retainedRawEdgeCount - edges.length,
      parallelGroupCount: edges.filter((edge) => edge.relationCount > 1).length,
      duplicateLabelGroupCount: visualNodes.duplicateLabelGroupCount,
      disambiguatedNodeCount: visualNodes.disambiguatedNodeCount,
    },
  };
}

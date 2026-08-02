// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { GraphEdge, GraphNode } from "@/lib/types/knowledge-graph";
import type {
  VisualGraphEdge,
  VisualGraphNode,
} from "@/components/knowledge-graph/graph-visualization";

vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

interface CapturedCanvasProps {
  nodes: VisualGraphNode[];
  edges: VisualGraphEdge[];
  hiddenNeighborCounts?: Map<string, number>;
  showEdgeLabels?: boolean;
  fitRequestKey?: number;
  onNodeClick?: (
    nodeId: string,
    entityId: number,
    label: string,
    entityType: string,
    riskLevel: string
  ) => void;
  onNodeExpand?: (nodeId: string) => void;
}

let lastCanvasProps: CapturedCanvasProps | null = null;
vi.mock("@/components/knowledge-graph/graph-canvas", () => ({
  GraphCanvas: (props: CapturedCanvasProps) => {
    lastCanvasProps = props;
    return <div data-testid="graph-canvas" />;
  },
}));
vi.mock("@/components/knowledge-graph/relation-detail-panel", () => ({
  RelationDetailPanel: () => null,
}));

const mockFetch = vi.fn();
const mockReset = vi.fn();
let subgraphState = {
  data: null,
  isMutating: false,
  error: null as string | null,
  fetch: mockFetch,
  reset: mockReset,
};
vi.mock("@/lib/hooks/use-graph-subgraph", () => ({
  useGraphSubgraph: () => subgraphState,
}));

vi.mock("@/lib/hooks/use-graph-entities", () => ({
  useGraphEntities: () => ({
    entities: [
      { entity_id: 2, label: "晨光煤矿", entity_type: "company", degree: 18 },
      { entity_id: 18, label: "某法院", entity_type: "court", degree: 22 },
    ],
    isLoading: false,
    error: null,
  }),
}));

const mockClose = vi.fn();
let storeState = {
  open: false,
  caseId: 0,
  centerEntityId: undefined as number | undefined,
  reportRef: null as string | null,
  closeModal: mockClose,
};
vi.mock("@/lib/stores/graph-modal", () => ({
  useGraphModalStore: (selector?: (state: typeof storeState) => unknown) =>
    selector ? selector(storeState) : storeState,
}));

function renderModal(element: React.ReactElement) {
  return render(<TooltipProvider>{element}</TooltipProvider>);
}

describe("GraphModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    lastCanvasProps = null;
    mockFetch.mockReset().mockResolvedValue({ nodes: [], edges: [] });
    subgraphState = {
      data: null,
      isMutating: false,
      error: null,
      fetch: mockFetch,
      reset: mockReset,
    };
  });

  it("renders nothing when closed", async () => {
    storeState = { ...storeState, open: false };
    const { GraphModal } = await import("@/components/knowledge-graph/graph-modal");
    const { container } = renderModal(<GraphModal />);
    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });

  it("renders graph canvas when open with centerEntityId", async () => {
    storeState = { ...storeState, open: true, caseId: 116, centerEntityId: 12 };
    const { GraphModal } = await import("@/components/knowledge-graph/graph-modal");
    renderModal(<GraphModal />);
    expect(await screen.findByTestId("graph-canvas")).toBeTruthy();
  });

  it("打开即按最大深度一次拉全量,不再有深度切换按钮", async () => {
    storeState = { ...storeState, open: true, caseId: 116, centerEntityId: 12 };
    const { GraphModal } = await import("@/components/knowledge-graph/graph-modal");
    renderModal(<GraphModal />);
    await waitFor(() => expect(mockFetch).toHaveBeenCalledWith({
      case_id: 116,
      center_entity_id: 12,
      depth: 3,
    }));
    expect(screen.queryByText("深度")).toBeNull();
  });

  it("单击只选择节点,通过明确命令逐级展开", async () => {
    const nodes = [
      { id: "entity_12", entity_id: 12, label: "中心", entity_type: "company", risk_level: "low" },
      { id: "entity_2", entity_id: 2, label: "邻居", entity_type: "company", risk_level: "low" },
      { id: "entity_3", entity_id: 3, label: "二跳", entity_type: "person", risk_level: "low" },
    ] satisfies GraphNode[];
    const edges = [
      { id: "r1", relation_id: 1, source: "entity_12", target: "entity_2", label: "担保", relation_type: "g", confidence: 0.9 },
      { id: "r2", relation_id: 2, source: "entity_2", target: "entity_3", label: "出资", relation_type: "i", confidence: 0.8 },
    ] satisfies GraphEdge[];
    mockFetch.mockResolvedValueOnce({ nodes, edges });

    storeState = { ...storeState, open: true, caseId: 116, centerEntityId: 12 };
    const { GraphModal } = await import("@/components/knowledge-graph/graph-modal");
    renderModal(<GraphModal />);

    await waitFor(() => expect(lastCanvasProps?.nodes).toHaveLength(2));
    expect(lastCanvasProps!.nodes.map(({ node }) => node.id).sort()).toEqual([
      "entity_12",
      "entity_2",
    ]);
    expect(lastCanvasProps!.hiddenNeighborCounts?.get("entity_2")).toBe(1);

    await act(async () => {
      lastCanvasProps!.onNodeClick?.("entity_2", 2, "邻居", "company", "low");
    });
    expect(lastCanvasProps!.nodes).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "展开 +1" }));
    await waitFor(() => expect(lastCanvasProps?.nodes).toHaveLength(3));
    expect(lastCanvasProps!.edges.map(({ edge }) => edge.id).sort()).toEqual(["r1", "r2"]);
  });

  it("聚合平行边、自关联不入画布，并可切换关系标签", async () => {
    const nodes = [
      { id: "entity_12", entity_id: 12, label: "中心", entity_type: "court" },
      { id: "entity_2", entity_id: 2, label: "煤矿", entity_type: "company" },
    ] satisfies GraphNode[];
    const edges = [
      { id: "r1", relation_id: 1, source: "entity_12", target: "entity_2", label: "裁定", relation_type: "r", confidence: 0.9 },
      { id: "r2", relation_id: 2, source: "entity_12", target: "entity_2", label: "宣告", relation_type: "r", confidence: 0.8 },
      { id: "loop", relation_id: 3, source: "entity_2", target: "entity_2", label: "案件主体", relation_type: "r", confidence: 1 },
    ] satisfies GraphEdge[];
    mockFetch.mockResolvedValueOnce({ nodes, edges });
    storeState = { ...storeState, open: true, caseId: 116, centerEntityId: 12 };

    const { GraphModal } = await import("@/components/knowledge-graph/graph-modal");
    renderModal(<GraphModal />);

    await waitFor(() => expect(lastCanvasProps?.edges).toHaveLength(1));
    expect(lastCanvasProps!.edges[0]).toMatchObject({ relationCount: 2 });
    expect(screen.getByText(/合并 1 条平行关系/)).toBeTruthy();
    expect(screen.getByText(/忽略 1 条自关联/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "显示关系标签" }));
    await waitFor(() => expect(lastCanvasProps?.showEdgeLabels).toBe(true));
    expect(screen.getByRole("button", { name: "隐藏关系标签" })).toBeTruthy();
  });

  it("子图加载失败时显示错误信息而非空白画布", async () => {
    mockFetch.mockRejectedValueOnce(new Error("子图加载失败：网络错误"));
    storeState = { ...storeState, open: true, caseId: 116, centerEntityId: 12 };
    const { GraphModal } = await import("@/components/knowledge-graph/graph-modal");
    renderModal(<GraphModal />);
    expect(await screen.findByText("子图加载失败：网络错误")).toBeTruthy();
    expect(screen.queryByTestId("graph-canvas")).toBeNull();
  });

  it("无中心实体时展示实体选择列表", async () => {
    storeState = { ...storeState, open: true, caseId: 116, centerEntityId: undefined };
    const { GraphModal } = await import("@/components/knowledge-graph/graph-modal");
    renderModal(<GraphModal />);
    expect(mockFetch).not.toHaveBeenCalled();
    expect(screen.getByText("中心实体")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "搜索实体" })).toBeTruthy();
    expect(screen.getByText("晨光煤矿")).toBeTruthy();
    expect(screen.getByText("某法院")).toBeTruthy();
  });
});

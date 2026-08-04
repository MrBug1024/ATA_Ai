// tests/unit/relation-detail-panel.test.tsx
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

Object.defineProperties(HTMLElement.prototype, {
  hasPointerCapture: { configurable: true, value: vi.fn(() => false) },
  setPointerCapture: { configurable: true, value: vi.fn() },
  releasePointerCapture: { configurable: true, value: vi.fn() },
  scrollIntoView: { configurable: true, value: vi.fn() },
});

const mockFetch = vi.fn().mockResolvedValue(undefined);
const mockReset = vi.fn();
vi.mock("@/lib/hooks/use-relation-evidence", () => ({
  useRelationEvidence: () => ({
    data: null, isMutating: false, error: null, fetch: mockFetch, reset: mockReset,
  }),
}));

const mockOpenDrawer = vi.fn();
vi.mock("@/lib/stores/evidence-drawer", () => ({
  useEvidenceDrawerStore: (sel?: (s: { openDrawer: typeof mockOpenDrawer }) => unknown) => {
    const state = { openDrawer: mockOpenDrawer };
    return sel ? sel(state) : state;
  },
}));

describe("RelationDetailPanel", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders nothing when selection is null", async () => {
    const { RelationDetailPanel } = await import("@/components/knowledge-graph/relation-detail-panel");
    const { container } = render(<RelationDetailPanel selection={null} caseId={116} reportRef={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("calls fetch with relation_id when edge selected", async () => {
    const { RelationDetailPanel } = await import("@/components/knowledge-graph/relation-detail-panel");
    const selection = { type: "edge" as const, edgeId: "r-1", relationId: 77, label: "担保" };
    render(<RelationDetailPanel selection={selection} caseId={116} reportRef={null} />);
    expect(mockFetch).toHaveBeenCalledWith({ case_id: 116, relation_id: 77 });
  });

  it("shows entity label and type when node selected", async () => {
    const { RelationDetailPanel } = await import("@/components/knowledge-graph/relation-detail-panel");
    const selection = { type: "node" as const, nodeId: "e-1", entityId: 1, label: "示例制造有限公司", entityType: "company", riskLevel: "high" };
    render(<RelationDetailPanel selection={selection} caseId={116} reportRef={null} />);
    expect(screen.getByText("示例制造有限公司")).toBeTruthy();
    expect(screen.getByText("company")).toBeTruthy();
  });

  it("does not call fetch when node selected", async () => {
    const { RelationDetailPanel } = await import("@/components/knowledge-graph/relation-detail-panel");
    const selection = { type: "node" as const, nodeId: "e-1", entityId: 1, label: "X", entityType: "company", riskLevel: "low" };
    render(<RelationDetailPanel selection={selection} caseId={116} reportRef={null} />);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("closes the detail panel from its icon button", async () => {
    const onClose = vi.fn();
    const { RelationDetailPanel } = await import("@/components/knowledge-graph/relation-detail-panel");
    const selection = { type: "node" as const, nodeId: "e-1", entityId: 1, label: "X", entityType: "company", riskLevel: "low" };
    render(
      <RelationDetailPanel
        selection={selection}
        caseId={116}
        reportRef={null}
        onClose={onClose}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "关闭详情" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("shows an identifiable relation picker for an aggregated edge", async () => {
    const { RelationDetailPanel } = await import("@/components/knowledge-graph/relation-detail-panel");
    const selection = {
      type: "edge" as const,
      edgeId: "cluster-18-2",
      relationId: 77,
      label: "担保",
      relations: [
        { relationId: 77, label: "担保", confidence: 0.91 },
        { relationId: 78, label: "担保", confidence: 0.82 },
      ],
    };

    render(<RelationDetailPanel selection={selection} caseId={116} reportRef={null} />);

    expect(screen.getByText("关系详情 · 2 条关系")).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "选择具体关系" }).textContent).toContain(
      "担保 · #77 · 置信度 91%",
    );
    expect(mockFetch).toHaveBeenCalledWith({ case_id: 116, relation_id: 77 });
  });

  it("fetches evidence for the relation chosen from an aggregated edge", async () => {
    const { RelationDetailPanel } = await import("@/components/knowledge-graph/relation-detail-panel");
    const selection = {
      type: "edge" as const,
      edgeId: "cluster-18-2",
      relationId: 77,
      label: "裁定受理",
      relations: [
        { relationId: 77, label: "裁定受理", confidence: 0.91 },
        { relationId: 78, label: "宣告", confidence: 0.82 },
      ],
    };

    render(<RelationDetailPanel selection={selection} caseId={116} reportRef={null} />);

    const trigger = screen.getByRole("combobox", { name: "选择具体关系" });
    fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: "mouse" });
    const option = await screen.findByRole("option", { name: "宣告 · 置信度 82%" });
    fireEvent.click(option);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith({ case_id: 116, relation_id: 78 });
    });
    expect(screen.getByText("宣告")).toBeTruthy();
  });

  it("resets the active relation when the selected edge changes", async () => {
    const { RelationDetailPanel } = await import("@/components/knowledge-graph/relation-detail-panel");
    const firstSelection = {
      type: "edge" as const,
      edgeId: "cluster-18-2",
      relationId: 77,
      label: "裁定受理",
      relations: [
        { relationId: 77, label: "裁定受理", confidence: 0.91 },
        { relationId: 78, label: "宣告", confidence: 0.82 },
      ],
    };
    const nextSelection = {
      type: "edge" as const,
      edgeId: "cluster-21-3",
      relationId: 99,
      label: "投资",
      relations: [
        { relationId: 99, label: "投资", confidence: 0.88 },
        { relationId: 100, label: "持股", confidence: 0.75 },
      ],
    };

    const { rerender } = render(
      <RelationDetailPanel selection={firstSelection} caseId={116} reportRef={null} />,
    );
    rerender(<RelationDetailPanel selection={nextSelection} caseId={116} reportRef={null} />);

    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: "选择具体关系" }).textContent).toContain(
        "投资 · 置信度 88%",
      );
    });
    expect(mockFetch).toHaveBeenLastCalledWith({ case_id: 116, relation_id: 99 });
  });
});

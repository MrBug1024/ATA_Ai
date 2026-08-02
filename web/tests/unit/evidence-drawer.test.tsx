// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock PageViewer so we don't need real images
vi.mock("@/components/knowledge-graph/page-viewer", () => ({
  PageViewer: () => <div data-testid="page-viewer" />,
}));

// Mock the evidence resolve hook
const mockResolve = vi.fn();
const mockReset = vi.fn();
vi.mock("@/lib/hooks/use-evidence-resolve", () => ({
  useEvidenceResolve: () => ({
    data: null,
    isMutating: false,
    error: null,
    resolve: mockResolve,
    reset: mockReset,
  }),
}));

// Mock store
const mockClose = vi.fn();
let storeState = { open: false, caseId: 0, reportRef: "", citationId: "", selectedEvidenceIndex: 0, currentPage: null, closeDrawer: mockClose, setSelectedEvidenceIndex: vi.fn(), setCurrentPage: vi.fn() };
vi.mock("@/lib/stores/evidence-drawer", () => ({
  useEvidenceDrawerStore: (sel?: (s: typeof storeState) => unknown) => sel ? sel(storeState) : storeState,
}));

describe("EvidenceDrawer", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("does not render Sheet content when closed", async () => {
    storeState = { ...storeState, open: false };
    const { EvidenceDrawer } = await import("@/components/knowledge-graph/evidence-drawer");
    render(<EvidenceDrawer />);
    expect(screen.queryByTestId("evidence-drawer-content")).toBeNull();
  });

  it("calls resolve when opened with citationId", async () => {
    storeState = { ...storeState, open: true, caseId: 116, reportRef: "r", citationId: "1" };
    mockResolve.mockResolvedValueOnce({ primary_page: null });
    const { EvidenceDrawer } = await import("@/components/knowledge-graph/evidence-drawer");
    render(<EvidenceDrawer />);
    expect(mockResolve).toHaveBeenCalledWith({ case_id: 116, report_ref: "r", citation_id: "1" });
  });

  it("does not throw in loading state", async () => {
    storeState = { ...storeState, open: true, caseId: 116, reportRef: "r", citationId: "1" };
    mockResolve.mockResolvedValueOnce({ primary_page: null });
    const { EvidenceDrawer } = await import("@/components/knowledge-graph/evidence-drawer");
    expect(() => render(<EvidenceDrawer />)).not.toThrow();
  });
});

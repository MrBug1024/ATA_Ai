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
let resolveData: {
  claim_text?: string;
  evidences?: Array<Record<string, unknown>>;
  primary_page?: null;
} | null = null;
vi.mock("@/lib/hooks/use-evidence-resolve", () => ({
  useEvidenceResolve: () => ({
    data: resolveData,
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
  beforeEach(() => {
    vi.clearAllMocks();
    resolveData = null;
  });

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

  it("labels sheet-row evidence by worksheet and row range, not a PDF page", async () => {
    storeState = { ...storeState, open: true, caseId: 116, reportRef: "r", citationId: "1" };
    resolveData = {
      claim_text: "咨询费合同抽查表存在整额流水",
      primary_page: null,
      evidences: [
        {
          chunk_id: "chunk-45",
          file_id: 4,
          file_name: "咨询费合同抽查表.xlsx",
          page_no: 1,
          quote_text: "第 45 至 47 行",
          bbox_list: [],
          page_image_ref: "",
          source_page_id: 0,
          locator_kind: "sheet_row",
          sheet_name: "咨询费合同抽查表",
          row_start: 45,
          row_end: 47,
        },
      ],
    };
    mockResolve.mockResolvedValueOnce({ primary_page: null });
    const { EvidenceDrawer } = await import("@/components/knowledge-graph/evidence-drawer");
    render(<EvidenceDrawer variant="inline" />);

    expect(screen.getByText("工作表：咨询费合同抽查表 · 行：45-47")).toBeTruthy();
    expect(screen.queryByText("第 1 页")).toBeNull();
  });
});

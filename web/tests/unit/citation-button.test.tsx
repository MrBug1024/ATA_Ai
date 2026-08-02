// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";

const mockOpen = vi.fn();
vi.mock("@/lib/stores/evidence-drawer", () => ({
  useEvidenceDrawerStore: (sel?: (s: { openDrawer: typeof mockOpen }) => unknown) => {
    const state = { openDrawer: mockOpen };
    return sel ? sel(state) : state;
  },
}));

let ctxValue = { caseId: 116 as number | null, reportRef: "final_report:demo-116" as string | null };
vi.mock("@/lib/assistant-ui/evidence-context", () => ({
  useEvidenceContext: () => ctxValue,
}));

describe("CitationButton", () => {
  beforeEach(() => { mockOpen.mockReset(); });

  it("renders citation number", async () => {
    ctxValue = { caseId: 116, reportRef: "final_report:demo-116" };
    const { CitationButton } = await import("@/components/knowledge-graph/citation-button");
    const { getByText } = render(<CitationButton citationId="3" />);
    expect(getByText("3")).toBeTruthy();
  });

  it("calls openDrawer with correct params on click", async () => {
    ctxValue = { caseId: 116, reportRef: "final_report:demo-116" };
    const { CitationButton } = await import("@/components/knowledge-graph/citation-button");
    const { getByRole } = render(<CitationButton citationId="2" />);
    fireEvent.click(getByRole("button"));
    expect(mockOpen).toHaveBeenCalledWith({
      caseId: 116, reportRef: "final_report:demo-116", citationId: "2",
    });
  });

  it("does nothing on click when reportRef is null", async () => {
    ctxValue = { caseId: 116, reportRef: null };
    const { CitationButton } = await import("@/components/knowledge-graph/citation-button");
    const { getByRole } = render(<CitationButton citationId="1" />);
    fireEvent.click(getByRole("button"));
    expect(mockOpen).not.toHaveBeenCalled();
  });
});

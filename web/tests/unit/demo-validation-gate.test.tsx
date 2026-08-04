// tests/unit/demo-validation-gate.test.tsx
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const mockValidate = vi.fn();
const mockReset = vi.fn();
let mockHookState: {
  data: unknown;
  isMutating: boolean;
  error: string | null;
  validate: typeof mockValidate;
  reset: typeof mockReset;
} = { data: null, isMutating: false, error: null, validate: mockValidate, reset: mockReset };

vi.mock("@/lib/hooks/use-demo-case-validate", () => ({
  useDemoCaseValidate: () => mockHookState,
}));

describe("DemoValidationGate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockHookState = { data: null, isMutating: false, error: null, validate: mockValidate, reset: mockReset };
  });

  it("does not render when reportRef is null", async () => {
    const { DemoValidationGate } = await import("@/components/knowledge-graph/demo-validation-gate");
    const { container } = render(<DemoValidationGate caseId={116} reportRef={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders validate button when reportRef provided and no data", async () => {
    const { DemoValidationGate } = await import("@/components/knowledge-graph/demo-validation-gate");
    render(<DemoValidationGate caseId={116} reportRef="final_report:demo-116" />);
    expect(screen.getByRole("button", { name: /验收/ })).toBeTruthy();
  });

  it("calls validate with correct args on click", async () => {
    const { DemoValidationGate } = await import("@/components/knowledge-graph/demo-validation-gate");
    render(<DemoValidationGate caseId={116} reportRef="final_report:demo-116" />);
    fireEvent.click(screen.getByRole("button", { name: /验收/ }));
    expect(mockValidate).toHaveBeenCalledWith({ case_id: 116, report_ref: "final_report:demo-116" });
  });

  it("shows ready badge when validation passes", async () => {
    mockHookState = {
      data: { ready: true, total_citations: 3, passed_citations: 3, failed_citations: 0, checks: [], issues: [], case_id: 116, report_ref: "r" },
      isMutating: false, error: null, validate: mockValidate, reset: mockReset,
    };
    const { DemoValidationGate } = await import("@/components/knowledge-graph/demo-validation-gate");
    render(<DemoValidationGate caseId={116} reportRef="r" />);
    expect(screen.getByText(/可发布/)).toBeTruthy();
  });

  it("shows failed badge and failing checks when ready is false", async () => {
    mockHookState = {
      data: {
        ready: false, total_citations: 3, passed_citations: 1, failed_citations: 2,
        checks: [
          { citation_id: "1", claim_id: 1, claim_text: "示例制造有限公司是被审计单位", ok: false, evidence_count: 0, anchor_count: 0, file_id: 0, page_no: 0, issues: ["缺少页图证据"] },
        ],
        issues: ["citation [1] 缺少证据"],
        case_id: 116, report_ref: "r",
      },
      isMutating: false, error: null, validate: mockValidate, reset: mockReset,
    };
    const { DemoValidationGate } = await import("@/components/knowledge-graph/demo-validation-gate");
    render(<DemoValidationGate caseId={116} reportRef="r" />);
    expect(screen.getByText(/2 条角标失败/)).toBeTruthy();
    expect(screen.getByText("示例制造有限公司是被审计单位")).toBeTruthy();
    expect(screen.getByText("缺少页图证据")).toBeTruthy();
  });
});

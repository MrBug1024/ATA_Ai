// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { CorrectionModel } from "@/lib/types/case-analytics";

const mocks = vi.hoisted(() => ({
  useCaseCorrections: vi.fn(),
  create: vi.fn(),
  revoke: vi.fn(),
  refresh: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/hooks/use-case-corrections", () => ({
  useCaseCorrections: (...args: unknown[]) => mocks.useCaseCorrections(...args),
}));
vi.mock("@/lib/hooks/use-create-correction", () => ({
  useCreateCorrection: () => ({
    data: null,
    isMutating: false,
    error: null,
    create: mocks.create,
    reset: vi.fn(),
  }),
}));
vi.mock("@/lib/hooks/use-revoke-correction", () => ({
  useRevokeCorrection: () => ({
    data: null,
    isMutating: false,
    error: null,
    revoke: mocks.revoke,
    reset: vi.fn(),
  }),
}));
vi.mock("sonner", () => ({
  toast: { success: mocks.toastSuccess, error: mocks.toastError },
}));
vi.mock("@/lib/hooks/use-auth", () => ({
  useAuth: () => ({ user: { user_id: "u1", username: "王律师" } }),
}));

const activeCorrection: CorrectionModel = {
  id: 7,
  case_id: 116,
  target: "房产估值",
  instruction: "以最新评估报告为准",
  source_query: "估值需要调整",
  operator_id: "u1",
  operator_name: "王律师",
  operator_meta: {},
  scope: "全案",
  origin: "manual",
  status: "active",
  superseded_by: null,
  created_at: "2026-07-16T08:00:00Z",
  updated_at: "2026-07-16T08:00:00Z",
};

describe("CorrectionsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.create.mockResolvedValue(activeCorrection);
    mocks.revoke.mockResolvedValue({ ...activeCorrection, status: "revoked" });
    mocks.refresh.mockResolvedValue(undefined);
    mocks.useCaseCorrections.mockReturnValue({
      corrections: [
        activeCorrection,
        { ...activeCorrection, id: 8, target: "旧估值", status: "revoked" },
      ],
      isLoading: false,
      error: null,
      refresh: mocks.refresh,
    });
  });

  it("submits a trimmed authoritative correction", async () => {
    const { CorrectionsPanel } = await import("@/components/cases/corrections-panel");
    render(<CorrectionsPanel caseId={116} />);

    fireEvent.change(screen.getByLabelText("订正标的"), {
      target: { value: "  房产估值  " },
    });
    fireEvent.change(screen.getByLabelText("强制修正指令"), {
      target: { value: "  以最新报告为准  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "新增订正" }));

    await waitFor(() =>
      expect(mocks.create).toHaveBeenCalledWith({
        target: "房产估值",
        instruction: "以最新报告为准",
        source_query: "",
        scope: "全案",
        operator_id: "u1",
        operator_name: "王律师",
      })
    );
    expect(mocks.refresh).toHaveBeenCalled();
    expect(mocks.toastSuccess).toHaveBeenCalledWith("权威订正已生效");
  });

  it("requests history and only allows active corrections to be revoked", async () => {
    const { CorrectionsPanel } = await import("@/components/cases/corrections-panel");
    render(<CorrectionsPanel caseId={116} />);

    fireEvent.click(screen.getByRole("button", { name: "查看历史" }));
    await waitFor(() => expect(mocks.useCaseCorrections).toHaveBeenCalledWith(116, true));

    expect(screen.getAllByRole("button", { name: /撤销订正/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "撤销订正 房产估值" }));
    await waitFor(() => expect(mocks.revoke).toHaveBeenCalledWith(7));
    expect(mocks.toastSuccess).toHaveBeenCalledWith("订正已撤销");
  });
});

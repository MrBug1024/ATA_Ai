// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { DeadlineBoardResponse } from "@/lib/types/case-analytics";

const mocks = vi.hoisted(() => ({
  useCaseDeadlineBoard: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("@/lib/hooks/use-case-deadline-board", () => ({
  useCaseDeadlineBoard: (...args: unknown[]) => mocks.useCaseDeadlineBoard(...args),
}));

const board: DeadlineBoardResponse = {
  case_id: 116,
  available: true,
  today: "2026-07-16",
  thresholds: { red_days: 15, yellow_days: 45 },
  counts: { expired: 1, red: 0, yellow: 0, safe: 0, unknown: 0, total: 1 },
  groups: {
    expired: [
      {
        type: "申请执行期限",
        due_date: "2026-07-13",
        remaining_days: -3,
        related_asset: "执行裁定",
        action: "立即核查中止、中断事由",
        level: "expired",
      },
    ],
    red: [],
    yellow: [],
    safe: [],
    unknown: [],
  },
};

describe("DeadlineBoard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.useCaseDeadlineBoard.mockReturnValue({
      board,
      isLoading: false,
      error: null,
      refresh: mocks.refresh,
    });
  });

  it("renders thresholds and grouped deadline actions", async () => {
    const { DeadlineBoard } = await import("@/components/cases/deadline-board");
    render(<DeadlineBoard caseId={116} />);

    expect(screen.getByText(/红色阈值 15 天/)).toBeTruthy();
    expect(screen.getByText("申请执行期限")).toBeTruthy();
    expect(screen.getByText("已逾期 3 天")).toBeTruthy();
    expect(screen.getByText(/立即核查中止、中断事由/)).toBeTruthy();
  });

  it("shows the backend unavailable state without treating it as an error", async () => {
    mocks.useCaseDeadlineBoard.mockReturnValue({
      board: { ...board, available: false },
      isLoading: false,
      error: null,
      refresh: mocks.refresh,
    });
    const { DeadlineBoard } = await import("@/components/cases/deadline-board");
    render(<DeadlineBoard caseId={116} />);

    expect(screen.getByText("时效扫描暂不可用")).toBeTruthy();
  });

  it("tolerates the unstructured fields being omitted by the backend", async () => {
    mocks.useCaseDeadlineBoard.mockReturnValue({
      board: { case_id: 116, available: true, today: "2026-07-16" },
      isLoading: false,
      error: null,
      refresh: mocks.refresh,
    });
    const { DeadlineBoard } = await import("@/components/cases/deadline-board");
    render(<DeadlineBoard caseId={116} />);

    expect(screen.getByText("暂无时效事项")).toBeTruthy();
    expect(screen.getByText(/红色阈值 - 天/)).toBeTruthy();
  });

  it("ignores malformed values allowed by the generic object schema", async () => {
    mocks.useCaseDeadlineBoard.mockReturnValue({
      board: {
        case_id: 116,
        available: true,
        today: "2026-07-16",
        thresholds: { red_days: {} },
        counts: { total: "many" },
        groups: { expired: "not-an-array", red: [{ type: { bad: true } }] },
      },
      isLoading: false,
      error: null,
      refresh: mocks.refresh,
    });
    const { DeadlineBoard } = await import("@/components/cases/deadline-board");
    render(<DeadlineBoard caseId={116} />);

    expect(screen.getByText("未命名时效事项")).toBeTruthy();
    expect(screen.getByText("剩余天数未知")).toBeTruthy();
  });

  it("offers retry when the request fails", async () => {
    mocks.useCaseDeadlineBoard.mockReturnValue({
      board: null,
      isLoading: false,
      error: "连接失败",
      refresh: mocks.refresh,
    });
    const { DeadlineBoard } = await import("@/components/cases/deadline-board");
    render(<DeadlineBoard caseId={116} />);

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(mocks.refresh).toHaveBeenCalledOnce();
  });
});

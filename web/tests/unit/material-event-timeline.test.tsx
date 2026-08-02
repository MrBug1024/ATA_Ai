// @vitest-environment jsdom
import { beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { CaseMaterialEventItem } from "@/lib/types/doc-categories";

const mocks = vi.hoisted(() => ({
  retry: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/hooks/use-retry-upload-batch", () => ({
  useRetryUploadBatch: () => ({
    data: null,
    isMutating: false,
    error: null,
    retry: mocks.retry,
    reset: vi.fn(),
  }),
}));

vi.mock("sonner", () => ({
  toast: {
    success: mocks.toastSuccess,
    error: mocks.toastError,
  },
}));

const mockEvent: CaseMaterialEventItem = {
  material_event_id: "m1",
  case_id: 116,
  debtor_id: 1,
  upload_batch_id: "b1",
  event_type: "supplement_upload",
  status: "completed",
  batch_name: "第一批材料",
  doc_category: "章程",
  operator_id: "u1",
  operator_name: "张操作员",
  file_count: 3,
  records_inserted: 120,
  event_payload: {},
  stage: "completed",
  has_conclusion_changes: true,
  reconciliation_item_count: 2,
  add_item_count: 1,
  override_item_count: 1,
  change_summary: "新增1条结论",
  error_message: "",
  started_at: "2026-06-01T10:00:00Z",
  completed_at: "2026-06-01T10:05:00Z",
  failed_at: null,
  created_at: "2026-06-01T09:55:00Z",
  updated_at: "2026-06-01T10:05:00Z",
};

describe("MaterialEventTimeline", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.retry.mockResolvedValue({ accepted: true });
  });

  it("renders event batch name", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    render(<MaterialEventTimeline events={[mockEvent]} isLoading={false} />);
    expect(screen.getByText("第一批材料")).toBeTruthy();
  });

  it("shows conclusion-change badge when has_conclusion_changes is true", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    render(<MaterialEventTimeline events={[mockEvent]} isLoading={false} />);
    expect(screen.getByText(/结论变化/)).toBeTruthy();
  });

  it("shows empty state when no events", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    render(<MaterialEventTimeline events={[]} isLoading={false} />);
    expect(screen.getByText(/暂无材料事件/)).toBeTruthy();
  });

  it("shows loading state", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    render(<MaterialEventTimeline events={[]} isLoading={true} />);
    expect(screen.getByText(/加载中/)).toBeTruthy();
  });

  it("shows error message when status is failed", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    const failedEvent: CaseMaterialEventItem = { ...mockEvent, status: "failed", error_message: "OCR超时" };
    render(<MaterialEventTimeline events={[failedEvent]} isLoading={false} />);
    fireEvent.click(screen.getByRole("button", { name: "查看错误" }));
    expect(screen.getByText("OCR超时")).toBeTruthy();
  });

  it("only offers retry for failed events and refreshes after acceptance", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    const onRetried = vi.fn();
    const failedEvent: CaseMaterialEventItem = {
      ...mockEvent,
      status: "failed",
      error_message: "OCR超时",
    };

    const { rerender } = render(
      <MaterialEventTimeline events={[mockEvent]} isLoading={false} onRetried={onRetried} />
    );
    expect(screen.queryByRole("button", { name: /重试批次/ })).toBeNull();

    rerender(
      <MaterialEventTimeline events={[failedEvent]} isLoading={false} onRetried={onRetried} />
    );
    fireEvent.click(screen.getByRole("button", { name: "重试批次 第一批材料" }));

    await waitFor(() => expect(mocks.retry).toHaveBeenCalledWith("auto"));
    expect(onRetried).toHaveBeenCalledOnce();
    expect(mocks.toastSuccess).toHaveBeenCalledWith("失败批次已重新提交");
    expect(
      (screen.getByRole("button", { name: "重试批次 第一批材料" }) as HTMLButtonElement)
        .disabled
    ).toBe(true);
    expect(screen.getByText("已提交")).toBeTruthy();
  });
});

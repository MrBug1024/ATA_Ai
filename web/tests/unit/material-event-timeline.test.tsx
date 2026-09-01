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
  entity_id: 1,
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
    expect(screen.getByText(/暂无资料处理记录/)).toBeTruthy();
  });

  it("shows the load error instead of a false empty state", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    render(
      <MaterialEventTimeline events={[]} isLoading={false} error="后端暂时不可用" />
    );
    expect(screen.getByText("资料处理记录加载失败")).toBeTruthy();
    expect(screen.getByText("后端暂时不可用")).toBeTruthy();
    expect(screen.queryByText(/暂无资料处理记录/)).toBeNull();
  });

  it("shows the persisted parse summary", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    render(
      <MaterialEventTimeline
        events={[
          {
            ...mockEvent,
            event_payload: { parse_summary: "本地完整读取 296 个工作表" },
          },
        ]}
        isLoading={false}
      />
    );
    expect(screen.getByText("本地完整读取 296 个工作表")).toBeTruthy();
  });

  it("labels preserved raw material as pending manual review without a retry action", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    render(
      <MaterialEventTimeline
        events={[
          {
            ...mockEvent,
            status: "completed",
            stage: "raw_preserved_pending_review",
            event_payload: { structured_projection: "not_attempted" },
          },
        ]}
        isLoading={false}
      />
    );

    expect(screen.getByText("原件已保全，待复核")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /重试批次/ })).toBeNull();
  });

  it("labels repaired duplicate projections without presenting them as zero-record imports", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    render(
      <MaterialEventTimeline
        events={[
          {
            ...mockEvent,
            material_event_id: "top-level-repair",
            records_inserted: 0,
            event_payload: { duplicate_projection_repaired: true },
          },
          {
            ...mockEvent,
            material_event_id: "nested-repair",
            records_inserted: 0,
            event_payload: {
              structured_import: { duplicate_projection_removed: true },
            },
          },
        ]}
        isLoading={false}
      />
    );

    expect(screen.getAllByText("已去重，未重复写入")).toHaveLength(2);
    expect(screen.getAllByText(/已去重，未重复写入结构化记录/)).toHaveLength(2);
    expect(screen.queryByText("0 条结构化记录")).toBeNull();
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

  it("failed status overrides an in-progress stage label", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    const failedEvent: CaseMaterialEventItem = {
      ...mockEvent,
      status: "failed",
      stage: "ocr_running",
      error_message: "OCR超时",
    };
    render(<MaterialEventTimeline events={[failedEvent]} isLoading={false} />);
    expect(screen.getByText("失败")).toBeTruthy();
    expect(screen.queryByText("OCR进行中")).toBeNull();
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

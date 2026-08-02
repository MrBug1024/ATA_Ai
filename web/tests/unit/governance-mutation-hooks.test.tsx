// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  mutate: vi.fn(),
  createCorrection: vi.fn(),
  revokeCorrection: vi.fn(),
  retryUploadBatch: vi.fn(),
}));

vi.mock("swr", () => ({ mutate: mocks.mutate }));
vi.mock("@/lib/backend/langgraph", () => ({
  caseCorrectionsKey: (caseId: number, history = false) =>
    `/cases/${caseId}/corrections${history ? "?include_history=true" : ""}`,
  materialEventKey: (id: string) => `/files/material-events/${id}`,
  uploadBatchKey: (id: string) => `/files/upload-batches/${id}`,
  createCorrection: mocks.createCorrection,
  revokeCorrection: mocks.revokeCorrection,
  retryUploadBatch: mocks.retryUploadBatch,
}));

describe("governance mutation hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.mutate.mockRejectedValue(new Error("revalidate failed"));
  });

  it("创建订正成功后不因缓存刷新失败而反转结果", async () => {
    const correction = { id: 1, status: "active" };
    mocks.createCorrection.mockResolvedValue(correction);
    const { useCreateCorrection } = await import("@/lib/hooks/use-create-correction");
    const { result } = renderHook(() => useCreateCorrection(116));

    await act(async () => {
      await expect(
        result.current.create({ target: "估值", instruction: "采用新报告" })
      ).resolves.toBe(correction);
    });
    expect(result.current.error).toBeNull();
  });

  it("撤销订正成功后不因缓存刷新失败而反转结果", async () => {
    const correction = { id: 1, status: "revoked" };
    mocks.revokeCorrection.mockResolvedValue(correction);
    const { useRevokeCorrection } = await import("@/lib/hooks/use-revoke-correction");
    const { result } = renderHook(() => useRevokeCorrection(116));

    await act(async () => {
      await expect(result.current.revoke(1)).resolves.toBe(correction);
    });
    expect(result.current.error).toBeNull();
  });

  it("批次重试受理后不因详情刷新失败而反转结果", async () => {
    const accepted = { accepted: true, material_event_id: "event-1" };
    mocks.retryUploadBatch.mockResolvedValue(accepted);
    const { useRetryUploadBatch } = await import("@/lib/hooks/use-retry-upload-batch");
    const { result } = renderHook(() => useRetryUploadBatch("batch-1"));

    await act(async () => {
      await expect(result.current.retry("auto")).resolves.toBe(accepted);
    });
    expect(result.current.error).toBeNull();
  });
});

// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  review: vi.fn(),
  reset: vi.fn(),
}));

vi.mock("@/lib/hooks/use-case-review", () => ({
  useCaseReview: () => ({
    data: null,
    isMutating: false,
    error: null,
    review: mocks.review,
    reset: mocks.reset,
  }),
}));

describe("ReviewDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.review.mockResolvedValue({ final_report: "复盘完成" });
  });

  it("省略 thread_id，让后端使用案件复盘独立线程", async () => {
    const { ReviewDialog } = await import("@/components/cases/review-dialog");
    render(<ReviewDialog caseId={116} />);

    fireEvent.click(screen.getByRole("button", { name: "AI 复盘" }));

    await waitFor(() =>
      expect(mocks.review).toHaveBeenCalledWith({})
    );
  });
});

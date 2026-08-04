// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  categories: [] as Array<{
    code: string;
    name: string;
    uploaded: boolean;
    file_count: number;
    record_count: number;
    last_uploaded_at: string | null;
  }>,
}));

vi.mock("@/lib/hooks/use-case-material-events", () => ({
  useCaseMaterialEvents: () => ({ events: [], isLoading: false }),
}));

vi.mock("@/lib/hooks/use-case-doc-categories", () => ({
  useCaseDocCategories: () => ({
    caseDocCategories: {
      case_id: 2,
      categories: mocks.categories,
      missing_categories: mocks.categories.filter((category) => !category.uploaded).map((category) => category.code),
    },
    isLoading: false,
  }),
}));

describe("CaseUploadStatus", () => {
  beforeEach(() => {
    mocks.categories = Array.from({ length: 10 }, (_, index) => ({
      code: `category-${index}`,
      name: `资料 ${index}`,
      uploaded: index < 3,
      file_count: index < 3 ? 1 : 0,
      record_count: 0,
      last_uploaded_at: null,
    }));
  });

  it("shows category coverage instead of treating a successful upload as completeness", async () => {
    const { CaseUploadStatus } = await import("@/components/cases/case-upload-status");
    render(<CaseUploadStatus caseId={2} />);

    const badge = screen.getByText("已有 3/10 类");
    expect(badge.getAttribute("title")).toContain("仍缺 7 类");
  });
});

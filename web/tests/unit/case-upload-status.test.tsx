// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  events: [] as Array<Record<string, unknown>>,
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
  useCaseMaterialEvents: () => ({ events: mocks.events, isLoading: false }),
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
    mocks.events = [];
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

  it("does not let a historical failed event override current usable category coverage", async () => {
    mocks.categories = mocks.categories.map((category) => ({
      ...category,
      uploaded: false,
      coverage_status: "ready",
    }));
    mocks.events = [
      {
        status: "failed",
        doc_category: "category-0",
        stage: "parse_document",
      },
    ];

    const { CaseUploadStatus } = await import("@/components/cases/case-upload-status");
    render(<CaseUploadStatus caseId={2} />);

    expect(screen.getByText("完整 10/10 类")).toBeTruthy();
    expect(screen.queryByText("上传失败")).toBeNull();
  });

  it("keeps a failed event visible when its category has no usable evidence", async () => {
    mocks.events = [
      {
        status: "failed",
        doc_category: "category-9",
        stage: "parse_document",
      },
    ];

    const { CaseUploadStatus } = await import("@/components/cases/case-upload-status");
    render(<CaseUploadStatus caseId={2} />);

    expect(screen.getByText("上传失败")).toBeTruthy();
  });

  it("prioritizes raw-only material that is pending manual review", async () => {
    mocks.categories = Array.from({ length: 10 }, (_, index) => ({
      code: `category-${index}`,
      name: `资料 ${index}`,
      uploaded: true,
      file_count: 1,
      record_count: 0,
      last_uploaded_at: null,
    }));
    mocks.events = [
      {
        status: "completed",
        stage: "raw_preserved_pending_review",
        event_payload: { stage: "raw_preserved_pending_review" },
      },
    ];

    const { CaseUploadStatus } = await import("@/components/cases/case-upload-status");
    render(<CaseUploadStatus caseId={2} />);

    expect(screen.getByText("待人工复核")).toBeTruthy();
    expect(screen.queryByText("完整 10/10 类")).toBeNull();
  });
});

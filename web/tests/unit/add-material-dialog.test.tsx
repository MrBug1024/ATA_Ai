// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

const mocks = vi.hoisted(() => ({
  validate: vi.fn(),
  upload: vi.fn(),
  retryUploadBatch: vi.fn(),
  addTask: vi.fn(),
  updateTask: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  refreshCategories: vi.fn(),
  refreshCaseDocCategories: vi.fn(),
  categories: [
    {
      code: "contract",
      name: "合同",
      description: "合同资料",
      sort_order: 1,
      enabled: true,
      fields: [],
    },
  ],
  categoriesError: undefined as Error | undefined,
  caseDocCategories: { case_id: 8, categories: [], missing_categories: ["contract"] },
  caseDocCategoriesError: undefined as Error | undefined,
  retryBatchId: "",
  selectOnValueChange: null as ((value: string) => void) | null,
  materialEvent: {
    material_event_id: "event-1",
    case_id: 8,
    entity_id: 1,
    upload_batch_id: "",
    event_type: "supplement_upload",
    status: "failed",
    batch_name: "合同资料",
    doc_category: "contract",
    operator_id: "auditor",
    operator_name: "审计员",
    file_count: 1,
    records_inserted: 0,
    event_payload: {},
    stage: "ocr_running",
    has_conclusion_changes: false,
    reconciliation_item_count: 0,
    add_item_count: 0,
    override_item_count: 0,
    change_summary: "",
    error_message: "OCR 处理失败",
    started_at: null,
    completed_at: null,
    failed_at: null,
    created_at: "2026-09-03T00:00:00Z",
    updated_at: "2026-09-03T00:00:00Z",
  },
}));

vi.mock("sonner", () => ({
  toast: {
    success: mocks.toastSuccess,
    error: mocks.toastError,
    warning: vi.fn(),
  },
}));

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ children }: { children: ReactNode }) => <>{children}</>,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
  DialogFooter: ({ children }: { children: ReactNode }) => <footer>{children}</footer>,
}));

vi.mock("@/components/ui/select", () => ({
  Select: ({ children, onValueChange }: { children: ReactNode; onValueChange: (value: string) => void }) => {
    mocks.selectOnValueChange = onValueChange;
    return <div>{children}</div>;
  },
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectGroup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children, value }: { children: ReactNode; value: string }) => (
    <button type="button" onClick={() => mocks.selectOnValueChange?.(value)}>{children}</button>
  ),
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: ({ placeholder }: { placeholder?: string }) => <span>{placeholder}</span>,
}));

vi.mock("@/lib/hooks/use-doc-categories", () => ({
  useDocCategories: () => ({
    categories: mocks.categories,
    isLoading: false,
    error: mocks.categoriesError,
    refresh: mocks.refreshCategories,
  }),
}));

vi.mock("@/lib/hooks/use-case-doc-categories", () => ({
  useCaseDocCategories: () => ({
    caseDocCategories: mocks.caseDocCategories,
    isLoading: false,
    error: mocks.caseDocCategoriesError,
    refresh: mocks.refreshCaseDocCategories,
  }),
}));

vi.mock("@/lib/hooks/use-validate-doc-category", () => ({
  useValidateDocCategory: () => ({ validate: mocks.validate }),
}));

vi.mock("@/lib/hooks/use-upload-ingest", () => ({
  useUploadIngest: () => ({ upload: mocks.upload }),
}));

vi.mock("@/lib/hooks/use-material-event", () => ({
  useMaterialEvent: () => ({ event: mocks.materialEvent }),
}));

vi.mock("@/lib/hooks/use-retry-upload-batch", () => ({
  useRetryUploadBatch: (batchId: string) => {
    mocks.retryBatchId = batchId;
    return {
      retry: mocks.retryUploadBatch,
      isMutating: false,
      error: null,
    };
  },
}));

vi.mock("@/lib/stores/upload-queue", () => ({
  useUploadQueue: (selector: (state: { addTask: typeof mocks.addTask; updateTask: typeof mocks.updateTask }) => unknown) =>
    selector({ addTask: mocks.addTask, updateTask: mocks.updateTask }),
}));

describe("AddMaterialDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.selectOnValueChange = null;
    mocks.retryBatchId = "";
    mocks.categories = [
      {
        code: "contract",
        name: "合同",
        description: "合同资料",
        sort_order: 1,
        enabled: true,
        fields: [],
      },
    ];
    mocks.categoriesError = undefined;
    mocks.caseDocCategories = { case_id: 8, categories: [], missing_categories: ["contract"] };
    mocks.caseDocCategoriesError = undefined;
    mocks.addTask.mockReturnValue("task-1");
    mocks.validate.mockResolvedValue({
      ok: true,
      suspected_mismatch: false,
      suspected_duplicate: false,
      message: "校验通过",
    });
    mocks.upload.mockResolvedValue({ material_event_id: "event-1" });
    mocks.retryUploadBatch.mockResolvedValue({
      accepted: true,
      material_event_id: "event-1",
    });
  });

  it("处理失败后重试已持久化批次，不重复校验或上传文件", async () => {
    const { AddMaterialDialog } = await import("@/components/cases/add-material-dialog");
    render(
      <AddMaterialDialog
        open
        onOpenChange={vi.fn()}
        caseItem={{
          case_id: 8,
          case_name: "年度审计",
          case_type: "annual_audit",
          entity_name: "测试公司",
          status: "active",
        }}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "合同" }));
    fireEvent.change(screen.getByLabelText("选择年审资料文件"), {
      target: { files: [new File(["contract"], "contract.pdf", { type: "application/pdf" })] },
    });

    await waitFor(() => expect(mocks.validate).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "确认上传" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "重试处理" })).toBeTruthy());
    const uploadedBatchId = mocks.upload.mock.calls[0]?.[0]?.upload_batch_id;
    expect(uploadedBatchId).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "重试处理" }));

    await waitFor(() => expect(mocks.retryUploadBatch).toHaveBeenCalledWith("auto"));
    expect(mocks.retryBatchId).toBe(uploadedBatchId);
    expect(mocks.validate).toHaveBeenCalledTimes(1);
    expect(mocks.upload).toHaveBeenCalledTimes(1);
    expect(mocks.updateTask).toHaveBeenCalledWith(
      "task-1",
      expect.objectContaining({ status: "processing", materialEventId: "event-1" })
    );
  });

  it("资料目录不可用时不把它展示成正常的零类别状态", async () => {
    mocks.categories = [];
    mocks.categoriesError = new Error("目录请求失败");
    const { AddMaterialDialog } = await import("@/components/cases/add-material-dialog");
    render(
      <AddMaterialDialog
        open
        onOpenChange={vi.fn()}
        caseItem={{
          case_id: 8,
          case_name: "年度审计",
          case_type: "annual_audit",
          entity_name: "测试公司",
          status: "active",
        }}
      />
    );

    expect(screen.getByText("资料目录暂不可用")).toBeTruthy();
    expect(screen.queryByText(/已有 0 类/)).toBeNull();
    expect(
      (screen.getByRole("button", { name: "确认上传" }) as HTMLButtonElement).disabled
    ).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    expect(mocks.refreshCategories).toHaveBeenCalledTimes(1);
    expect(mocks.refreshCaseDocCategories).toHaveBeenCalledTimes(1);
  });
});

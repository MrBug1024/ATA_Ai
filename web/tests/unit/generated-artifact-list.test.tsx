// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PreviewContext, type PreviewableFile } from "@/lib/assistant-ui/preview-context";
import { GeneratedArtifactList } from "@/components/chat/generated-artifact-list";

const mocks = vi.hoisted(() => ({
  getPreviewTicket: vi.fn(),
  getDownloadTicket: vi.fn(),
  openPreview: vi.fn(),
  retryJob: vi.fn(),
  cancelJob: vi.fn(),
  useJob: vi.fn(),
  refreshJob: vi.fn(),
  apiFetch: vi.fn(),
  getAuthorizationHeader: vi.fn(),
  createObjectURL: vi.fn(),
  revokeObjectURL: vi.fn(),
}));

vi.mock("@/lib/api/client", () => ({ apiFetch: mocks.apiFetch }));
vi.mock("@/lib/auth/token-store", () => ({
  getAuthorizationHeader: mocks.getAuthorizationHeader,
}));

vi.mock("@/lib/backend/generated-artifacts", async () => {
  const actual = await vi.importActual<typeof import("@/lib/backend/generated-artifacts")>(
    "@/lib/backend/generated-artifacts"
  );
  return {
    ...actual,
    getArtifactPreviewTicket: mocks.getPreviewTicket,
    getArtifactDownloadTicket: mocks.getDownloadTicket,
  };
});

const JOB_REF = {
  job_id: "job-1",
  case_id: 42,
  assistant_turn_id: "turn-1-assistant",
  report_id: 88,
  report_version: 3,
  template_version_id: "template-v1",
  template_version_label: "v1",
  delivery_level: "review_draft",
} as const;

const JOB = {
  ...JOB_REF,
  status: "succeeded" as const,
  stage: "succeeded",
  progress: { percent: 100, completed: 2, total: 2, failed: 0 },
  expected_item_count: 2,
  succeeded_item_count: 2,
  items: [],
  retryable: true,
  artifacts: [
    {
      id: "approved-artifact",
      document_code: "audit_report",
      display_name: "审计报告",
      file_name: "测试项目审计报告.docx",
      extension: "docx",
      content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      file_size: 1024,
      sha256: "a".repeat(64),
      status: "published",
      delivery_approved: true,
      preview_available: true,
      quality_status: "passed",
    },
    {
      id: "rejected-artifact",
      document_code: "financial_statements",
      display_name: "财务报表",
      file_name: "测试项目财务报表.xlsx",
      extension: "xlsx",
      content_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      file_size: 2048,
      sha256: "b".repeat(64),
      status: "rejected",
      delivery_approved: false,
      preview_available: false,
      quality_status: "failed",
      quality_summary: "勾稽校验未通过",
    },
  ],
};

vi.mock("@/lib/hooks/use-attachment-job", () => ({
  useAttachmentJob: () => mocks.useJob(),
  useRetryAttachmentJob: () => ({ retryJob: mocks.retryJob, isMutating: false }),
  useCancelAttachmentJob: () => ({ cancelJob: mocks.cancelJob, isMutating: false }),
}));

function setup(attachmentJob: unknown = JOB_REF) {
  let previewFile: PreviewableFile | null = null;
  render(
    <PreviewContext.Provider
      value={{
        previewFile,
        openPreview: (file) => { previewFile = file; mocks.openPreview(file); },
        closePreview: () => { previewFile = null; },
      }}
    >
      <GeneratedArtifactList attachmentJob={attachmentJob} />
    </PreviewContext.Provider>
  );
}

describe("GeneratedArtifactList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getPreviewTicket.mockResolvedValue({
      url: "https://objects.test/preview-ticket",
      expires_at: "2026-08-31T12:00:00Z",
      content_type: "application/pdf",
      file_name: "测试项目审计报告预览.pdf",
    });
    mocks.getDownloadTicket.mockResolvedValue({
      url: "https://objects.test/download-ticket",
      expires_at: "2026-08-31T12:00:00Z",
      content_type: JOB.artifacts[0].content_type,
      file_name: JOB.artifacts[0].file_name,
    });
    mocks.useJob.mockReturnValue({
      job: JOB,
      error: null,
      isLoading: false,
      isValidating: false,
      refresh: mocks.refreshJob,
    });
    mocks.getAuthorizationHeader.mockReturnValue("Bearer access-1");
    mocks.apiFetch.mockResolvedValue(new Response("document-bytes", { status: 200 }));
    mocks.createObjectURL.mockReturnValue("blob:download-1");
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: mocks.createObjectURL,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: mocks.revokeObjectURL,
    });
  });

  it("renders nothing for incomplete or unbound metadata", () => {
    setup({ job_id: "job-only" });
    expect(screen.queryByTestId("generated-artifact-list")).toBeNull();
  });

  it("shows only approved artifact actions and explains rejected delivery", () => {
    setup();
    expect(screen.getByText("报告 v3 · 模板 v1 · 任务 job-1")).toBeTruthy();
    expect(screen.getByText("勾稽校验未通过")).toBeTruthy();
    expect(screen.getByText("已生成，等待复核")).toBeTruthy();
    expect(screen.getByText("成功 2/2 个附件")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "预览" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "下载" })).toHaveLength(1);
  });

  it("gets a purpose-specific preview ticket and never treats it as a download", async () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "预览" }));
    await waitFor(() => expect(mocks.getPreviewTicket).toHaveBeenCalledWith(42, "approved-artifact"));
    expect(mocks.openPreview).toHaveBeenCalledWith(expect.objectContaining({
      previewUrl: "https://objects.test/preview-ticket",
      previewUrlIsDownload: false,
      contentType: "application/pdf",
      requestHeaders: { Authorization: "Bearer access-1" },
    }));
    expect(mocks.getDownloadTicket).not.toHaveBeenCalled();
  });

  it("downloads an authenticated blob and revokes its temporary URL", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    setup();
    fireEvent.click(screen.getByRole("button", { name: "下载" }));
    await waitFor(() => expect(mocks.getDownloadTicket).toHaveBeenCalledWith(42, "approved-artifact"));
    expect(mocks.apiFetch).toHaveBeenCalledWith(
      "https://objects.test/download-ticket",
      undefined,
      { auth: true }
    );
    expect(mocks.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledOnce();
    expect(mocks.revokeObjectURL).toHaveBeenCalledWith("blob:download-1");
    click.mockRestore();
  });

  it("shows a neutral loading state without exposing a cancel action", () => {
    mocks.useJob.mockReturnValue({
      job: null,
      error: null,
      isLoading: true,
      isValidating: true,
      refresh: mocks.refreshJob,
    });
    setup();
    expect(screen.getByText("加载状态")).toBeTruthy();
    expect(screen.getByText("正在加载附件任务状态…")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "取消" })).toBeNull();
  });

  it("shows an error state and lets the user refresh it", async () => {
    mocks.refreshJob.mockResolvedValue(undefined);
    mocks.useJob.mockReturnValue({
      job: null,
      error: "任务状态已过期",
      isLoading: false,
      isValidating: false,
      refresh: mocks.refreshJob,
    });
    setup();
    expect(screen.getByText("状态不可用")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "取消" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "刷新状态" }));
    await waitFor(() => expect(mocks.refreshJob).toHaveBeenCalledOnce());
  });

  it("retries failed items on the same immutable job without a client key", async () => {
    mocks.retryJob.mockResolvedValue(JOB);
    setup();
    fireEvent.click(screen.getByRole("button", { name: "重新生成" }));
    await waitFor(() => expect(mocks.retryJob).toHaveBeenCalledWith(undefined));
  });
});

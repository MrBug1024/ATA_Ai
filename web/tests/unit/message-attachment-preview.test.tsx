// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MessageAttachmentItem } from "@/components/assistant-ui/attachment";
import { PreviewProvider, PreviewSidePanel } from "@/components/shared/preview-host";
import { seedPreviewUrls, resetAttachmentStore } from "@/lib/assistant-ui/attachment-store";

vi.mock("@/components/shared/pdf-page-view", () => ({
  PdfPageView: () => <div data-testid="pdf-page-view" />,
}));

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

beforeEach(() => {
  mockFetch.mockReset();
  resetAttachmentStore();
});

function setup(attachment: Parameters<typeof MessageAttachmentItem>[0]["attachment"]) {
  return render(
    <PreviewProvider>
      <MessageAttachmentItem attachment={attachment} />
      <PreviewSidePanel />
    </PreviewProvider>
  );
}

describe("消息附件点击预览(端到端接线)", () => {
  it("PDF 附件:点击后用 store 缓存的 URL 在面板中渲染 PDF", () => {
    seedPreviewUrls([{ id: "att-1", url: "http://x/report.pdf" }]);
    setup({ id: "att-1", name: "报告.pdf", contentType: "application/pdf" });

    fireEvent.click(screen.getByLabelText("预览文件: 报告.pdf"));
    expect(screen.getByTestId("file-preview-panel")).toBeTruthy();
    expect(screen.getByTestId("pdf-page-view")).toBeTruthy();
  });

  it("文本附件:点击后面板拉取并展示文本内容", async () => {
    mockFetch.mockResolvedValue({ text: async () => "第一行流水" });
    seedPreviewUrls([{ id: "att-2", url: "http://x/data.csv" }]);
    setup({ id: "att-2", name: "data.csv", contentType: "application/octet-stream" });

    fireEvent.click(screen.getByLabelText("预览文件: data.csv"));
    expect(await screen.findByText("第一行流水")).toBeTruthy();
  });

  it("无缓存 URL 的 Office 附件:面板显示降级文案", () => {
    setup({ id: "att-3", name: "合同.docx" });

    fireEvent.click(screen.getByLabelText("预览文件: 合同.docx"));
    expect(screen.getByText("不支持预览此格式")).toBeTruthy();
  });
});

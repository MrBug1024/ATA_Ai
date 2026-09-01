// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { act } from "react";
import { PreviewProvider, PreviewSidePanel } from "@/components/shared/preview-host";
import { usePreview, type PreviewableFile } from "@/lib/assistant-ui/preview-context";
import { useEvidenceDrawerStore } from "@/lib/stores/evidence-drawer";

vi.mock("@/components/shared/pdf-page-view", () => ({
  PdfPageView: (props: { width?: number; height?: number; httpHeaders?: Record<string, string> }) => (
    <div
      data-testid="pdf-page-view"
      data-width={props.width ?? ""}
      data-height={props.height ?? ""}
      data-authorization={props.httpHeaders?.Authorization ?? ""}
    />
  ),
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
  act(() => useEvidenceDrawerStore.getState().closeDrawer());
});

function Trigger({ file }: { file: PreviewableFile }) {
  const { openPreview } = usePreview();
  return (
    <button type="button" onClick={() => openPreview(file)}>
      open
    </button>
  );
}

function setup(file: PreviewableFile) {
  return render(
    <PreviewProvider>
      <Trigger file={file} />
      <PreviewSidePanel />
    </PreviewProvider>
  );
}

describe("PreviewProvider + PreviewSidePanel", () => {
  it("初始不渲染面板;openPreview 后渲染,关闭按钮收起", async () => {
    mockFetch.mockResolvedValue({ text: async () => "hello world" });
    setup({ name: "notes.txt", contentType: "text/plain", previewUrl: "http://x/notes.txt" });

    expect(screen.queryByTestId("file-preview-panel")).toBeNull();

    fireEvent.click(screen.getByText("open"));
    expect(screen.getByTestId("file-preview-panel")).toBeTruthy();
    expect(screen.getByText("notes.txt")).toBeTruthy();
    await waitFor(() => expect(screen.getByText("hello world")).toBeTruthy());

    fireEvent.click(screen.getByLabelText("关闭预览"));
    expect(screen.queryByTestId("file-preview-panel")).toBeNull();
  });

  it("PDF 文件走 PdfPageView 渲染", () => {
    setup({
      name: "报告.pdf",
      contentType: "application/pdf",
      previewUrl: "http://x/r.pdf",
      requestHeaders: { Authorization: "Bearer access-1" },
    });
    fireEvent.click(screen.getByText("open"));
    expect(screen.getByTestId("pdf-page-view").getAttribute("data-authorization")).toBe(
      "Bearer access-1"
    );
  });

  it("文本预览请求会透传认证头", async () => {
    mockFetch.mockResolvedValue({ text: async () => "protected text" });
    setup({
      name: "notes.txt",
      contentType: "text/plain",
      previewUrl: "http://x/notes.txt",
      requestHeaders: { Authorization: "Bearer access-1" },
    });
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByText("protected text")).toBeTruthy());
    expect(mockFetch).toHaveBeenCalledWith(
      "http://x/notes.txt",
      expect.objectContaining({ headers: { Authorization: "Bearer access-1" } })
    );
  });

  it("图片文件渲染 <img>", () => {
    setup({ name: "证据.png", contentType: "image/png", previewUrl: "http://x/p.png" });
    fireEvent.click(screen.getByText("open"));
    const img = screen.getByAltText("证据.png") as HTMLImageElement;
    expect(img.src).toBe("http://x/p.png");
  });

  it("缺 previewUrl 的文本文件显示「暂无预览」而非永久加载", () => {
    setup({ name: "notes.txt", contentType: "text/plain" });
    fireEvent.click(screen.getByText("open"));
    expect(screen.getByText("暂无预览")).toBeTruthy();
  });

  it("不支持的格式显示降级文案与下载链接", () => {
    setup({ name: "合同.docx", previewUrl: "http://x/c.docx" });
    fireEvent.click(screen.getByText("open"));
    expect(screen.getByText("不支持预览此格式")).toBeTruthy();
    expect(screen.getByText("下载文件")).toBeTruthy();
  });
});

describe("放大查看(lightbox)", () => {
  it("图片:点击面板内图片打开大图弹层,关闭后收起", () => {
    setup({ name: "证据.png", contentType: "image/png", previewUrl: "http://x/p.png" });
    fireEvent.click(screen.getByText("open"));

    fireEvent.click(screen.getByLabelText("放大查看: 证据.png"));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeTruthy();
    expect(screen.getByAltText("证据.png 大图")).toBeTruthy();

    fireEvent.click(screen.getByText("Close"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("PDF:点击面板内页面打开放大弹层(弹层内重新渲染 PDF)", () => {
    setup({ name: "报告.pdf", contentType: "application/pdf", previewUrl: "http://x/r.pdf" });
    fireEvent.click(screen.getByText("open"));
    expect(screen.getAllByTestId("pdf-page-view")).toHaveLength(1);

    fireEvent.click(screen.getByLabelText("放大查看 PDF"));
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getAllByTestId("pdf-page-view")).toHaveLength(2);
  });

  it("全屏弹层默认整图可见(object-contain 限高)", () => {
    setup({ name: "证据.png", contentType: "image/png", previewUrl: "http://x/p.png" });
    fireEvent.click(screen.getByText("open"));
    fireEvent.click(screen.getByLabelText("放大查看: 证据.png"));

    const big = screen.getByAltText("证据.png 大图");
    expect(big.className).toContain("object-contain");
    expect(big.className).toContain("max-h-full");
  });

  it("全屏弹层 PDF 默认整页适配(按高度渲染,不按宽度)", () => {
    setup({ name: "报告.pdf", contentType: "application/pdf", previewUrl: "http://x/r.pdf" });
    fireEvent.click(screen.getByText("open"));
    fireEvent.click(screen.getByLabelText("放大查看 PDF"));

    const views = screen.getAllByTestId("pdf-page-view");
    const lightboxView = views[1];
    expect(lightboxView.getAttribute("data-height")).not.toBe("");
    expect(lightboxView.getAttribute("data-width")).toBe("");
    // 面板内仍按宽度渲染
    expect(views[0].getAttribute("data-width")).not.toBe("");
  });

  it("文本文件不提供放大入口", () => {
    mockFetch.mockResolvedValue({ text: async () => "hello" });
    setup({ name: "notes.txt", contentType: "text/plain", previewUrl: "http://x/n.txt" });
    fireEvent.click(screen.getByText("open"));
    expect(screen.queryByLabelText(/放大查看/)).toBeNull();
  });
});

describe("与证据抽屉互斥(右侧单抽屉位)", () => {
  it("预览打开时,打开证据抽屉(点角标)→ 预览自动关闭", () => {
    mockFetch.mockResolvedValue({ text: async () => "hello" });
    setup({ name: "notes.txt", contentType: "text/plain", previewUrl: "http://x/n.txt" });
    fireEvent.click(screen.getByText("open"));
    expect(screen.getByTestId("file-preview-panel")).toBeTruthy();

    act(() =>
      useEvidenceDrawerStore.getState().openDrawer({ caseId: 1, reportRef: "r", citationId: "1" })
    );
    expect(screen.queryByTestId("file-preview-panel")).toBeNull();
    expect(useEvidenceDrawerStore.getState().open).toBe(true);
  });

  it("证据抽屉打开时,点附件预览 → 抽屉关闭、预览打开", () => {
    mockFetch.mockResolvedValue({ text: async () => "hello" });
    setup({ name: "notes.txt", contentType: "text/plain", previewUrl: "http://x/n.txt" });
    act(() =>
      useEvidenceDrawerStore.getState().openDrawer({ caseId: 1, reportRef: "r", citationId: "1" })
    );

    fireEvent.click(screen.getByText("open"));
    expect(useEvidenceDrawerStore.getState().open).toBe(false);
    expect(screen.getByTestId("file-preview-panel")).toBeTruthy();
  });
});

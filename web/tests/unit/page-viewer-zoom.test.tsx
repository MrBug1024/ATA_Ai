// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { PageViewer } from "@/components/knowledge-graph/page-viewer";
import type { EvidenceItem, PageAnchorsResponse } from "@/lib/types/knowledge-graph";

vi.mock("@/lib/hooks/use-page-anchors", () => ({
  usePageAnchors: () => ({ data: null, isLoading: false, error: null }),
}));

vi.mock("@/components/shared/pdf-page-view", () => ({
  PdfPageView: (props: { width?: number; height?: number; pageNumber: number }) => (
    <div
      data-testid="pdf-page-view"
      data-width={props.width ?? ""}
      data-height={props.height ?? ""}
      data-page={props.pageNumber}
    />
  ),
}));

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

function imagePage(): PageAnchorsResponse {
  return {
    file_id: 1,
    page_no: 2,
    page_width: 800,
    page_height: 1100,
    page_image_ref: "ref",
    anchors: [],
    file_name: "凭证.png",
    source_file_url: "http://x/p2.png",
    content_type: "image/png",
  };
}

describe("PageViewer 全屏查看", () => {
  it("点击页面图片打开全屏弹层,弹层内再渲染一份页面", () => {
    render(<PageViewer initialPage={imagePage()} selectedEvidence={null} />);

    expect(screen.getAllByAltText("凭证.png 第 2 页")).toHaveLength(1);
    fireEvent.click(screen.getByLabelText("全屏查看页面"));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeTruthy();
    expect(screen.getAllByAltText("凭证.png 第 2 页")).toHaveLength(2);
    expect(within(dialog).getByText("凭证.png — 第 2 页")).toBeTruthy();
  });

  it("无可预览文件时不提供全屏入口", () => {
    render(
      <PageViewer
        initialPage={{ ...imagePage(), source_file_url: undefined, content_type: "text/plain" }}
        selectedEvidence={null}
      />
    );
    expect(screen.queryByLabelText("全屏查看页面")).toBeNull();
  });
});

function pdfPrimaryPage(): PageAnchorsResponse {
  return {
    file_id: 9,
    page_no: 1,
    page_width: 800,
    page_height: 1100,
    page_image_ref: "",
    anchors: [],
    file_name: "二债会资料.pdf",
    source_file_url: "http://x/f.pdf",
    content_type: "application/pdf",
  };
}

function pdfEvidence(pageNo: number): EvidenceItem {
  return {
    chunk_id: `c-${pageNo}`,
    file_id: 9,
    file_name: "二债会资料.pdf",
    page_no: pageNo,
    quote_text: "地点:六盘水市钟山大道时代假日酒店",
    bbox_list: [],
    page_image_ref: "",
    source_page_id: 0,
    source_file_url: "http://x/f.pdf",
    content_type: "application/pdf",
  };
}

describe("多证据选中时按证据所在页渲染", () => {
  it("选中第 2 页的证据时,PDF 渲染第 2 页而非首屏页", async () => {
    render(<PageViewer initialPage={pdfPrimaryPage()} selectedEvidence={pdfEvidence(2)} />);

    const view = await screen.findByTestId("pdf-page-view");
    expect(view.getAttribute("data-page")).toBe("2");
    expect(screen.getByText("二债会资料.pdf — 第 2 页")).toBeTruthy();
  });

  it("未选中证据时仍渲染首屏页", async () => {
    render(<PageViewer initialPage={pdfPrimaryPage()} selectedEvidence={null} />);

    const view = await screen.findByTestId("pdf-page-view");
    expect(view.getAttribute("data-page")).toBe("1");
  });
});

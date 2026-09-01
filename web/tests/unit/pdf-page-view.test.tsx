// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PdfPageView } from "@/components/shared/pdf-page-view";

const mocks = vi.hoisted(() => ({ documentProps: vi.fn() }));

vi.mock("react-pdf", () => ({
  pdfjs: { GlobalWorkerOptions: {} },
  Document: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => {
    mocks.documentProps(props);
    return <div>{children}</div>;
  },
  Page: () => <div data-testid="pdf-page" />,
}));

vi.mock("@/components/knowledge-graph/bbox-overlay", () => ({
  BboxOverlay: () => null,
}));

describe("PdfPageView", () => {
  it("passes authorization headers to PDF.js document options", () => {
    render(
      <PdfPageView
        url="https://annual-api.test/artifact-access/ticket"
        pageNumber={1}
        httpHeaders={{ Authorization: "Bearer access-1" }}
      />
    );

    expect(mocks.documentProps).toHaveBeenLastCalledWith(expect.objectContaining({
      file: "https://annual-api.test/artifact-access/ticket",
      options: { httpHeaders: { Authorization: "Bearer access-1" } },
    }));
  });
});

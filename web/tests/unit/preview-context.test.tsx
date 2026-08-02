// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { createElement, useState, useCallback, type ReactNode } from "react";
import { PreviewContext, usePreview, type PreviewableFile } from "@/lib/assistant-ui/preview-context";
import { ThinkingContext } from "@/lib/assistant-ui/thinking-context";
import { useContext } from "react";

describe("PreviewContext", () => {
  it("默认值：previewFile null + 默认 no-op 函数可调用", () => {
    const { result } = renderHook(() => usePreview());
    expect(result.current.previewFile).toBeNull();
    expect(() => result.current.openPreview({ name: "x" })).not.toThrow();
    expect(() => result.current.closePreview()).not.toThrow();
  });

  it("Provider 注入的实现可以打开/关闭", () => {
    function Wrapper({ children }: { children: ReactNode }) {
      const [file, setFile] = useState<PreviewableFile | null>(null);
      const openPreview = useCallback((f: PreviewableFile) => setFile(f), []);
      const closePreview = useCallback(() => setFile(null), []);
      return createElement(
        PreviewContext.Provider,
        { value: { previewFile: file, openPreview, closePreview } },
        children
      );
    }
    const { result } = renderHook(() => usePreview(), { wrapper: Wrapper });
    expect(result.current.previewFile).toBeNull();

    const file: PreviewableFile = { name: "doc.pdf", contentType: "application/pdf" };
    act(() => result.current.openPreview(file));
    expect(result.current.previewFile?.name).toBe("doc.pdf");

    act(() => result.current.closePreview());
    expect(result.current.previewFile).toBeNull();
  });
});

describe("ThinkingContext", () => {
  it("默认值是空 Map", () => {
    const { result } = renderHook(() => useContext(ThinkingContext));
    expect(result.current).toBeInstanceOf(Map);
    expect(result.current.size).toBe(0);
  });
});

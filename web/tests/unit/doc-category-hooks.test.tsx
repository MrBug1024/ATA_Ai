// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { SWRConfig } from "swr";
import { useDocCategories } from "@/lib/hooks/use-doc-categories";
import { useCaseDocCategories } from "@/lib/hooks/use-case-doc-categories";
import { useCaseMaterialEvents } from "@/lib/hooks/use-case-material-events";
import { useMaterialEvent } from "@/lib/hooks/use-material-event";

function jsonRes(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function freshSwr({ children }: { children: ReactNode }) {
  return createElement(
    SWRConfig,
    { value: { provider: () => new Map(), dedupingInterval: 0 } },
    children
  );
}

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("useDocCategories", () => {
  it("加载分类列表", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes({ categories: [{ name: "a" }, { name: "b" }] }));
    const { result } = renderHook(() => useDocCategories(), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.categories).toHaveLength(2);
  });

  it("缺省 categories 时返回空数组", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes({}));
    const { result } = renderHook(() => useDocCategories(), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.categories).toEqual([]);
  });

  it("非 2xx → error", async () => {
    fetchMock.mockResolvedValueOnce(new Response("x", { status: 500 }));
    const { result } = renderHook(() => useDocCategories(), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.error).toBeDefined());
  });
});

describe("useCaseDocCategories", () => {
  it("caseId 为 null 时不请求", async () => {
    const { result } = renderHook(() => useCaseDocCategories(null), { wrapper: freshSwr });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.caseDocCategories).toBeUndefined();
  });

  it("caseId 非 null 时请求对应路径", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes({ case_id: 7, categories: [] }));
    const { result } = renderHook(() => useCaseDocCategories(7), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.caseDocCategories).toBeDefined());
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://localhost:8080/api/case/7/doc-categories"
    );
  });
});

describe("useCaseMaterialEvents", () => {
  it("caseId 为 null 时返回空事件", () => {
    const { result } = renderHook(() => useCaseMaterialEvents(null), { wrapper: freshSwr });
    expect(result.current.events).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("取 material_events 字段", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes({ material_events: [{ id: "e1" }] }));
    const { result } = renderHook(() => useCaseMaterialEvents(3), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.events).toHaveLength(1));
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://localhost:8080/files/cases/3/material-events"
    );
  });

  it("非 2xx → error 字符串", async () => {
    fetchMock.mockResolvedValueOnce(new Response("x", { status: 500 }));
    const { result } = renderHook(() => useCaseMaterialEvents(3), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(typeof result.current.error).toBe("string");
  });
});

describe("useMaterialEvent", () => {
  it("eventId 为 null 时返回 null", () => {
    const { result } = renderHook(() => useMaterialEvent(null), { wrapper: freshSwr });
    expect(result.current.event).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("对 eventId 做 URL 编码", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes({ id: "ev/1", status: "completed" }));
    const { result } = renderHook(() => useMaterialEvent("ev/1"), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.event).not.toBeNull());
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://localhost:8080/files/material-events/ev%2F1"
    );
  });

  it("非 2xx → error 字符串", async () => {
    fetchMock.mockResolvedValueOnce(new Response("x", { status: 404 }));
    const { result } = renderHook(() => useMaterialEvent("e1"), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.error).toBeTruthy());
  });
});

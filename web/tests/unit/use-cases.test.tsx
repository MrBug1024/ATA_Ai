// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { SWRConfig } from "swr";
import { useCases } from "@/lib/hooks/use-cases";

function jsonRes(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

function freshSwr({ children }: { children: ReactNode }) {
  return createElement(
    SWRConfig,
    { value: { provider: () => new Map(), dedupingInterval: 0 } },
    children
  );
}

function casesPage(page: number, items: Array<{ case_id: number; case_name?: string }>) {
  return {
    cases: items.map((i) => ({ case_name: "C", case_type: "T", status: "open", ...i })),
    total: 100,
    page,
    page_size: 20,
  };
}

describe("useCases", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("初次加载第一页", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes(casesPage(1, [{ case_id: 1 }, { case_id: 2 }])));
    const { result } = renderHook(() => useCases(), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.cases.map((c) => c.case_id)).toEqual([1, 2]);
    expect(result.current.total).toBe(100);
  });

  it("setPage 第二页累加（去重）", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes(casesPage(1, [{ case_id: 1 }, { case_id: 2 }])));
    fetchMock.mockResolvedValueOnce(jsonRes(casesPage(2, [{ case_id: 2 }, { case_id: 3 }])));
    const { result } = renderHook(() => useCases(), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.cases.length).toBe(2));
    act(() => result.current.setPage(2));
    await waitFor(() => expect(result.current.cases.length).toBe(3));
    expect(result.current.cases.map((c) => c.case_id)).toEqual([1, 2, 3]);
  });

  it("setKeyword 重置到第 1 页 + 清空", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes(casesPage(1, [{ case_id: 1 }])));
    fetchMock.mockResolvedValueOnce(jsonRes(casesPage(1, [{ case_id: 5 }])));
    const { result } = renderHook(() => useCases(), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.cases.length).toBe(1));
    act(() => result.current.setKeyword("foo"));
    await waitFor(() => expect(result.current.page).toBe(1));
    await waitFor(() => expect(result.current.cases[0]?.case_id).toBe(5));
    // 调用的 url 含 keyword=foo
    const lastUrl = fetchMock.mock.calls.at(-1)?.[0] as string;
    expect(lastUrl).toContain("keyword=foo");
  });

  it("setKeyword 同值时 no-op", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes(casesPage(1, [{ case_id: 1 }])));
    const { result } = renderHook(() => useCases(), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.cases.length).toBe(1));
    const callsBefore = fetchMock.mock.calls.length;
    act(() => result.current.setKeyword(""));
    expect(fetchMock.mock.calls.length).toBe(callsBefore);
  });

  it("setPage(1) 清空 cases", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes(casesPage(1, [{ case_id: 1 }])));
    fetchMock.mockResolvedValueOnce(jsonRes(casesPage(2, [{ case_id: 2 }])));
    fetchMock.mockResolvedValueOnce(jsonRes(casesPage(1, [{ case_id: 9 }])));
    const { result } = renderHook(() => useCases(), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.cases.length).toBe(1));
    act(() => result.current.setPage(2));
    await waitFor(() => expect(result.current.cases.length).toBe(2));
    act(() => result.current.setPage(1));
    await waitFor(() => expect(result.current.cases.map((c) => c.case_id)).toEqual([9]));
  });

  it("retry/refresh 触发 mutate", async () => {
    fetchMock.mockResolvedValue(jsonRes(casesPage(1, [{ case_id: 1 }])));
    const { result } = renderHook(() => useCases(), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.cases.length).toBe(1));
    const callsBefore = fetchMock.mock.calls.length;
    await act(async () => {
      result.current.retry();
    });
    await act(async () => {
      result.current.refresh();
    });
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
  });

  it("响应非 2xx → fetcher 抛错传给 SWR error", async () => {
    fetchMock.mockResolvedValueOnce(new Response("nope", { status: 500 }));
    const { result } = renderHook(() => useCases(), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.error).toBeDefined());
    expect((result.current.error as Error).message).toContain("500");
  });
});

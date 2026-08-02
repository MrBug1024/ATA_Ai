// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { SWRConfig } from "swr";
import { useConversations } from "@/lib/hooks/use-conversations";

vi.mock("@/lib/auth/token-store", () => ({
  getAuthorizationHeader: () => null,
  clearAuthSession: vi.fn(),
}));

function jsonRes(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), { status: 200, ...init });
}

function freshSwr({ children }: { children: ReactNode }) {
  return createElement(SWRConfig, { value: { provider: () => new Map(), dedupingInterval: 0 } }, children);
}

const threadFixture = {
  thread_id: "t1",
  title: "X",
  checkpoint_id: "ck",
  case_id: 0,
  debtor_id: 0,
  debtor_name: "",
  last_query: "",
  last_intent: "",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("useConversations", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("加载 LangGraph threads 列表", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonRes({ threads: [threadFixture], total: 1, limit: 50, offset: 0 })
    );
    const { result } = renderHook(() => useConversations(), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.conversations).toHaveLength(1);
    expect(result.current.conversations[0].thread_id).toBe("t1");
    expect(result.current.total).toBe(1);
    expect(result.current.limit).toBe(50);
    expect(result.current.offset).toBe(0);
  });

  it("响应缺 threads 字段 → 空数组", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes({ total: 0, limit: 50, offset: 0 }));
    const { result } = renderHook(() => useConversations(), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.conversations).toEqual([]);
  });

  it("禁用时不请求会话列表", async () => {
    const { result } = renderHook(() => useConversations({}, false), {
      wrapper: freshSwr,
    });
    expect(result.current.conversations).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refresh 触发 mutate", async () => {
    fetchMock.mockResolvedValue(jsonRes({ threads: [], total: 0, limit: 50, offset: 0 }));
    const { result } = renderHook(() => useConversations(), { wrapper: freshSwr });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const callsBefore = fetchMock.mock.calls.length;
    await act(async () => {
      await result.current.refresh();
    });
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
  });
});

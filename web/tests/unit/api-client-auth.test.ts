// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, UnauthorizedError } from "@/lib/api/client";

const tokenMocks = vi.hoisted(() => ({
  getAuthorizationHeader: vi.fn(),
  clearAuthSession: vi.fn(),
}));

vi.mock("@/lib/auth/token-store", () => tokenMocks);

describe("apiFetch auth", () => {
  const fetchMock = vi.fn();
  let originalLocation: Location;

  beforeEach(() => {
    fetchMock.mockReset();
    tokenMocks.getAuthorizationHeader.mockReset().mockReturnValue("bearer access-1");
    tokenMocks.clearAuthSession.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("NEXT_PUBLIC_LANGGRAPH_API_BASE_URL", "http://langgraph.test");
    originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: "", pathname: "/cases", search: "?page=2" },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("只给 LangGraph 请求附加 bearer", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));

    await apiFetch("http://langgraph.test/chat/threads");
    await apiFetch("http://cases.test/api/cases");

    const langgraphHeaders = new Headers(fetchMock.mock.calls[0][1]?.headers);
    const casesHeaders = new Headers(fetchMock.mock.calls[1][1]?.headers);
    expect(langgraphHeaders.get("Authorization")).toBe("bearer access-1");
    expect(casesHeaders.has("Authorization")).toBe(false);
  });

  it("统一后端下案件接口也附加 bearer", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://unified.test");
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));

    await apiFetch("http://unified.test/api/cases");

    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.get("Authorization")).toBe("bearer access-1");
  });

  it("LangGraph 401 清理 token 并携带 from 跳转", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 401 }));

    await expect(apiFetch("http://langgraph.test/me")).rejects.toBeInstanceOf(
      UnauthorizedError
    );

    expect(tokenMocks.clearAuthSession).toHaveBeenCalledOnce();
    expect(window.location.href).toBe("/login?from=%2Fcases%3Fpage%3D2");
  });

  it("认证接口可以自行检查 401", async () => {
    fetchMock.mockResolvedValue(new Response('{"detail":"bad credentials"}', { status: 401 }));

    const response = await apiFetch(
      "http://langgraph.test/auth/login",
      { method: "POST" },
      { auth: false, handleUnauthorized: false }
    );

    expect(response.status).toBe(401);
    expect(tokenMocks.clearAuthSession).not.toHaveBeenCalled();
    expect(window.location.href).toBe("");
  });
});

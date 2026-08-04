// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, UnauthorizedError } from "@/lib/api/client";

const tokenMocks = vi.hoisted(() => ({
  getAuthorizationHeader: vi.fn(),
  clearAuthSession: vi.fn(),
}));

vi.mock("@/lib/auth/token-store", () => tokenMocks);

describe("unified annual-audit API authentication", () => {
  const fetchMock = vi.fn();
  let originalLocation: Location;

  beforeEach(() => {
    fetchMock.mockReset();
    tokenMocks.getAuthorizationHeader.mockReset().mockReturnValue("bearer access-1");
    tokenMocks.clearAuthSession.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://annual-api.test");
    originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: "", pathname: "/audits", search: "?page=2" },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  });

  it("attaches bearer credentials to every unified API route", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    await apiFetch("http://annual-api.test/chat/threads");
    await apiFetch("http://annual-api.test/api/cases");
    for (const call of fetchMock.mock.calls) {
      const headers = new Headers(call[1]?.headers);
      expect(headers.get("Authorization")).toBe("bearer access-1");
    }
  });

  it("does not send the platform token to another origin", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    await apiFetch("http://external.test/reference");
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.has("Authorization")).toBe(false);
  });

  it("clears the session and redirects after an authenticated 401", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 401 }));
    await expect(apiFetch("http://annual-api.test/me")).rejects.toBeInstanceOf(
      UnauthorizedError
    );
    expect(tokenMocks.clearAuthSession).toHaveBeenCalledOnce();
    expect(window.location.href).toBe("/login?from=%2Faudits%3Fpage%3D2");
  });

  it("lets the login operation inspect its own 401 response", async () => {
    fetchMock.mockResolvedValue(new Response('{"detail":"bad credentials"}', { status: 401 }));
    const response = await apiFetch(
      "http://annual-api.test/auth/login",
      { method: "POST" },
      { auth: false, handleUnauthorized: false }
    );
    expect(response.status).toBe(401);
    expect(tokenMocks.clearAuthSession).not.toHaveBeenCalled();
  });
});

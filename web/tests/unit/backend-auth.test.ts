import { beforeEach, describe, expect, it, vi } from "vitest";
import { BackendError } from "@/lib/backend/http";
import { changePassword, getMe, login, logout } from "@/lib/backend/auth";

const apiFetchMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api/client", () => ({
  apiFetch: apiFetchMock,
  langgraphUrl: (path: string) => `http://langgraph.test${path}`,
}));

describe("backend auth contract", () => {
  beforeEach(() => apiFetchMock.mockReset());

  it("使用 login_identifier 登录且不附加旧 token", async () => {
    apiFetchMock.mockResolvedValue(
      Response.json({
        access_token: "token",
        expires_at: "2099-01-01T00:00:00Z",
        user_id: "u1",
        username: "alice",
        company_id: "c1",
      })
    );

    await login({ login_identifier: "alice", password: "secret" });

    expect(apiFetchMock).toHaveBeenCalledWith(
      "http://langgraph.test/auth/login",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ login_identifier: "alice", password: "secret" }),
      }),
      { auth: false, handleUnauthorized: false }
    );
  });

  it("/me、logout 和 password/change 使用认证请求", async () => {
    apiFetchMock.mockResolvedValue(Response.json({ authenticated: true }));

    await getMe();
    await logout();
    await changePassword({ old_password: "old", new_password: "new" });

    expect(apiFetchMock.mock.calls[0][0]).toBe("http://langgraph.test/me");
    expect(apiFetchMock.mock.calls[0][2]).toEqual({ auth: true, handleUnauthorized: false });
    expect(apiFetchMock.mock.calls[1][1]).toEqual({ method: "POST" });
    expect(apiFetchMock.mock.calls[2][1].body).toBe(
      JSON.stringify({ old_password: "old", new_password: "new" })
    );
  });

  it("保留后端 detail 错误和状态码", async () => {
    apiFetchMock.mockResolvedValue(
      Response.json({ detail: "用户名或密码错误" }, { status: 401 })
    );

    await expect(login({ login_identifier: "alice", password: "bad" })).rejects.toEqual(
      new BackendError("用户名或密码错误", 401)
    );
  });
});

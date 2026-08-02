// @vitest-environment jsdom
import type { PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BackendError } from "@/lib/backend/http";
import { AuthProvider, useAuth } from "@/lib/hooks/use-auth";

const mocks = vi.hoisted(() => ({
  getMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  changePassword: vi.fn(),
  storeAuthSession: vi.fn(),
  clearAuthSession: vi.fn(),
  getAuthSession: vi.fn(),
  getAuthorizationHeader: vi.fn(),
}));

vi.mock("@/lib/backend/auth", () => ({
  getMe: mocks.getMe,
  login: mocks.login,
  logout: mocks.logout,
  changePassword: mocks.changePassword,
}));

vi.mock("@/lib/auth/token-store", () => ({
  AUTH_SESSION_STORAGE_KEY: "ai-hunter.auth-session",
  storeAuthSession: mocks.storeAuthSession,
  clearAuthSession: mocks.clearAuthSession,
  getAuthSession: mocks.getAuthSession,
  getAuthorizationHeader: mocks.getAuthorizationHeader,
}));

const USER = {
  user_id: "u1",
  username: "alice",
  company_id: "c1",
  authenticated: true,
};

const LOGIN_RESPONSE = {
  access_token: "token-1",
  token_type: "bearer",
  expires_at: "2099-01-01T00:00:00Z",
  user_id: "u1",
  username: "alice",
  company_id: "c1",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function wrapper({ children }: PropsWithChildren) {
  return <AuthProvider>{children}</AuthProvider>;
}

describe("AuthProvider", () => {
  let originalLocation: Location;

  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
    mocks.getAuthSession.mockReturnValue(null);
    originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: "", pathname: "/login", search: "" },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("把 /me 的 200 system 身份视为可访问", async () => {
    mocks.getMe.mockResolvedValue({
      user_id: "__system__",
      username: "system",
      authenticated: false,
    });

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.user?.username).toBe("system");
  });

  it("/me 返回 401 时清理 token 并保持未登录", async () => {
    mocks.getMe.mockRejectedValue(new BackendError("Unauthorized", 401));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.isAuthenticated).toBe(false);
    expect(mocks.clearAuthSession).toHaveBeenCalledOnce();
  });

  it("登录后保存 bearer、刷新 /me 并跳回站内来源页", async () => {
    mocks.getMe
      .mockRejectedValueOnce(new BackendError("Unauthorized", 401))
      .mockResolvedValueOnce(USER);
    mocks.login.mockResolvedValue(LOGIN_RESPONSE);
    window.location.search = "?from=%2Fcases%3Fpage%3D2";

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.login("alice", "secret");
    });

    expect(mocks.login).toHaveBeenCalledWith({
      login_identifier: "alice",
      password: "secret",
    });
    expect(mocks.storeAuthSession).toHaveBeenCalledWith({
      accessToken: "token-1",
      tokenType: "bearer",
      expiresAt: "2099-01-01T00:00:00Z",
      userId: "u1",
      username: "alice",
      companyId: "c1",
    });
    expect(window.location.href).toBe("/cases?page=2");
  });

  it("拒绝协议相对的外部回跳地址", async () => {
    mocks.getMe
      .mockRejectedValueOnce(new BackendError("Unauthorized", 401))
      .mockResolvedValueOnce(USER);
    mocks.login.mockResolvedValue(LOGIN_RESPONSE);
    window.location.search = "?from=%2F%2Fevil.example";

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    await act(async () => {
      await result.current.login("alice", "secret");
    });

    expect(window.location.href).toBe("/chat");
  });

  it("后端登出失败时仍完成本地登出", async () => {
    mocks.getMe.mockResolvedValue(USER);
    mocks.logout.mockRejectedValue(new Error("network"));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    await act(async () => {
      await result.current.logout();
    });

    expect(mocks.clearAuthSession).toHaveBeenCalledOnce();
    expect(result.current.isAuthenticated).toBe(false);
    expect(window.location.href).toBe("/login");
  });

  it("按新接口字段提交密码修改", async () => {
    mocks.getMe.mockResolvedValue(USER);
    mocks.changePassword.mockResolvedValue(undefined);

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    await act(async () => {
      await result.current.changePassword("old", "new");
    });

    expect(mocks.changePassword).toHaveBeenCalledWith({
      old_password: "old",
      new_password: "new",
    });
  });

  it("改密返回 401 时立即清理会话并跳转登录", async () => {
    mocks.getMe.mockResolvedValue(USER);
    mocks.changePassword.mockRejectedValue(new BackendError("Unauthorized", 401));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    await act(async () => {
      await expect(result.current.changePassword("old", "new")).rejects.toThrow(
        "Unauthorized"
      );
    });

    expect(mocks.clearAuthSession).toHaveBeenCalledOnce();
    expect(result.current.isAuthenticated).toBe(false);
    expect(window.location.href).toBe("/login");
  });

  it("其他标签页清理 session 时同步退出当前身份", async () => {
    mocks.getMe.mockResolvedValue(USER);

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "ai-hunter.auth-session",
          oldValue: JSON.stringify(LOGIN_RESPONSE),
          newValue: null,
        })
      );
    });

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
  });

  it("其他标签页写入新 session 时重新获取当前身份", async () => {
    const nextUser = { ...USER, user_id: "u2", username: "bob" };
    mocks.getMe.mockResolvedValueOnce(USER).mockResolvedValueOnce(nextUser);
    mocks.getAuthSession.mockReturnValue(LOGIN_RESPONSE);

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.user?.user_id).toBe("u1"));

    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "ai-hunter.auth-session",
          newValue: JSON.stringify(LOGIN_RESPONSE),
        })
      );
    });

    await waitFor(() => expect(result.current.user?.user_id).toBe("u2"));
  });

  it("并发 refresh 只允许最后一次请求更新身份", async () => {
    mocks.getMe.mockResolvedValueOnce(USER);
    const stale = deferred<typeof USER>();
    const latest = deferred<typeof USER>();

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.user?.user_id).toBe("u1"));
    mocks.getMe
      .mockImplementationOnce(() => stale.promise)
      .mockImplementationOnce(() => latest.promise);

    let staleRefresh!: Promise<void>;
    let latestRefresh!: Promise<void>;
    act(() => {
      staleRefresh = result.current.refresh();
      latestRefresh = result.current.refresh();
    });

    await act(async () => {
      latest.resolve({ ...USER, user_id: "latest", username: "latest" });
      await latestRefresh;
    });
    await act(async () => {
      stale.resolve({ ...USER, user_id: "stale", username: "stale" });
      await staleRefresh;
    });

    expect(result.current.user?.user_id).toBe("latest");
  });
});

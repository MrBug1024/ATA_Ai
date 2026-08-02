// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthGuard } from "@/components/auth/auth-guard";

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  replace: vi.fn(),
  pathname: "/cases",
}));

vi.mock("@/lib/hooks/use-auth", () => ({ useAuth: mocks.useAuth }));
vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ replace: mocks.replace }),
}));

describe("AuthGuard", () => {
  beforeEach(() => {
    mocks.useAuth.mockReset();
    mocks.replace.mockReset();
    mocks.pathname = "/cases";
    window.history.replaceState({}, "", "/cases?page=2");
  });

  it("检查期间不渲染受保护内容", () => {
    mocks.useAuth.mockReturnValue({ isLoading: true, isAuthenticated: false });

    render(
      <AuthGuard>
        <div>private content</div>
      </AuthGuard>
    );

    expect(screen.queryByText("private content")).toBeNull();
  });

  it("未登录访问受保护页时携带来源跳转", async () => {
    mocks.useAuth.mockReturnValue({ isLoading: false, isAuthenticated: false });

    render(
      <AuthGuard>
        <div>private content</div>
      </AuthGuard>
    );

    await waitFor(() => {
      expect(mocks.replace).toHaveBeenCalledWith("/login?from=%2Fcases%3Fpage%3D2");
    });
    expect(screen.queryByText("private content")).toBeNull();
  });

  it("已登录访问登录页时转到聊天页", async () => {
    mocks.pathname = "/login";
    mocks.useAuth.mockReturnValue({ isLoading: false, isAuthenticated: true });

    render(
      <AuthGuard>
        <div>login form</div>
      </AuthGuard>
    );

    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/chat"));
    expect(screen.queryByText("login form")).toBeNull();
  });

  it("已登录时渲染受保护内容", () => {
    mocks.useAuth.mockReturnValue({ isLoading: false, isAuthenticated: true });

    render(
      <AuthGuard>
        <div>private content</div>
      </AuthGuard>
    );

    expect(screen.getByText("private content")).not.toBeNull();
    expect(mocks.replace).not.toHaveBeenCalled();
  });
});

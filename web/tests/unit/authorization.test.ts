import { describe, expect, it } from "vitest";
import {
  canAccessAdmin,
  canAccessModule,
  canManageCompanies,
  isSystemAdminPreview,
} from "@/lib/auth/authorization";

describe("administrator authorization", () => {
  it("allows an authenticated super administrator", () => {
    const user = { authenticated: true, is_super_admin: true };

    expect(canAccessAdmin(user)).toBe(true);
    expect(canManageCompanies(user)).toBe(true);
  });

  it("temporarily denies company administrators", () => {
    const user = { authenticated: true, is_company_admin: true };

    expect(canAccessAdmin(user)).toBe(false);
    expect(canManageCompanies(user)).toBe(false);
  });

  it("allows only the explicit system administrator preview identity", () => {
    const previewUser = {
      user_id: "__system__",
      authenticated: false,
      is_super_admin: true,
      allowed_modules: ["chat", "admin"],
    };

    expect(isSystemAdminPreview(previewUser)).toBe(true);
    expect(canAccessAdmin(previewUser)).toBe(true);
    expect(canManageCompanies(previewUser)).toBe(true);
  });

  it.each([
    {
      user_id: "__system__",
      authenticated: false,
      is_super_admin: true,
      allowed_modules: ["chat"],
    },
    {
      user_id: "someone-else",
      authenticated: false,
      is_super_admin: true,
      allowed_modules: ["admin"],
    },
    {
      user_id: "__system__",
      authenticated: false,
      is_super_admin: false,
      allowed_modules: ["admin"],
    },
  ])("denies incomplete preview markers", (user) => {
    expect(isSystemAdminPreview(user)).toBe(false);
    expect(canAccessAdmin(user)).toBe(false);
  });

  it("denies missing users and ordinary authenticated users", () => {
    expect(canAccessAdmin(null)).toBe(false);
    expect(canAccessAdmin({ authenticated: true })).toBe(false);
  });

  it("按 /me allowed_modules 控制功能模块", () => {
    const user = {
      authenticated: true,
      allowed_modules: ["graph", "review"],
    };

    expect(canAccessModule(user, "graph")).toBe(true);
    expect(canAccessModule(user, "review")).toBe(true);
    expect(canAccessModule(user, "deadline")).toBe(false);
  });

  it("超级管理员可访问全部模块，预览身份仍受 allowed_modules 限制", () => {
    expect(
      canAccessModule({ authenticated: true, is_super_admin: true }, "deadline")
    ).toBe(true);
    expect(
      canAccessModule(
        {
          user_id: "__system__",
          authenticated: false,
          is_super_admin: true,
          allowed_modules: ["admin", "graph"],
        },
        "graph"
      )
    ).toBe(true);
    expect(
      canAccessModule(
        {
          user_id: "__system__",
          authenticated: false,
          is_super_admin: true,
          allowed_modules: ["admin", "graph"],
        },
        "review"
      )
    ).toBe(false);
  });
});

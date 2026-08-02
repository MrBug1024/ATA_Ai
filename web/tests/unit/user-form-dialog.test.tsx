// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AdminUserRecord } from "@/lib/backend/admin";

const mocks = vi.hoisted(() => ({
  createAdminUser: vi.fn(),
  updateAdminUser: vi.fn(),
  createReset: vi.fn(),
  updateReset: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));

vi.mock("@/lib/hooks/use-admin", () => ({
  useCreateAdminUser: () => ({
    createAdminUser: mocks.createAdminUser,
    isMutating: false,
    error: null,
    reset: mocks.createReset,
  }),
  useUpdateAdminUser: () => ({
    updateAdminUser: mocks.updateAdminUser,
    isMutating: false,
    error: null,
    reset: mocks.updateReset,
  }),
}));

const SUPER_ADMIN: AdminUserRecord = {
  user_id: "root-id",
  username: "Root User",
  company: "",
  company_id: "",
  region: "",
  note: "",
  auth_source: "local",
  status: "active",
  is_super_admin: true,
  last_login_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("UserFormDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.createAdminUser.mockResolvedValue({});
    mocks.updateAdminUser.mockResolvedValue({});
  });

  it("编辑时锁定认证来源、隐藏密码和超级管理员开关，并只提交资料字段", async () => {
    const { UserFormDialog } = await import("@/components/admin/user-form-dialog");
    const onOpenChange = vi.fn();
    render(
      <UserFormDialog
        open
        onOpenChange={onOpenChange}
        user={SUPER_ADMIN}
        companies={[]}
      />
    );

    const authSource = document.getElementById("admin-auth-source") as HTMLButtonElement;
    expect(authSource.disabled).toBe(true);
    expect(screen.queryByLabelText("初始密码")).toBeNull();
    expect(screen.queryByText("超级管理员")).toBeNull();

    fireEvent.change(screen.getByLabelText("显示名称"), {
      target: { value: "Updated Root" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存资料" }));

    await waitFor(() => expect(mocks.updateAdminUser).toHaveBeenCalledOnce());
    expect(mocks.updateAdminUser).toHaveBeenCalledWith({
      username: "Updated Root",
      company_id: "",
      company: "",
      status: "active",
      region: "",
      note: "",
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("新建普通用户时必须选择公司", async () => {
    const { UserFormDialog } = await import("@/components/admin/user-form-dialog");
    render(
      <UserFormDialog open onOpenChange={vi.fn()} user={null} companies={[]} />
    );
    expect(screen.getByLabelText("初始密码")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("用户 ID"), {
      target: { value: "new-user" },
    });
    fireEvent.change(screen.getByLabelText("显示名称"), {
      target: { value: "New User" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建用户" }));

    expect(await screen.findByText("普通用户必须归属一家公司")).toBeTruthy();
    expect(mocks.createAdminUser).not.toHaveBeenCalled();
  });

  it("初始密码不能等于用户 ID 或显示名称", async () => {
    const { passwordError } = await import("@/components/admin/user-form-dialog");

    expect(passwordError("User123456", "user123456", "Alice", true)).toBe(
      "密码不能与用户 ID 或显示名称相同"
    );
    expect(passwordError("Alice12345", "other", "alice12345", true)).toBe(
      "密码不能与用户 ID 或显示名称相同"
    );
  });
});

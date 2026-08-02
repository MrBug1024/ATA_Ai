// @vitest-environment jsdom
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AdminUserRecord } from "@/lib/backend/admin";

const mocks = vi.hoisted(() => ({
  roleData: null as null | { user_id: string; company_id: string; roles: string[] },
  roleError: null as string | null,
  tagData: null as null | {
    user_id: string;
    tags: {
      project_role: string[];
      title: string[];
      expertise: string[];
      company: string;
      region: string;
    };
  },
  tagError: null as string | null,
  saveRoles: vi.fn(),
  saveTags: vi.fn(),
  resetRoles: vi.fn(),
  resetTags: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));

vi.mock("@/components/ui/tabs", () => ({
  Tabs: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TabsList: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({ children }: { children: React.ReactNode }) => <button>{children}</button>,
  TabsContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/lib/hooks/use-admin", () => ({
  useAdminRoles: () => ({
    roles: {
      reviewer: {
        role_name: "复核员",
        tier: "expert",
        modules: [],
        visible_report_sections: [],
        description: "",
      },
    },
    isLoading: false,
    error: null,
  }),
  useTagCatalog: () => ({
    catalog: [
      {
        dimension: "expertise",
        tag_value: "合同",
        tag_group: "专业",
        sort_order: 1,
      },
    ],
    isLoading: false,
    error: null,
  }),
  useAdminUserRoles: () => ({
    data: mocks.roleData,
    isLoading: false,
    error: mocks.roleError,
  }),
  useAdminUserTags: () => ({
    data: mocks.tagData,
    isLoading: false,
    error: mocks.tagError,
  }),
  useSaveUserRoles: () => ({
    saveUserRoles: mocks.saveRoles,
    isMutating: false,
    error: null,
    reset: mocks.resetRoles,
  }),
  useSaveUserTags: () => ({
    saveUserTags: mocks.saveTags,
    isMutating: false,
    error: null,
    reset: mocks.resetTags,
  }),
}));

function user(userId: string): AdminUserRecord {
  return {
    user_id: userId,
    username: userId,
    company: "Acme",
    company_id: "c1",
    region: "",
    note: "",
    auth_source: "local",
    status: "active",
    is_super_admin: false,
    last_login_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("UserAccessDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.roleError = null;
    mocks.tagError = null;
    mocks.roleData = {
      user_id: "user-1",
      company_id: "c1",
      roles: ["reviewer"],
    };
    mocks.tagData = {
      user_id: "user-1",
      tags: {
        project_role: [],
        title: [],
        expertise: ["合同"],
        company: "Acme",
        region: "",
      },
    };
  });

  it("切换用户时清空旧选择，陈旧响应或错误状态下禁止保存", async () => {
    const { UserAccessDialog } = await import("@/components/admin/user-access-dialog");
    const { rerender } = render(
      <UserAccessDialog open onOpenChange={vi.fn()} user={user("user-1")} />
    );

    const roleCheckbox = await screen.findByRole("checkbox", { name: /复核员/ });
    const tagCheckbox = screen.getByRole("checkbox", { name: "合同" });
    await waitFor(() => expect(roleCheckbox.getAttribute("data-state")).toBe("checked"));
    expect(tagCheckbox.getAttribute("data-state")).toBe("checked");

    act(() => {
      mocks.roleError = "加载失败";
      mocks.tagError = "加载失败";
      rerender(
        <UserAccessDialog open onOpenChange={vi.fn()} user={user("user-2")} />
      );
    });

    await waitFor(() =>
      expect(roleCheckbox.getAttribute("data-state")).toBe("unchecked")
    );
    expect(tagCheckbox.getAttribute("data-state")).toBe("unchecked");
    expect((screen.getByRole("button", { name: "保存角色" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "保存专业领域" }) as HTMLButtonElement).disabled).toBe(true);
    expect(mocks.resetRoles).toHaveBeenCalledTimes(2);
    expect(mocks.resetTags).toHaveBeenCalledTimes(2);
    expect(mocks.saveRoles).not.toHaveBeenCalled();
    expect(mocks.saveTags).not.toHaveBeenCalled();
  });
});

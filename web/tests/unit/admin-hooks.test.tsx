// @vitest-environment jsdom
import type { PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  AdminUserRecord,
  CompanyRecord,
  UserListParams,
} from "@/lib/backend/admin";
import {
  useAdminCompanies,
  useAdminUserRoles,
  useAdminUserTags,
  useAdminUsers,
  useSaveCompany,
  useSaveUserRoles,
  useSaveUserTags,
  useUpdateAdminUser,
} from "@/lib/hooks/use-admin";

const mocks = vi.hoisted(() => ({
  listCompanies: vi.fn(),
  upsertCompany: vi.fn(),
  listUsers: vi.fn(),
  updateUser: vi.fn(),
  getUserRoles: vi.fn(),
  replaceUserRoles: vi.fn(),
  getUserTags: vi.fn(),
  replaceUserTags: vi.fn(),
  authRefresh: vi.fn(),
  currentUser: { user_id: "operator" } as { user_id: string } | null,
}));

vi.mock("@/lib/backend/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/backend/admin")>();
  return {
    ...actual,
    listCompanies: mocks.listCompanies,
    upsertCompany: mocks.upsertCompany,
    listUsers: mocks.listUsers,
    updateUser: mocks.updateUser,
    getUserRoles: mocks.getUserRoles,
    replaceUserRoles: mocks.replaceUserRoles,
    getUserTags: mocks.getUserTags,
    replaceUserTags: mocks.replaceUserTags,
  };
});

vi.mock("@/lib/hooks/use-auth", () => ({
  useAuth: () => ({ user: mocks.currentUser, refresh: mocks.authRefresh }),
}));

const COMPANY: CompanyRecord = {
  company_id: "co-1",
  company_name: "测试公司",
  company_name_norm: "测试公司",
  company_type: "customer",
  status: "active",
  notes: "",
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
};

const USER: AdminUserRecord = {
  user_id: "user-1",
  username: "alice",
  company: "测试公司",
  company_id: "co-1",
  region: "",
  note: "",
  auth_source: "local",
  status: "active",
  is_super_admin: false,
  last_login_at: null,
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
};

function freshSwr({ children }: PropsWithChildren) {
  return (
    <SWRConfig
      value={{
        provider: () => new Map(),
        dedupingInterval: 0,
        revalidateOnFocus: false,
        shouldRetryOnError: false,
      }}
    >
      {children}
    </SWRConfig>
  );
}

function countCalls<T extends unknown[]>(mock: { mock: { calls: T[] } }, expected: T): number {
  return mock.mock.calls.filter(
    (call) => JSON.stringify(call) === JSON.stringify(expected)
  ).length;
}

describe("admin hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.currentUser = { user_id: "operator" };
    mocks.authRefresh.mockResolvedValue(undefined);
    mocks.listCompanies.mockResolvedValue([COMPANY]);
    mocks.upsertCompany.mockResolvedValue(COMPANY);
    mocks.listUsers.mockImplementation(async (params: UserListParams = {}) => [
      {
        ...USER,
        status: params.status || "active",
      },
    ]);
    mocks.updateUser.mockResolvedValue(USER);
    mocks.getUserRoles.mockImplementation(
      async (userId: string, companyId?: string) => ({
        user_id: userId,
        company_id: companyId ?? "",
        roles: [],
      })
    );
    mocks.replaceUserRoles.mockImplementation(
      async (userId: string, request: { company_id: string; roles: string[] }) => ({
        user_id: userId,
        company_id: request.company_id,
        roles: request.roles,
      })
    );
    mocks.getUserTags.mockImplementation(async (userId: string) => ({
      user_id: userId,
      tags: {
        project_role: [],
        title: [],
        expertise: [],
        company: "测试公司",
        region: "",
      },
    }));
    mocks.replaceUserTags.mockImplementation(
      async (userId: string, request: { dimension: string; values: string[] }) => ({
        user_id: userId,
        ...request,
      })
    );
  });

  it("用户筛选参数变化时使用新 key 并返回对应列表", async () => {
    const { result, rerender } = renderHook(
      ({ params }: { params: UserListParams }) => useAdminUsers(params),
      {
        wrapper: freshSwr,
        initialProps: { params: { status: "active", limit: 20 } },
      }
    );

    await waitFor(() => expect(result.current.users[0]?.status).toBe("active"));
    expect(mocks.listUsers).toHaveBeenCalledWith({ status: "active", limit: 20 });

    rerender({ params: { companyId: "co-1", status: "disabled", limit: 10 } });

    await waitFor(() => expect(result.current.users[0]?.status).toBe("disabled"));
    expect(mocks.listUsers).toHaveBeenCalledWith({
      companyId: "co-1",
      status: "disabled",
      limit: 10,
    });
  });

  it("保存用户后刷新当前 SWR Provider 中所有用户列表组合", async () => {
    const { result } = renderHook(
      () => ({
        active: useAdminUsers({ status: "active", limit: 20 }),
        disabled: useAdminUsers({ companyId: "co-1", status: "disabled", limit: 10 }),
        update: useUpdateAdminUser("user-1"),
      }),
      { wrapper: freshSwr }
    );

    await waitFor(() => expect(mocks.listUsers).toHaveBeenCalledTimes(2));

    await act(async () => {
      await expect(result.current.update.updateAdminUser({ note: "已更新" })).resolves.toBe(
        USER
      );
    });

    await waitFor(() => expect(mocks.listUsers).toHaveBeenCalledTimes(4));
    expect(
      countCalls(mocks.listUsers, [{ status: "active", limit: 20 }])
    ).toBe(2);
    expect(
      countCalls(mocks.listUsers, [
        { companyId: "co-1", status: "disabled", limit: 10 },
      ])
    ).toBe(2);
    expect(mocks.updateUser).toHaveBeenCalledWith("user-1", { note: "已更新" });
  });

  it("保存公司后刷新 include-disabled 的两种公司列表", async () => {
    const { result } = renderHook(
      () => ({
        activeOnly: useAdminCompanies(false),
        withDisabled: useAdminCompanies(true),
        save: useSaveCompany(),
      }),
      { wrapper: freshSwr }
    );

    await waitFor(() => expect(mocks.listCompanies).toHaveBeenCalledTimes(2));

    await act(async () => {
      await result.current.save.saveCompany({ company_name: "测试公司" });
    });

    await waitFor(() => expect(mocks.listCompanies).toHaveBeenCalledTimes(4));
    expect(countCalls(mocks.listCompanies, [false])).toBe(2);
    expect(countCalls(mocks.listCompanies, [true])).toBe(2);
  });

  it("角色和标签保存只刷新目标用户的精确缓存 key", async () => {
    const { result } = renderHook(
      () => ({
        targetRolesAll: useAdminUserRoles("user-1"),
        targetRolesCompany: useAdminUserRoles("user-1", "co-1"),
        otherRoles: useAdminUserRoles("user-2", "co-1"),
        targetTags: useAdminUserTags("user-1"),
        otherTags: useAdminUserTags("user-2"),
        saveRoles: useSaveUserRoles({ user_id: "user-1", company_id: "co-1" }),
        saveTags: useSaveUserTags("user-1"),
      }),
      { wrapper: freshSwr }
    );

    await waitFor(() => expect(mocks.getUserRoles).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(mocks.getUserTags).toHaveBeenCalledTimes(2));
    mocks.getUserRoles.mockClear();
    mocks.getUserTags.mockClear();

    await act(async () => {
      await result.current.saveRoles.saveUserRoles({
        company_id: "co-1",
        roles: ["lawyer"],
      });
    });

    await waitFor(() => expect(mocks.getUserRoles).toHaveBeenCalledTimes(2));
    expect(mocks.getUserRoles.mock.calls).toEqual(
      expect.arrayContaining([
        ["user-1", undefined],
        ["user-1", "co-1"],
      ])
    );
    expect(mocks.getUserRoles).not.toHaveBeenCalledWith("user-2", "co-1");

    await act(async () => {
      await result.current.saveTags.saveUserTags({
        dimension: "expertise",
        values: ["收入循环"],
      });
    });

    await waitFor(() => expect(mocks.getUserTags).toHaveBeenCalledTimes(1));
    expect(mocks.getUserTags).toHaveBeenCalledWith("user-1");
    expect(mocks.getUserTags).not.toHaveBeenCalledWith("user-2");
    expect(mocks.replaceUserRoles).toHaveBeenCalledWith("user-1", {
      company_id: "co-1",
      roles: ["lawyer"],
    });
    expect(mocks.replaceUserTags).toHaveBeenCalledWith("user-1", {
      dimension: "expertise",
      values: ["收入循环"],
    });
  });

  it("缓存刷新失败不反转已成功的公司写入", async () => {
    mocks.listCompanies
      .mockReset()
      .mockResolvedValueOnce([COMPANY])
      .mockRejectedValueOnce(new Error("刷新失败"));
    const saved = { ...COMPANY, notes: "已保存" };
    mocks.upsertCompany.mockResolvedValueOnce(saved);

    const { result } = renderHook(
      () => ({ list: useAdminCompanies(false), save: useSaveCompany() }),
      { wrapper: freshSwr }
    );
    await waitFor(() => expect(result.current.list.companies).toEqual([COMPANY]));

    await act(async () => {
      await expect(
        result.current.save.saveCompany({ company_name: "测试公司", notes: "已保存" })
      ).resolves.toEqual(saved);
    });

    expect(result.current.save.data).toEqual(saved);
    expect(result.current.save.error).toBeNull();
    await waitFor(() => expect(result.current.list.error).toBe("刷新失败"));
  });

  it("后端保存失败时不刷新公司列表", async () => {
    mocks.upsertCompany.mockRejectedValueOnce(new Error("保存失败"));
    const { result } = renderHook(
      () => ({ list: useAdminCompanies(false), save: useSaveCompany() }),
      { wrapper: freshSwr }
    );
    await waitFor(() => expect(mocks.listCompanies).toHaveBeenCalledTimes(1));

    await act(async () => {
      await expect(
        result.current.save.saveCompany({ company_name: "失败公司" })
      ).rejects.toThrow("保存失败");
    });

    expect(mocks.listCompanies).toHaveBeenCalledTimes(1);
    expect(result.current.save.error).toBe("保存失败");
  });
});

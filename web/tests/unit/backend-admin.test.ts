import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  companiesKey,
  createUser,
  generateCompanyId,
  getUserRoles,
  getUserTags,
  isCompaniesListKey,
  isUsersListKey,
  listCompanies,
  listRoles,
  listTagCatalog,
  listUsers,
  replaceUserRoles,
  replaceUserTags,
  rolesKey,
  tagCatalogKey,
  updateRolePermission,
  updateUser,
  upsertCompany,
  userRolesKey,
  usersKey,
  userTagsKey,
} from "@/lib/backend/admin";
import { BackendError } from "@/lib/backend/http";

const fetchMock = vi.fn();

function jsonResponse(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

function requestAt(index: number): [string, RequestInit | undefined] {
  return fetchMock.mock.calls[index] as [string, RequestInit | undefined];
}

function jsonBody(init: RequestInit | undefined): unknown {
  return JSON.parse(String(init?.body));
}

describe("admin backend contract", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("NEXT_PUBLIC_LANGGRAPH_API_BASE_URL", "http://langgraph.test");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("构造并编码管理员列表、用户详情与角色 URL", () => {
    expect(tagCatalogKey("project_role")).toBe(
      "http://langgraph.test/tag-catalog?dimension=project_role"
    );
    expect(companiesKey(true)).toBe(
      "http://langgraph.test/companies?include_disabled=true"
    );
    expect(
      usersKey({ companyId: "co /华", status: "active", limit: 25 })
    ).toBe(
      "http://langgraph.test/users?company_id=co+%2F%E5%8D%8E&status=active&limit=25"
    );
    expect(userTagsKey("user/a b")).toBe(
      "http://langgraph.test/users/user%2Fa%20b/tags"
    );
    expect(userRolesKey("user/a b", "co /华")).toBe(
      "http://langgraph.test/users/user%2Fa%20b/roles?company_id=co+%2F%E5%8D%8E"
    );
    expect(rolesKey()).toBe("http://langgraph.test/roles");

    expect(isUsersListKey(usersKey())).toBe(true);
    expect(isUsersListKey(userTagsKey("u1"))).toBe(false);
    expect(isCompaniesListKey(companiesKey())).toBe(true);
    expect(isCompaniesListKey("http://langgraph.test/companies/generate-id")).toBe(false);
  });

  it("解包标签、公司和用户列表，并保留角色目录结构", async () => {
    const tag = {
      dimension: "expertise",
      tag_value: "破产重整",
      tag_group: "专业领域",
      sort_order: 1,
    } as const;
    const company = {
      company_id: "co-1",
      company_name: "测试公司",
      company_name_norm: "测试公司",
      company_type: "customer",
      status: "active",
      notes: "",
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
    } as const;
    const user = {
      user_id: "u1",
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
    } as const;
    const roles = {
      roles: {
        analyst: {
          role_name: "分析员",
          tier: "expert",
          modules: ["report"],
          visible_report_sections: ["data_gap_audit"],
          description: "",
        },
      },
      report_sections: [],
      all_modules: ["report"],
      tiers: ["field", "expert", "management"],
    } as const;

    fetchMock
      .mockResolvedValueOnce(jsonResponse({ catalog: [tag] }))
      .mockResolvedValueOnce(jsonResponse({ companies: [company] }))
      .mockResolvedValueOnce(jsonResponse({ users: [user] }))
      .mockResolvedValueOnce(jsonResponse(roles));

    await expect(listTagCatalog("expertise")).resolves.toEqual([tag]);
    await expect(listCompanies()).resolves.toEqual([company]);
    await expect(listUsers({ companyId: "co-1" })).resolves.toEqual([user]);
    await expect(listRoles()).resolves.toEqual(roles);
  });

  it("列表字段缺失时返回空数组", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(jsonResponse({}));

    await expect(listTagCatalog()).resolves.toEqual([]);
    await expect(listCompanies()).resolves.toEqual([]);
    await expect(listUsers()).resolves.toEqual([]);
  });

  it("按契约提交公司 POST 和用户创建/更新请求，并省略空密码", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({})));

    await upsertCompany({
      company_name: "测试公司",
      company_type: "customer",
      status: "active",
      notes: "备注",
    });
    await createUser({
      user_id: "u1",
      username: "alice",
      company_id: "co-1",
      auth_source: "local",
      status: "active",
      password: "   ",
    });
    await updateUser("user/a b", {
      username: "Alice Updated",
      password: "",
      note: "已更新",
    });

    const [companyUrl, companyInit] = requestAt(0);
    expect(companyUrl).toBe("http://langgraph.test/companies");
    expect(companyInit?.method).toBe("POST");
    expect(jsonBody(companyInit)).toEqual({
      company_name: "测试公司",
      company_type: "customer",
      status: "active",
      notes: "备注",
    });

    const [createUrl, createInit] = requestAt(1);
    expect(createUrl).toBe("http://langgraph.test/users");
    expect(createInit?.method).toBe("POST");
    expect(jsonBody(createInit)).toEqual({
      user_id: "u1",
      username: "alice",
      company_id: "co-1",
      auth_source: "local",
      status: "active",
    });

    const [updateUrl, updateInit] = requestAt(2);
    expect(updateUrl).toBe("http://langgraph.test/users/user%2Fa%20b");
    expect(updateInit?.method).toBe("PUT");
    expect(jsonBody(updateInit)).toEqual({
      username: "Alice Updated",
      note: "已更新",
    });
  });

  it("完整保留角色、标签与权限更新中的空数组", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({})));

    await replaceUserRoles("user/a", { company_id: "co-1", roles: [] });
    await replaceUserTags("user/a", { dimension: "expertise", values: [] });
    await updateRolePermission("role/a", {
      role_name: "空权限角色",
      tier: "field",
      modules: [],
      visible_report_sections: [],
      description: "测试清空权限",
    });

    const [rolesUrl, rolesInit] = requestAt(0);
    expect(rolesUrl).toBe("http://langgraph.test/users/user%2Fa/roles");
    expect(rolesInit?.method).toBe("PUT");
    expect(jsonBody(rolesInit)).toEqual({ company_id: "co-1", roles: [] });

    const [tagsUrl, tagsInit] = requestAt(1);
    expect(tagsUrl).toBe("http://langgraph.test/users/user%2Fa/tags");
    expect(tagsInit?.method).toBe("PUT");
    expect(jsonBody(tagsInit)).toEqual({ dimension: "expertise", values: [] });

    const [permissionUrl, permissionInit] = requestAt(2);
    expect(permissionUrl).toBe("http://langgraph.test/roles/role%2Fa");
    expect(permissionInit?.method).toBe("PUT");
    expect(jsonBody(permissionInit)).toEqual({
      role_name: "空权限角色",
      tier: "field",
      modules: [],
      visible_report_sections: [],
      description: "测试清空权限",
    });
  });

  it("读取公司 ID、用户标签与带公司过滤的用户角色", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ company_name: "测试 公司", company_id: "co-1" }))
      .mockResolvedValueOnce(
        jsonResponse({
          user_id: "user/a",
          tags: {
            project_role: [],
            title: [],
            expertise: [],
            company: "测试公司",
            region: "",
          },
        })
      )
      .mockResolvedValueOnce(
        jsonResponse({ user_id: "user/a", company_id: "co /华", roles: [] })
      );

    await generateCompanyId("测试 公司");
    await getUserTags("user/a");
    await getUserRoles("user/a", "co /华");

    expect(requestAt(0)[0]).toBe(
      "http://langgraph.test/companies/generate-id?company_name=%E6%B5%8B%E8%AF%95+%E5%85%AC%E5%8F%B8"
    );
    expect(requestAt(1)[0]).toBe("http://langgraph.test/users/user%2Fa/tags");
    expect(requestAt(2)[0]).toBe(
      "http://langgraph.test/users/user%2Fa/roles?company_id=co+%2F%E5%8D%8E"
    );
  });

  it("把 403 detail 保留为带状态码的 BackendError", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "仅超级管理员可修改角色权限" }, 403)
    );

    const error = await updateRolePermission("company_admin", {
      tier: "management",
      modules: ["admin"],
    }).catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(BackendError);
    expect(error).toMatchObject({
      message: "仅超级管理员可修改角色权限",
      status: 403,
    });
  });
});

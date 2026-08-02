import { langgraphUrl } from "@/lib/api/client";
import { getJson, postJson, putJson } from "./http";

export type CompanyStatus = "active" | "disabled";
export type UserStatus = "active" | "disabled" | "locked";
export type AuthSource = "local" | "platform" | "sso";
export type TagDimension = "project_role" | "title" | "expertise";
export type PermissionTier = "field" | "expert" | "management";

export type ModuleCode =
  | "admin"
  | "corrections"
  | "deadline"
  | "drilldown"
  | "graph"
  | "progress"
  | "report"
  | "review";

export interface CompanyRecord {
  company_id: string;
  company_name: string;
  company_name_norm: string;
  company_type: string;
  status: CompanyStatus;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface CompanyUpsertRequest {
  company_id?: string | null;
  company_name: string;
  company_type?: string;
  status?: CompanyStatus;
  notes?: string;
}

export interface CompanyIdResponse {
  company_name: string;
  company_id: string;
}

export interface AdminUserRecord {
  user_id: string;
  username: string;
  company: string;
  company_id: string;
  company_display_name?: string;
  region: string;
  note: string;
  auth_source: AuthSource;
  status: UserStatus;
  is_super_admin: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface UserUpsertRequest {
  user_id?: string | null;
  username?: string | null;
  company?: string | null;
  company_id?: string | null;
  auth_source?: AuthSource | null;
  status?: UserStatus | null;
  is_super_admin?: boolean | null;
  password?: string | null;
  region?: string | null;
  note?: string | null;
}

export type CreateUserRequest = UserUpsertRequest & {
  user_id: string;
  username: string;
};

export interface UserListParams {
  companyId?: string;
  status?: UserStatus | "";
  limit?: number;
}

export interface UserTags {
  project_role: string[];
  title: string[];
  expertise: string[];
  company: string;
  region: string;
}

export interface UserTagsResponse {
  user_id: string;
  tags: UserTags;
}

export interface TagCatalogItem {
  dimension: TagDimension;
  tag_value: string;
  tag_group: string;
  sort_order: number;
}

export interface TagsUpdateRequest {
  dimension: TagDimension;
  values: string[];
}

export interface TagsUpdateResponse {
  user_id: string;
  dimension: TagDimension;
  values: string[];
}

export interface UserRolesResponse {
  user_id: string;
  company_id: string;
  roles: string[];
}

export interface UserRolesUpdateRequest {
  company_id: string;
  roles: string[];
}

export interface RolePermission {
  role_name: string;
  tier: PermissionTier;
  modules: Array<ModuleCode | "*">;
  visible_report_sections: string[];
  description: string;
}

export interface ReportSection {
  section_code: string;
  section_id: string;
  title: string;
  audience: PermissionTier;
  sort_order: number;
  status: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface RolesResponse {
  roles: Record<string, RolePermission>;
  report_sections: ReportSection[];
  all_modules: ModuleCode[];
  tiers: PermissionTier[];
}

export interface RolePermissionRequest {
  role_name?: string | null;
  tier: PermissionTier;
  modules: Array<ModuleCode | "*">;
  visible_report_sections?: string[] | null;
  description?: string;
}

export interface UserListResponse {
  users: AdminUserRecord[];
}

export interface CompanyListResponse {
  companies: CompanyRecord[];
}

export interface TagCatalogResponse {
  catalog: TagCatalogItem[];
}

export function tagCatalogKey(dimension?: TagDimension): string {
  const query = new URLSearchParams();
  if (dimension) query.set("dimension", dimension);
  const suffix = query.size > 0 ? `?${query}` : "";
  return langgraphUrl(`/tag-catalog${suffix}`);
}

export function companiesKey(includeDisabled = false): string {
  return langgraphUrl(`/companies?include_disabled=${includeDisabled}`);
}

export function usersKey(params: UserListParams = {}): string {
  const query = new URLSearchParams();
  if (params.companyId) query.set("company_id", params.companyId);
  if (params.status) query.set("status", params.status);
  query.set("limit", String(params.limit ?? 200));
  return langgraphUrl(`/users?${query}`);
}

export function userTagsKey(userId: string): string {
  return langgraphUrl(`/users/${encodeURIComponent(userId)}/tags`);
}

export function userRolesKey(userId: string, companyId?: string): string {
  const query = new URLSearchParams();
  if (companyId) query.set("company_id", companyId);
  const suffix = query.size > 0 ? `?${query}` : "";
  return langgraphUrl(`/users/${encodeURIComponent(userId)}/roles${suffix}`);
}

export function rolesKey(): string {
  return langgraphUrl("/roles");
}

export function isUsersListKey(key: unknown): key is string {
  return typeof key === "string" && key.startsWith(langgraphUrl("/users?"));
}

export function isCompaniesListKey(key: unknown): key is string {
  return typeof key === "string" && key.startsWith(langgraphUrl("/companies?"));
}

export async function listTagCatalog(dimension?: TagDimension): Promise<TagCatalogItem[]> {
  const response = await getJson<TagCatalogResponse>(
    tagCatalogKey(dimension),
    "获取人员标签目录失败"
  );
  return response.catalog ?? [];
}

export async function listCompanies(includeDisabled = false): Promise<CompanyRecord[]> {
  const response = await getJson<CompanyListResponse>(
    companiesKey(includeDisabled),
    "获取公司列表失败"
  );
  return response.companies ?? [];
}

export function upsertCompany(request: CompanyUpsertRequest): Promise<CompanyRecord> {
  return postJson<CompanyRecord>(langgraphUrl("/companies"), request, "保存公司失败");
}

export function generateCompanyId(companyName: string): Promise<CompanyIdResponse> {
  const query = new URLSearchParams({ company_name: companyName });
  return getJson<CompanyIdResponse>(
    langgraphUrl(`/companies/generate-id?${query}`),
    "生成公司 ID 失败"
  );
}

export async function listUsers(params: UserListParams = {}): Promise<AdminUserRecord[]> {
  const response = await getJson<UserListResponse>(usersKey(params), "获取用户列表失败");
  return response.users ?? [];
}

function withoutEmptyPassword<T extends UserUpsertRequest>(request: T): T {
  if (typeof request.password !== "string" || request.password.trim().length > 0) {
    return request;
  }
  const sanitized = { ...request };
  delete sanitized.password;
  return sanitized;
}

export function createUser(request: CreateUserRequest): Promise<AdminUserRecord> {
  return postJson<AdminUserRecord>(
    langgraphUrl("/users"),
    withoutEmptyPassword(request),
    "创建用户失败"
  );
}

export function updateUser(
  userId: string,
  request: UserUpsertRequest
): Promise<AdminUserRecord> {
  return putJson<AdminUserRecord>(
    langgraphUrl(`/users/${encodeURIComponent(userId)}`),
    withoutEmptyPassword(request),
    "更新用户失败"
  );
}

export function getUserTags(userId: string): Promise<UserTagsResponse> {
  return getJson<UserTagsResponse>(userTagsKey(userId), "获取用户标签失败");
}

export function replaceUserTags(
  userId: string,
  request: TagsUpdateRequest
): Promise<TagsUpdateResponse> {
  return putJson<TagsUpdateResponse>(userTagsKey(userId), request, "更新用户标签失败");
}

export function getUserRoles(userId: string, companyId?: string): Promise<UserRolesResponse> {
  return getJson<UserRolesResponse>(
    userRolesKey(userId, companyId),
    "获取用户角色失败"
  );
}

export function replaceUserRoles(
  userId: string,
  request: UserRolesUpdateRequest
): Promise<UserRolesResponse> {
  return putJson<UserRolesResponse>(
    userRolesKey(userId),
    request,
    "更新用户角色失败"
  );
}

export function listRoles(): Promise<RolesResponse> {
  return getJson<RolesResponse>(rolesKey(), "获取角色权限失败");
}

export function updateRolePermission(
  roleCode: string,
  request: RolePermissionRequest
): Promise<RolePermission> {
  return putJson<RolePermission>(
    langgraphUrl(`/roles/${encodeURIComponent(roleCode)}`),
    request,
    "更新角色权限失败"
  );
}

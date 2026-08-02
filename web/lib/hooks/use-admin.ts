"use client";

import useSWR, { useSWRConfig } from "swr";
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
  userTagsKey,
  usersKey,
  type AdminUserRecord,
  type CompanyUpsertRequest,
  type CreateUserRequest,
  type RolePermissionRequest,
  type TagDimension,
  type TagsUpdateRequest,
  type UserListParams,
  type UserRolesUpdateRequest,
  type UserUpsertRequest,
} from "@/lib/backend/admin";
import { useAuth } from "@/lib/hooks/use-auth";
import { useBackendMutation } from "@/lib/hooks/use-backend-mutation";

function errorMessage(error: unknown): string | null {
  if (!error) return null;
  return error instanceof Error ? error.message : "Unknown error";
}

function ignoreRevalidationFailure(work: Promise<unknown> | unknown): void {
  void Promise.resolve(work).catch(() => undefined);
}

export function useAdminCompanies(includeDisabled = true) {
  const { data, error, isLoading, mutate } = useSWR(
    companiesKey(includeDisabled),
    () => listCompanies(includeDisabled)
  );

  return {
    companies: data ?? [],
    isLoading,
    error: errorMessage(error),
    refresh: mutate,
  };
}

export function useAdminUsers(params: UserListParams = {}) {
  const key = usersKey(params);
  const { data, error, isLoading, mutate } = useSWR(key, () => listUsers(params));

  return {
    users: data ?? [],
    isLoading,
    error: errorMessage(error),
    refresh: mutate,
  };
}

export function useAdminRoles() {
  const { data, error, isLoading, mutate } = useSWR(rolesKey(), listRoles);
  return {
    roles: data?.roles ?? {},
    reportSections: data?.report_sections ?? [],
    allModules: data?.all_modules ?? [],
    tiers: data?.tiers ?? [],
    isLoading,
    error: errorMessage(error),
    refresh: mutate,
  };
}

export function useTagCatalog(dimension?: TagDimension) {
  const { data, error, isLoading, mutate } = useSWR(
    tagCatalogKey(dimension),
    () => listTagCatalog(dimension)
  );
  return {
    catalog: data ?? [],
    isLoading,
    error: errorMessage(error),
    refresh: mutate,
  };
}

export function useAdminUserRoles(
  userId: string | null,
  companyId?: string
) {
  const key = userId ? userRolesKey(userId, companyId) : null;
  const { data, error, isLoading, mutate } = useSWR(
    key,
    () => getUserRoles(userId as string, companyId)
  );
  return {
    data: data ?? null,
    isLoading,
    error: errorMessage(error),
    refresh: mutate,
  };
}

export function useAdminUserTags(userId: string | null) {
  const key = userId ? userTagsKey(userId) : null;
  const { data, error, isLoading, mutate } = useSWR(
    key,
    () => getUserTags(userId as string)
  );
  return {
    data: data ?? null,
    isLoading,
    error: errorMessage(error),
    refresh: mutate,
  };
}

export function useSaveCompany() {
  const { mutate } = useSWRConfig();
  const mutation = useBackendMutation(async (request: CompanyUpsertRequest) => {
    const result = await upsertCompany(request);
    ignoreRevalidationFailure(mutate(isCompaniesListKey));
    return result;
  });
  return { ...mutation, saveCompany: mutation.trigger };
}

export function useGenerateCompanyId() {
  const mutation = useBackendMutation(async (companyName: string) =>
    generateCompanyId(companyName.trim())
  );
  return { ...mutation, generateCompanyId: mutation.trigger };
}

export function useCreateAdminUser() {
  const { mutate } = useSWRConfig();
  const mutation = useBackendMutation(async (request: CreateUserRequest) => {
    const result = await createUser(request);
    ignoreRevalidationFailure(mutate(isUsersListKey));
    return result;
  });
  return { ...mutation, createAdminUser: mutation.trigger };
}

export function useUpdateAdminUser(userId: string) {
  const { mutate } = useSWRConfig();
  const { user, refresh } = useAuth();
  const mutation = useBackendMutation(async (request: UserUpsertRequest) => {
    const result = await updateUser(userId, request);
    ignoreRevalidationFailure(mutate(isUsersListKey));
    if (user?.user_id === userId) ignoreRevalidationFailure(refresh());
    return result;
  });
  return { ...mutation, updateAdminUser: mutation.trigger };
}

export function useSaveUserRoles(user: Pick<AdminUserRecord, "user_id" | "company_id">) {
  const { mutate } = useSWRConfig();
  const { user: currentUser, refresh } = useAuth();
  const mutation = useBackendMutation(async (request: UserRolesUpdateRequest) => {
    const result = await replaceUserRoles(user.user_id, request);
    ignoreRevalidationFailure(
      Promise.all([
        mutate(userRolesKey(user.user_id)),
        mutate(userRolesKey(user.user_id, request.company_id || user.company_id)),
      ])
    );
    if (currentUser?.user_id === user.user_id) ignoreRevalidationFailure(refresh());
    return result;
  });
  return { ...mutation, saveUserRoles: mutation.trigger };
}

export function useSaveUserTags(userId: string) {
  const { mutate } = useSWRConfig();
  const { user, refresh } = useAuth();
  const mutation = useBackendMutation(async (request: TagsUpdateRequest) => {
    const result = await replaceUserTags(userId, request);
    ignoreRevalidationFailure(mutate(userTagsKey(userId)));
    if (user?.user_id === userId) ignoreRevalidationFailure(refresh());
    return result;
  });
  return { ...mutation, saveUserTags: mutation.trigger };
}

export function useSaveRolePermission(roleCode: string) {
  const { mutate } = useSWRConfig();
  const { refresh } = useAuth();
  const mutation = useBackendMutation(async (request: RolePermissionRequest) => {
    const result = await updateRolePermission(roleCode, request);
    ignoreRevalidationFailure(mutate(rolesKey()));
    // A global role edit can change the current user's effective permissions.
    ignoreRevalidationFailure(refresh());
    return result;
  });
  return { ...mutation, saveRolePermission: mutation.trigger };
}

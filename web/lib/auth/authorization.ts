/**
 * Client-side authorization only controls navigation and presentation.
 * Every privileged operation must still be authorized by the backend.
 */
export interface AuthorizationIdentity {
  user_id?: string;
  authenticated?: boolean;
  is_super_admin?: boolean;
  is_company_admin?: boolean;
  allowed_modules?: string[];
}

function hasAdminModule(user: AuthorizationIdentity): boolean {
  return Boolean(
    user.allowed_modules?.some(
      (moduleName) => moduleName.trim().toLowerCase() === "admin"
    )
  );
}

function hasModule(user: AuthorizationIdentity, moduleName: string): boolean {
  const normalized = moduleName.trim().toLowerCase();
  return Boolean(
    user.allowed_modules?.some((allowed) => {
      const value = allowed.trim().toLowerCase();
      return value === "*" || value === normalized;
    })
  );
}

/**
 * The auth-disabled backend exposes a synthetic identity for local preview.
 * Requiring every marker prevents other unauthenticated identities from
 * accidentally inheriting the preview-only administrator navigation.
 */
export function isSystemAdminPreview(
  user: AuthorizationIdentity | null | undefined
): boolean {
  return Boolean(
    user?.user_id === "__system__" &&
      user.authenticated === false &&
      user.is_super_admin === true &&
      hasAdminModule(user)
  );
}

export function canAccessAdmin(
  user: AuthorizationIdentity | null | undefined
): boolean {
  if (!user) return false;
  if (user.authenticated === false) return isSystemAdminPreview(user);

  // Company administrators remain disabled until backend tenant scoping is
  // enforced for every administrator endpoint.
  return user.is_super_admin === true;
}

export function canManageCompanies(
  user: AuthorizationIdentity | null | undefined
): boolean {
  // Company management is intentionally super-admin-only. The synthetic
  // system identity is accepted solely for the explicit local preview mode.
  return canAccessAdmin(user);
}

/**
 * Gate feature modules using the effective permissions returned by /me.
 * Super administrators retain full access even when an older backend omits
 * allowed_modules; the synthetic preview identity remains tightly scoped.
 */
export function canAccessModule(
  user: AuthorizationIdentity | null | undefined,
  moduleName: string
): boolean {
  if (!user) return false;
  if (user.authenticated === false) {
    return isSystemAdminPreview(user) && hasModule(user, moduleName);
  }
  return user.is_super_admin === true || hasModule(user, moduleName);
}

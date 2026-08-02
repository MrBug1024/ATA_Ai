export const AUTH_SESSION_STORAGE_KEY = "ai-hunter.auth-session";
const EXPIRY_SKEW_MS = 30_000;

export interface AuthSession {
  accessToken: string;
  tokenType: string;
  expiresAt: string;
  userId: string;
  username: string;
  companyId: string;
}

function getStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    const storage = window.localStorage;
    return typeof storage?.getItem === "function" &&
      typeof storage?.setItem === "function" &&
      typeof storage?.removeItem === "function"
      ? storage
      : null;
  } catch {
    return null;
  }
}

function isAuthSession(value: unknown): value is AuthSession {
  if (typeof value !== "object" || value === null) return false;
  const session = value as Partial<AuthSession>;
  return (
    typeof session.accessToken === "string" &&
    session.accessToken.length > 0 &&
    typeof session.tokenType === "string" &&
    typeof session.expiresAt === "string" &&
    typeof session.userId === "string" &&
    typeof session.username === "string" &&
    typeof session.companyId === "string"
  );
}

function isExpired(expiresAt: string): boolean {
  const timestamp = Date.parse(expiresAt);
  return !Number.isFinite(timestamp) || timestamp <= Date.now() + EXPIRY_SKEW_MS;
}

export function storeAuthSession(session: AuthSession): void {
  try {
    getStorage()?.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(session));
  } catch {
    // Storage can be unavailable in restricted browser contexts.
  }
}

export function clearAuthSession(): void {
  try {
    getStorage()?.removeItem(AUTH_SESSION_STORAGE_KEY);
  } catch {
    // Local cleanup is best-effort when storage access is restricted.
  }
}

function removeStoredSession(storage: Storage): void {
  try {
    storage.removeItem(AUTH_SESSION_STORAGE_KEY);
  } catch {
    // Invalid stored data may be impossible to remove in restricted contexts.
  }
}

export function getAuthSession(): AuthSession | null {
  const storage = getStorage();
  if (!storage) return null;

  let raw: string | null;
  try {
    raw = storage.getItem(AUTH_SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  try {
    const session: unknown = JSON.parse(raw);
    if (!isAuthSession(session) || isExpired(session.expiresAt)) {
      removeStoredSession(storage);
      return null;
    }
    return session;
  } catch {
    removeStoredSession(storage);
    return null;
  }
}

export function getAuthorizationHeader(): string | null {
  const session = getAuthSession();
  if (!session) return null;
  return `${session.tokenType || "bearer"} ${session.accessToken}`;
}

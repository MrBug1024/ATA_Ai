import { clearAuthSession, getAuthorizationHeader } from "@/lib/auth/token-store";

/**
 * Low-level transport for LangGraph and Cases requests.
 *
 * The unified backend receives the browser-held bearer token. During rollback
 * only, a separately configured legacy Cases API remains unauthenticated.
 */

const PUBLIC_PATHS = new Set(["/login"]);

function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  if (PUBLIC_PATHS.has(window.location.pathname)) return;
  const from = window.location.pathname + window.location.search;
  window.location.href = `/login?from=${encodeURIComponent(from)}`;
}

export class UnauthorizedError extends Error {
  constructor(message = "Unauthorized") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

export interface ApiFetchOptions {
  /** Override automatic bearer attachment for LangGraph requests. */
  auth?: boolean;
  /** Let callers such as login and /me inspect a 401 response themselves. */
  handleUnauthorized?: boolean;
}

function inputUrl(input: RequestInfo | URL): string {
  return input instanceof Request ? input.url : String(input);
}

function unifiedApiBaseUrl(): string {
  return trimTrailingSlash(process.env.NEXT_PUBLIC_API_BASE_URL ?? "");
}

function langgraphBaseUrl(): string {
  return (
    unifiedApiBaseUrl() ||
    trimTrailingSlash(process.env.NEXT_PUBLIC_LANGGRAPH_API_BASE_URL ?? "")
  );
}

function casesBaseUrl(): string {
  return (
    unifiedApiBaseUrl() || trimTrailingSlash(process.env.NEXT_PUBLIC_CASES_API_BASE_URL ?? "")
  );
}

function isAuthenticatedApiRequest(input: RequestInfo | URL): boolean {
  const base = langgraphBaseUrl();
  if (!base) return false;
  const url = inputUrl(input);
  return url === base || url.startsWith(`${base}/`);
}

function requestHeaders(input: RequestInfo | URL, init?: RequestInit): Headers {
  const headers = new Headers(input instanceof Request ? input.headers : undefined);
  new Headers(init?.headers).forEach((value, key) => headers.set(key, value));
  return headers;
}

export async function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
  options: ApiFetchOptions = {}
): Promise<Response> {
  const authenticate = options.auth ?? isAuthenticatedApiRequest(input);
  let requestInit = init;
  if (authenticate) {
    const headers = requestHeaders(input, init);
    if (!headers.has("Authorization")) {
      const authorization = getAuthorizationHeader();
      if (authorization) {
        headers.set("Authorization", authorization);
        requestInit = { ...init, headers };
      }
    }
  }

  const response = await fetch(input, requestInit);
  const handleUnauthorized = options.handleUnauthorized ?? authenticate;
  if (response.status === 401 && handleUnauthorized) {
    clearAuthSession();
    redirectToLogin();
    throw new UnauthorizedError();
  }
  return response;
}

function trimTrailingSlash(url: string): string {
  return url.endsWith("/") ? url.slice(0, -1) : url;
}

export function casesUrl(path: string): string {
  return `${casesBaseUrl()}${path}`;
}

export function langgraphUrl(path: string): string {
  return `${langgraphBaseUrl()}${path}`;
}

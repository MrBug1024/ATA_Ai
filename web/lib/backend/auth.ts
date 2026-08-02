import { apiFetch, langgraphUrl } from "@/lib/api/client";
import { BackendError, extractErrorMessage } from "./http";

export interface LoginRequest {
  login_identifier: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type?: string;
  expires_at: string;
  user_id: string;
  username: string;
  company_id: string;
}

export interface MeResponse {
  user_id?: string;
  username?: string;
  roles?: string[];
  company_id?: string;
  apps?: string[];
  is_company_admin?: boolean;
  is_super_admin?: boolean;
  authenticated?: boolean;
  visible_audiences?: string[];
  visible_report_sections?: string[];
  allowed_modules?: string[];
  tags?: Record<string, unknown>;
}

export interface PasswordChangeRequest {
  old_password: string;
  new_password: string;
}

async function readBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function authRequest<T>(
  path: string,
  init: RequestInit,
  fallback: string,
  authenticated: boolean
): Promise<T> {
  const response = await apiFetch(langgraphUrl(path), init, {
    auth: authenticated,
    handleUnauthorized: false,
  });
  const body = await readBody(response);
  if (!response.ok) {
    throw new BackendError(
      extractErrorMessage(body, `${fallback} (${response.status})`),
      response.status
    );
  }
  return body as T;
}

export function login(request: LoginRequest): Promise<LoginResponse> {
  return authRequest<LoginResponse>(
    "/auth/login",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    "登录失败",
    false
  );
}

export function getMe(): Promise<MeResponse> {
  return authRequest<MeResponse>("/me", { method: "GET" }, "获取当前用户失败", true);
}

export async function logout(): Promise<void> {
  await authRequest<Record<string, unknown>>(
    "/auth/logout",
    { method: "POST" },
    "退出登录失败",
    true
  );
}

export async function changePassword(request: PasswordChangeRequest): Promise<void> {
  await authRequest<Record<string, unknown>>(
    "/auth/password/change",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    "修改密码失败",
    true
  );
}

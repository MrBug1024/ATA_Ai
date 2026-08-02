import { apiFetch } from "@/lib/api/client";

/** 后端(LangGraph / Cases)返回非 2xx 时抛出,携带 HTTP 状态码与解析后的错误信息。 */
export class BackendError extends Error {
  constructor(
    message: string,
    public readonly status: number
  ) {
    super(message);
    this.name = "BackendError";
  }
}

/**
 * 从后端错误体提取人类可读信息,统一三种历史格式:
 * FastAPI 校验错误 `{ detail: [{ msg }] }`、`{ detail: string }`、`{ error | message: string }`。
 */
export function extractErrorMessage(body: unknown, fallback: string): string {
  if (typeof body !== "object" || body === null) return fallback;
  const b = body as Record<string, unknown>;
  if (Array.isArray(b.detail)) {
    const msgs = b.detail
      .map((d) => (typeof d === "object" && d !== null ? (d as { msg?: string }).msg : undefined))
      .filter((m): m is string => typeof m === "string" && m.length > 0);
    if (msgs.length > 0) return msgs.join("; ");
  }
  if (typeof b.detail === "string" && b.detail) return b.detail;
  if (typeof b.error === "string" && b.error) return b.error;
  if (typeof b.message === "string" && b.message) return b.message;
  return fallback;
}

async function readErrorBody(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

async function requestJson<T>(
  url: string,
  init: RequestInit | undefined,
  fallback: string
): Promise<T> {
  const res = await apiFetch(url, init);
  if (!res.ok) {
    const body = await readErrorBody(res);
    throw new BackendError(extractErrorMessage(body, `${fallback} (${res.status})`), res.status);
  }
  return res.json() as Promise<T>;
}

export async function getJson<T>(url: string, fallback = "请求失败"): Promise<T> {
  return requestJson<T>(url, undefined, fallback);
}

export async function postJson<T>(
  url: string,
  body: unknown,
  fallback = "请求失败"
): Promise<T> {
  return requestJson<T>(
    url,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    fallback
  );
}

export async function postWithoutBody<T>(
  url: string,
  fallback = "请求失败"
): Promise<T> {
  return requestJson<T>(url, { method: "POST" }, fallback);
}

export async function putJson<T>(
  url: string,
  body: unknown,
  fallback = "请求失败"
): Promise<T> {
  return requestJson<T>(
    url,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    fallback
  );
}

export async function postForm<T>(
  url: string,
  form: FormData,
  fallback = "请求失败"
): Promise<T> {
  return requestJson<T>(url, { method: "POST", body: form }, fallback);
}

export async function deleteJson(url: string, fallback = "删除失败"): Promise<void> {
  const res = await apiFetch(url, { method: "DELETE" });
  if (!res.ok) {
    const body = await readErrorBody(res);
    throw new BackendError(extractErrorMessage(body, `${fallback} (${res.status})`), res.status);
  }
}

import { describe, it, expect, vi, beforeEach } from "vitest";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

beforeEach(() => {
  mockFetch.mockReset();
});

describe("extractErrorMessage", () => {
  it("joins FastAPI detail array msgs", async () => {
    const { extractErrorMessage } = await import("@/lib/backend/http");
    expect(
      extractErrorMessage({ detail: [{ msg: "字段缺失" }, { msg: "类型错误" }] }, "fallback")
    ).toBe("字段缺失; 类型错误");
  });

  it("returns detail string directly", async () => {
    const { extractErrorMessage } = await import("@/lib/backend/http");
    expect(extractErrorMessage({ detail: "案件不存在" }, "fallback")).toBe("案件不存在");
  });

  it("returns the message from a structured FastAPI domain error", async () => {
    const { extractErrorMessage } = await import("@/lib/backend/http");
    expect(
      extractErrorMessage(
        { detail: { code: "JOB_NOT_RETRYABLE", message: "当前任务没有可重试的失败项" } },
        "fallback"
      )
    ).toBe("当前任务没有可重试的失败项");
  });

  it("returns error field when present", async () => {
    const { extractErrorMessage } = await import("@/lib/backend/http");
    expect(extractErrorMessage({ error: "boom" }, "fallback")).toBe("boom");
  });

  it("returns message field when present", async () => {
    const { extractErrorMessage } = await import("@/lib/backend/http");
    expect(extractErrorMessage({ message: "stream error" }, "fallback")).toBe("stream error");
  });

  it("falls back for empty or non-object bodies", async () => {
    const { extractErrorMessage } = await import("@/lib/backend/http");
    expect(extractErrorMessage({}, "fallback")).toBe("fallback");
    expect(extractErrorMessage(null, "fallback")).toBe("fallback");
    expect(extractErrorMessage("oops", "fallback")).toBe("fallback");
  });
});

describe("getJson", () => {
  it("returns parsed body on ok", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ a: 1 }) });
    const { getJson } = await import("@/lib/backend/http");
    await expect(getJson<{ a: number }>("http://test/x")).resolves.toEqual({ a: 1 });
    expect(mockFetch).toHaveBeenCalledWith("http://test/x", undefined);
  });

  it("throws BackendError with extracted message on !ok", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({ detail: "未找到" }),
    });
    const { getJson, BackendError } = await import("@/lib/backend/http");
    const err = await getJson("http://test/x", "请求失败").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(BackendError);
    expect((err as Error).message).toBe("未找到");
    expect((err as { status: number }).status).toBe(404);
  });

  it("keeps a backend 401 as a BackendError instead of treating it as Web logout", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: "LangGraph authentication failed" }),
    });
    const { getJson, BackendError } = await import("@/lib/backend/http");
    const err = await getJson("http://test/x", "请求失败").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(BackendError);
    expect((err as Error).message).toBe("LangGraph authentication failed");
    expect((err as { status: number }).status).toBe(401);
  });

  it("throws fallback message when error body is missing json()", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });
    const { getJson } = await import("@/lib/backend/http");
    const err = await getJson("http://test/x", "请求失败").catch((e: unknown) => e);
    expect((err as Error).message).toBe("请求失败 (500)");
  });
});

describe("postJson", () => {
  it("sends JSON body with content-type header", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) });
    const { postJson } = await import("@/lib/backend/http");
    await postJson("http://test/y", { q: "hi" });
    expect(mockFetch).toHaveBeenCalledWith(
      "http://test/y",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ q: "hi" }),
      })
    );
  });
});

describe("postWithoutBody", () => {
  it("sends POST without content-type or body", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) });
    const { postWithoutBody } = await import("@/lib/backend/http");
    await postWithoutBody("http://test/action");
    expect(mockFetch).toHaveBeenCalledWith("http://test/action", { method: "POST" });
  });
});

describe("putJson", () => {
  it("sends JSON body with PUT method", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) });
    const { putJson } = await import("@/lib/backend/http");
    await putJson("http://test/p", { q: "hi" });
    expect(mockFetch).toHaveBeenCalledWith(
      "http://test/p",
      expect.objectContaining({
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ q: "hi" }),
      })
    );
  });

  it("throws BackendError with extracted message on !ok", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ detail: "参数错误" }),
    });
    const { putJson, BackendError } = await import("@/lib/backend/http");
    const err = await putJson("http://test/p", {}, "更新失败").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(BackendError);
    expect((err as Error).message).toBe("参数错误");
  });
});

describe("patchJson", () => {
  it("sends JSON body with PATCH method", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ revision: 2 }) });
    const { patchJson } = await import("@/lib/backend/http");
    await patchJson("http://test/version", { revision: 1, name: "新名称" });
    expect(mockFetch).toHaveBeenCalledWith(
      "http://test/version",
      expect.objectContaining({
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision: 1, name: "新名称" }),
      })
    );
  });
});

describe("postForm", () => {
  it("sends FormData without explicit content-type", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) });
    const { postForm } = await import("@/lib/backend/http");
    const form = new FormData();
    form.append("k", "v");
    await postForm("http://test/z", form);
    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.body).toBe(form);
    expect(init.headers).toBeUndefined();
  });
});

describe("deleteJson", () => {
  it("resolves void on ok", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    const { deleteJson } = await import("@/lib/backend/http");
    await expect(deleteJson("http://test/d")).resolves.toBeUndefined();
    expect(mockFetch).toHaveBeenCalledWith(
      "http://test/d",
      expect.objectContaining({ method: "DELETE" })
    );
  });

  it("throws BackendError on !ok", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 403, json: async () => ({}) });
    const { deleteJson, BackendError } = await import("@/lib/backend/http");
    await expect(deleteJson("http://test/d", "删除失败")).rejects.toBeInstanceOf(BackendError);
  });
});

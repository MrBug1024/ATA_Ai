// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useUploadIngest } from "@/lib/hooks/use-upload-ingest";
import { useValidateDocCategory } from "@/lib/hooks/use-validate-doc-category";

vi.mock("@/lib/auth/token-store", () => ({
  getAuthorizationHeader: () => null,
  clearAuthSession: vi.fn(),
}));

function jsonRes(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("useUploadIngest", () => {
  it("成功上传，构造 multipart 请求并返回响应", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes({ material_event_id: "ev-1" }));
    const { result } = renderHook(() => useUploadIngest());
    const resp = await result.current.upload({
      files: [new File(["d"], "a.pdf")],
      current_case_id: 1,
      doc_category: "类别",
      batch_name: "批次A",
    });
    expect(resp).toMatchObject({ material_event_id: "ev-1" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8080/files/upload-and-ingest");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toBeInstanceOf(FormData);
    const form = (init as RequestInit).body as FormData;
    expect(form.get("current_case_id")).toBe("1");
    expect(form.get("case_id")).toBeNull();
    expect(form.get("doc_category")).toBe("类别");
    expect(form.get("batch_name")).toBe("批次A");
  });

  it("失败时抛出上游 error 文案", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes({ error: "上游拒绝" }, 400));
    const { result } = renderHook(() => useUploadIngest());
    await expect(
      result.current.upload({
        files: [new File(["d"], "a.pdf")],
        current_case_id: 1,
        doc_category: "x",
      })
    ).rejects.toThrow("上游拒绝");
  });

  it("失败且无 JSON 时使用默认文案", async () => {
    fetchMock.mockResolvedValueOnce(new Response("nope", { status: 500 }));
    const { result } = renderHook(() => useUploadIngest());
    await expect(
      result.current.upload({
        files: [new File(["d"], "a.pdf")],
        current_case_id: 1,
        doc_category: "x",
      })
    ).rejects.toThrow("上传失败 (500)");
  });
});

describe("useValidateDocCategory", () => {
  it("成功校验并返回响应", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes({ valid: true }));
    const { result } = renderHook(() => useValidateDocCategory());
    const resp = await result.current.validate({ doc_category: "x" } as never);
    expect(resp).toMatchObject({ valid: true });
    const [url, init] = fetchMock.mock.calls[0];
    // path stays the same (Cases API)
    expect(url).toBe("http://localhost:8080/api/ingest/validate-doc-category");
    expect((init as RequestInit).method).toBe("POST");
  });

  it("失败时抛出上游 error 文案", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes({ error: "无效分类" }, 422));
    const { result } = renderHook(() => useValidateDocCategory());
    await expect(result.current.validate({ doc_category: "x" } as never)).rejects.toThrow(
      "无效分类"
    );
  });

  it("失败且无 JSON 时使用默认文案", async () => {
    fetchMock.mockResolvedValueOnce(new Response("nope", { status: 503 }));
    const { result } = renderHook(() => useValidateDocCategory());
    await expect(result.current.validate({ doc_category: "x" } as never)).rejects.toThrow(
      "校验失败 (503)"
    );
  });
});

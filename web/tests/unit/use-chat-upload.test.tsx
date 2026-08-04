// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useChatUpload } from "@/lib/hooks/use-chat-upload";

function jsonRes(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("useChatUpload", () => {
  it("成功: 200 返回 ChatUploadResponse", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonRes({
        upload_batch_id: "b1",
        case_id: 42,
        entity_id: 0,
        entity_name: "",
        effective_entity_name: "",
        file_count: 1,
        duplicate_files: [],
        files: [
          {
            name: "a.pdf",
            url: "s3://...",
            type: "file",
            extension: ".pdf",
            content_type: "application/pdf",
            content: "",
            doc_category: "",
            upload_batch_id: "b1",
            file_hash: "h1",
            file_size: 100,
            content_ref: "",
            duplicate_of: "",
            storage_ref: "s3://bucket/k",
            storage_provider: "s3",
            storage_bucket: "bucket",
            storage_key: "k",
            storage_etag: "e",
            storage_version: "v",
          },
        ],
      })
    );

    const { result } = renderHook(() => useChatUpload());
    const resp = await result.current.upload(
      { caseId: 42 },
      [new File(["x"], "a.pdf")]
    );

    expect(resp.file_count).toBe(1);
    expect(resp.files[0].file_hash).toBe("h1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8080/chat/upload-files");
    expect((init as RequestInit).method).toBe("POST");
    const form = (init as RequestInit).body as FormData;
    expect(form.get("current_case_id")).toBe("42");
    expect(form.get("current_entity_id")).toBe("0");
    expect(form.get("current_entity_name")).toBe("");
    const files = form.getAll("files");
    expect(files).toHaveLength(1);
  });

  it("422 抛错使用 detail[0].msg", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonRes({ detail: [{ msg: "case_id 必填" }] }, 422)
    );
    const { result } = renderHook(() => useChatUpload());
    await expect(
      result.current.upload({ caseId: 0 }, [new File(["x"], "a.pdf")])
    ).rejects.toThrow("case_id 必填");
  });

  it("422 抛错使用 error 字段(老格式)", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes({ error: "上游拒绝" }, 422));
    const { result } = renderHook(() => useChatUpload());
    await expect(
      result.current.upload({ caseId: 1 }, [new File(["x"], "a.pdf")])
    ).rejects.toThrow("上游拒绝");
  });

  it("500 抛错使用默认文案", async () => {
    fetchMock.mockResolvedValueOnce(new Response("nope", { status: 500 }));
    const { result } = renderHook(() => useChatUpload());
    await expect(
      result.current.upload({ caseId: 1 }, [new File(["x"], "a.pdf")])
    ).rejects.toThrow("文件上传失败 (500)");
  });

  it("可选字段 entityId/entityName/docCategory/batchName 等会写入 FormData", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonRes({ upload_batch_id: "b1", case_id: 1, entity_id: 0, entity_name: "", effective_entity_name: "", file_count: 0, duplicate_files: [], files: [] })
    );
    const { result } = renderHook(() => useChatUpload());
    await result.current.upload(
      {
        caseId: 1,
        entityId: 7,
        entityName: "张三",
        docCategory: "合同",
        batchName: "批次A",
        uploadBatchId: "b1",
        operatorId: "u1",
        operatorName: "操作员A",
      },
      []
    );
    const form = fetchMock.mock.calls[0][1]!.body as FormData;
    expect(form.get("current_entity_id")).toBe("7");
    expect(form.get("current_entity_name")).toBe("张三");
    expect(form.get("doc_category")).toBe("合同");
    expect(form.get("batch_name")).toBe("批次A");
    expect(form.get("upload_batch_id")).toBe("b1");
    expect(form.get("operator_id")).toBe("u1");
    expect(form.get("operator_name")).toBe("操作员A");
  });
});

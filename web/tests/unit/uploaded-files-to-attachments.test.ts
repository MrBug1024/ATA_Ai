import { describe, it, expect } from "vitest";
import { uploadedFilesToAttachments } from "@/lib/assistant-ui/uploaded-files-to-attachments";
import type { FileItem } from "@/lib/types/chat-upload";

function makeFile(over: Partial<FileItem>): FileItem {
  return {
    name: "f.bin",
    url: "https://x/f.bin",
    type: "file",
    extension: ".bin",
    content_type: "application/octet-stream",
    content: "",
    doc_category: "",
    upload_batch_id: "b1",
    file_hash: "h1",
    file_size: 1,
    content_ref: "",
    duplicate_of: "",
    storage_ref: "",
    storage_provider: "minio",
    storage_bucket: "x",
    storage_key: "f.bin",
    storage_etag: "",
    storage_version: "",
    ...over,
  };
}

describe("uploadedFilesToAttachments", () => {
  it("空数组返回空 attachments 与空 seeds", () => {
    const r = uploadedFilesToAttachments([]);
    expect(r.attachments).toEqual([]);
    expect(r.seeds).toEqual([]);
  });

  it("image 文件 → type=image，并产出 preview seed", () => {
    const f = makeFile({
      name: "shot.png",
      content_type: "image/png",
      file_hash: "abc",
      url: "https://minio/x/shot.png",
    });
    const r = uploadedFilesToAttachments([f]);
    expect(r.attachments).toHaveLength(1);
    const a = r.attachments![0] as { id: string; type: string; name: string; contentType: string; status: { type: string } };
    expect(a.type).toBe("image");
    expect(a.name).toBe("shot.png");
    expect(a.contentType).toBe("image/png");
    expect(a.status.type).toBe("complete");
    expect(a.id).toBe("att-abc");
    expect(r.seeds).toEqual([{ id: "att-abc", url: "https://minio/x/shot.png" }]);
  });

  it("pdf 文件 → type=document", () => {
    const f = makeFile({ name: "a.pdf", content_type: "application/pdf", file_hash: "p1" });
    const r = uploadedFilesToAttachments([f]);
    expect((r.attachments![0] as { type: string }).type).toBe("document");
  });

  it("其它类型 → type=file", () => {
    const f = makeFile({ name: "a.txt", content_type: "text/plain", file_hash: "t1" });
    const r = uploadedFilesToAttachments([f]);
    expect((r.attachments![0] as { type: string }).type).toBe("file");
  });

  it("id 用 file_hash 稳定派生", () => {
    const f = makeFile({ file_hash: "deadbeef" });
    const r = uploadedFilesToAttachments([f]);
    expect((r.attachments![0] as { id: string }).id).toBe("att-deadbeef");
  });

  it("url 为空时不产出 seed（但仍产 attachment）", () => {
    const f = makeFile({ url: "", file_hash: "noimg", content_type: "image/png" });
    const r = uploadedFilesToAttachments([f]);
    expect(r.attachments).toHaveLength(1);
    expect(r.seeds).toEqual([]);
  });

  it("多个文件按序映射", () => {
    const files = [
      makeFile({ name: "1.png", content_type: "image/png", file_hash: "a" }),
      makeFile({ name: "2.pdf", content_type: "application/pdf", file_hash: "b" }),
    ];
    const r = uploadedFilesToAttachments(files);
    expect(r.attachments).toHaveLength(2);
    expect(r.seeds).toHaveLength(2);
    expect((r.attachments![0] as { name: string }).name).toBe("1.png");
    expect((r.attachments![1] as { name: string }).name).toBe("2.pdf");
  });
});

import { describe, it, expect, beforeEach } from "vitest";
import {
  stageFileItem,
  consumeFileItemsByAttachmentIds,
  primeFileItemsByAttachmentIds,
  seedPreviewUrls,
  getAttachmentPreviewUrl,
  resetAttachmentStore,
} from "@/lib/assistant-ui/attachment-store";
import type { FileItem } from "@/lib/types/chat-upload";

function fileItem(name: string, hash: string, url = `s3://x/${name}`): FileItem {
  return {
    name,
    url,
    type: "file",
    extension: name.split(".").pop() ?? "",
    content_type: "application/pdf",
    content: "",
    doc_category: "",
    upload_batch_id: "b1",
    file_hash: hash,
    file_size: 10,
    content_ref: "",
    duplicate_of: "",
    storage_ref: url,
    storage_provider: "s3",
    storage_bucket: "x",
    storage_key: name,
    storage_etag: "e",
    storage_version: "v",
  };
}

beforeEach(() => {
  resetAttachmentStore();
});

describe("attachment-store", () => {
  it("stage 后 consume 取走 FileItem,preview URL 仍可读", () => {
    stageFileItem("a1", fileItem("a.pdf", "h1"));
    expect(consumeFileItemsByAttachmentIds(["a1"])).toEqual([fileItem("a.pdf", "h1")]);
    expect(consumeFileItemsByAttachmentIds(["a1"])).toEqual([]);
    expect(getAttachmentPreviewUrl("a1")).toBe("s3://x/a.pdf");
  });

  it("url 为空的 FileItem 不产生 preview URL", () => {
    stageFileItem("a2", fileItem("b.pdf", "h2", ""));
    expect(getAttachmentPreviewUrl("a2")).toBeUndefined();
  });

  it("prime 等价于批量 stage", () => {
    const fi = fileItem("c.pdf", "h3");
    primeFileItemsByAttachmentIds([["a3", fi]]);
    expect(getAttachmentPreviewUrl("a3")).toBe("s3://x/c.pdf");
    expect(consumeFileItemsByAttachmentIds(["a3"])).toEqual([fi]);
  });

  it("seedPreviewUrls 只写 preview,不影响 consume;空 url 跳过", () => {
    seedPreviewUrls([
      { id: "s1", url: "https://m/p.png" },
      { id: "s2", url: "" },
    ]);
    expect(getAttachmentPreviewUrl("s1")).toBe("https://m/p.png");
    expect(getAttachmentPreviewUrl("s2")).toBeUndefined();
    expect(consumeFileItemsByAttachmentIds(["s1"])).toEqual([]);
  });

  it("consume 多 id 按输入顺序,缺失的跳过", () => {
    stageFileItem("x1", fileItem("a.pdf", "h1"));
    stageFileItem("x2", fileItem("b.pdf", "h2"));
    const got = consumeFileItemsByAttachmentIds(["missing", "x2", "x1"]);
    expect(got.map((f) => f.file_hash)).toEqual(["h2", "h1"]);
  });

  it("resetAttachmentStore 清空一切", () => {
    stageFileItem("r1", fileItem("a.pdf", "h1"));
    resetAttachmentStore();
    expect(getAttachmentPreviewUrl("r1")).toBeUndefined();
    expect(consumeFileItemsByAttachmentIds(["r1"])).toEqual([]);
  });
});

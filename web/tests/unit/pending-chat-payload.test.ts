import { describe, it, expect } from "vitest";
import {
  parsePendingPayload,
  pendingMessageKey,
  type PendingChatPayload,
} from "@/lib/utils/pending-chat-payload";
import type { FileItem } from "@/lib/types/chat-upload";

describe("pendingMessageKey", () => {
  it("拼接 thread id", () => {
    expect(pendingMessageKey("abc")).toBe("pending-message-abc");
  });
});

function fi(name: string, hash: string): FileItem {
  return {
    name,
    url: `s3://x/${name}`,
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
    storage_ref: `s3://x/${name}`,
    storage_provider: "s3",
    storage_bucket: "x",
    storage_key: name,
    storage_etag: "e",
    storage_version: "v",
  };
}

describe("parsePendingPayload", () => {
  it("null / 空串返回 null", () => {
    expect(parsePendingPayload(null)).toBeNull();
    expect(parsePendingPayload("")).toBeNull();
    expect(parsePendingPayload("   ")).toBeNull();
  });

  it("纯字符串视为 content（向后兼容）", () => {
    expect(parsePendingPayload("hello")).toEqual({ content: "hello" });
  });

  it("解析 JSON payload", () => {
    const payload: PendingChatPayload = {
      content: "看看这个",
      attachments: [
        {
          id: "att-1",
          type: "file",
          name: "a.pdf",
          contentType: "application/pdf",
          content: [],
          status: { type: "complete" },
        },
      ],
      fileItemEntries: [["att-1", fi("a.pdf", "h1")]],
    };
    expect(parsePendingPayload(JSON.stringify(payload))).toEqual(payload);
  });

  it("非法 JSON 退回当字符串处理", () => {
    expect(parsePendingPayload("{not json")).toEqual({ content: "{not json" });
  });

  it("JSON 对象缺 content 字段时退回字符串", () => {
    const raw = JSON.stringify({ foo: "bar" });
    expect(parsePendingPayload(raw)).toEqual({ content: raw });
  });
});

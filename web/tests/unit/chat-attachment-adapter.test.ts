import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createChatAttachmentAdapter } from "@/lib/assistant-ui/chat-attachment-adapter";
import {
  consumeFileItemsByAttachmentIds,
  primeFileItemsByAttachmentIds,
  getAttachmentPreviewUrl,
} from "@/lib/assistant-ui/attachment-store";
import type { FileItem } from "@/lib/types/chat-upload";

const toastWarning = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    warning: (...args: unknown[]) => toastWarning(...args),
  },
}));

const uploadMock = vi.fn();
beforeEach(() => {
  uploadMock.mockReset();
  toastWarning.mockReset();
});
afterEach(() => {
  vi.restoreAllMocks();
});

function fileItem(name: string, hash: string): FileItem {
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

describe("createChatAttachmentAdapter", () => {
  const adapter = () => createChatAttachmentAdapter({ caseId: 1, upload: uploadMock });

  it("add 成功: 返回 AUI-conformant complete attachment (type:'file', content:[])", async () => {
    uploadMock.mockResolvedValue({
      upload_batch_id: "b1",
      case_id: 1,
      entity_id: 0,
      entity_name: "",
      effective_entity_name: "",
      file_count: 1,
      duplicate_files: [],
      files: [fileItem("a.pdf", "h1")],
    });
    const a = adapter();
    const att = (await a.add({ file: new File(["x"], "a.pdf") })) as unknown as {
      id: string;
      type: string;
      name: string;
      content: unknown[];
      status: { type: string };
    };
    expect(att.status).toEqual({ type: "complete" });
    expect(att.type).toBe("file");
    expect(att.name).toBe("a.pdf");
    expect(att.content).toEqual([]);
  });

  it("add 成功: FileItem 存入模块级 store,以 attachment id 可取出", async () => {
    uploadMock.mockResolvedValue({
      upload_batch_id: "b1",
      case_id: 1,
      entity_id: 0,
      entity_name: "",
      effective_entity_name: "",
      file_count: 1,
      duplicate_files: [],
      files: [fileItem("a.pdf", "h1")],
    });
    const a = adapter();
    const att = (await a.add({ file: new File(["x"], "a.pdf") })) as unknown as { id: string };
    const fi = fileItem("a.pdf", "h1");
    const got = consumeFileItemsByAttachmentIds([att.id]);
    expect(got).toEqual([fi]);
  });

  it("add 失败: 返回 incomplete attachment 带 reason", async () => {
    uploadMock.mockRejectedValue(new Error("case_id 必填"));
    const a = adapter();
    const att = (await a.add({ file: new File(["x"], "a.pdf") })) as unknown as {
      status: { type: string; reason: string };
    };
    expect(att.status).toEqual({ type: "incomplete", reason: "case_id 必填" });
  });

  it("add 抛非 Error 对象时用默认文案", async () => {
    uploadMock.mockRejectedValue("plain string");
    const a = adapter();
    const att = (await a.add({ file: new File(["x"], "a.pdf") })) as unknown as {
      status: { type: string; reason: string };
    };
    expect(att.status).toEqual({ type: "incomplete", reason: "上传失败" });
  });

  it("重复文件: toast.warning 提示,且返回 incomplete", async () => {
    uploadMock.mockResolvedValue({
      upload_batch_id: "b1",
      case_id: 1,
      entity_id: 0,
      entity_name: "",
      effective_entity_name: "",
      file_count: 0,
      duplicate_files: ["a.pdf"],
      files: [],
    });
    const a = adapter();
    const att = (await a.add({ file: new File(["x"], "a.pdf") })) as unknown as {
      status: { type: string; reason: string };
    };
    expect(toastWarning).toHaveBeenCalledWith(expect.stringContaining("a.pdf"));
    expect(att.status).toEqual({ type: "incomplete", reason: "全部文件重复" });
  });

  it("accept 字段为 *", () => {
    expect(adapter().accept).toBe("*");
  });

  it("remove / send 留空实现:不抛错", async () => {
    const a = adapter();
    await expect(a.remove({} as never)).resolves.toBeUndefined();
    await expect(a.send({} as never)).resolves.toBeUndefined();
  });

  it("调用 upload 时 caseId 透传", async () => {
    uploadMock.mockResolvedValue({
      upload_batch_id: "b1",
      case_id: 99,
      entity_id: 0,
      entity_name: "",
      effective_entity_name: "",
      file_count: 0,
      duplicate_files: [],
      files: [],
    });
    const a = createChatAttachmentAdapter({ caseId: 99, upload: uploadMock });
    await a.add({ file: new File(["x"], "a.pdf") });
    expect(uploadMock).toHaveBeenCalledWith({ caseId: 99 }, expect.any(Array));
  });
});

describe("consumeFileItemsByAttachmentIds", () => {
  beforeEach(() => {
    uploadMock.mockReset();
  });

  it("不存在的 id 返回空数组", () => {
    expect(consumeFileItemsByAttachmentIds(["nope"])).toEqual([]);
  });

  it("多次调用同 id 第二次返回空(consume 语义)", async () => {
    uploadMock.mockResolvedValue({
      upload_batch_id: "b1",
      case_id: 1,
      entity_id: 0,
      entity_name: "",
      effective_entity_name: "",
      file_count: 1,
      duplicate_files: [],
      files: [fileItem("a.pdf", "h1")],
    });
    const a = createChatAttachmentAdapter({ caseId: 1, upload: uploadMock });
    const att = (await a.add({ file: new File(["x"], "a.pdf") })) as unknown as { id: string };
    const first = consumeFileItemsByAttachmentIds([att.id]);
    const second = consumeFileItemsByAttachmentIds([att.id]);
    expect(first).toHaveLength(1);
    expect(second).toEqual([]);
  });

  it("add 后通过 getAttachmentPreviewUrl 可拿到 FileItem.url", async () => {
    uploadMock.mockResolvedValue({
      upload_batch_id: "b1",
      case_id: 1,
      entity_id: 0,
      entity_name: "",
      effective_entity_name: "",
      file_count: 1,
      duplicate_files: [],
      files: [fileItem("img.png", "hu1")],
    });
    const a = createChatAttachmentAdapter({ caseId: 1, upload: uploadMock });
    const att = (await a.add({ file: new File(["x"], "img.png") })) as unknown as { id: string };
    expect(getAttachmentPreviewUrl(att.id)).toBe("s3://x/img.png");
  });

  it("primeFileItemsByAttachmentIds 同时填入 file 存储与预览 URL 缓存", () => {
    const fi = fileItem("primed.png", "hu2");
    primeFileItemsByAttachmentIds([["att-primed", fi]]);
    expect(getAttachmentPreviewUrl("att-primed")).toBe("s3://x/primed.png");
    expect(consumeFileItemsByAttachmentIds(["att-primed"])).toEqual([fi]);
    // FileItem 被 consume,但预览 URL 仍可读 (用于历史消息渲染)
    expect(getAttachmentPreviewUrl("att-primed")).toBe("s3://x/primed.png");
  });

  it("URL 原样保留,不做任何编码处理", () => {
    const fi: FileItem = {
      ...fileItem("img.png", "hu3"),
      url: "https://m.example.com/raw/Screenshot%25202026.png",
    };
    primeFileItemsByAttachmentIds([["att-raw", fi]]);
    expect(getAttachmentPreviewUrl("att-raw")).toBe(
      "https://m.example.com/raw/Screenshot%25202026.png"
    );
  });

  it("多 id 中只对存在的那些返回 FileItem,顺序按输入", async () => {
    uploadMock.mockResolvedValueOnce({
      upload_batch_id: "b1",
      case_id: 1,
      entity_id: 0,
      entity_name: "",
      effective_entity_name: "",
      file_count: 1,
      duplicate_files: [],
      files: [fileItem("a.pdf", "h1")],
    });
    uploadMock.mockResolvedValueOnce({
      upload_batch_id: "b1",
      case_id: 1,
      entity_id: 0,
      entity_name: "",
      effective_entity_name: "",
      file_count: 1,
      duplicate_files: [],
      files: [fileItem("b.pdf", "h2")],
    });
    const a = createChatAttachmentAdapter({ caseId: 1, upload: uploadMock });
    const att1 = (await a.add({ file: new File(["x"], "a.pdf") })) as unknown as { id: string };
    const att2 = (await a.add({ file: new File(["y"], "b.pdf") })) as unknown as { id: string };
    const got = consumeFileItemsByAttachmentIds(["missing", att2.id, att1.id]);
    expect(got.map((f) => f.file_hash)).toEqual(["h2", "h1"]);
  });
});

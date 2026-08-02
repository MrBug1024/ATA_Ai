import { describe, it, expect } from "vitest";
import {
  FileImage,
  FileText,
  FileSpreadsheet,
  FileVideo,
  FileAudio,
  FileArchive,
  FileCode,
  File,
} from "lucide-react";
import { getFileTypeInfo, resolvePreviewType } from "@/lib/utils/file-type";

describe("getFileTypeInfo", () => {
  it("按 mime 识别图片", () => {
    expect(getFileTypeInfo("x", "image/png").icon).toBe(FileImage);
  });
  it("按扩展名识别图片", () => {
    expect(getFileTypeInfo("photo.JPG").icon).toBe(FileImage);
  });
  it("识别 PDF", () => {
    expect(getFileTypeInfo("a.pdf").icon).toBe(FileText);
    expect(getFileTypeInfo("x", "application/pdf").icon).toBe(FileText);
  });
  it("识别 Word", () => {
    expect(getFileTypeInfo("合同.docx").color).toBe("text-blue-500");
  });
  it("识别表格", () => {
    expect(getFileTypeInfo("流水.xlsx").icon).toBe(FileSpreadsheet);
    expect(getFileTypeInfo("x.csv").icon).toBe(FileSpreadsheet);
  });
  it("识别视频/音频/压缩包/代码", () => {
    expect(getFileTypeInfo("v.mp4").icon).toBe(FileVideo);
    expect(getFileTypeInfo("a.mp3").icon).toBe(FileAudio);
    expect(getFileTypeInfo("z.zip").icon).toBe(FileArchive);
    expect(getFileTypeInfo("s.ts").icon).toBe(FileCode);
  });
  it("未知类型兜底", () => {
    expect(getFileTypeInfo("blob.bin").icon).toBe(File);
    expect(getFileTypeInfo().icon).toBe(File);
  });
});

describe("resolvePreviewType", () => {
  it("图片 → image", () => {
    expect(resolvePreviewType("p.png")).toBe("image");
    expect(resolvePreviewType("x", "image/webp")).toBe("image");
  });
  it("PDF → pdf", () => {
    expect(resolvePreviewType("a.pdf")).toBe("pdf");
    expect(resolvePreviewType("x", "application/pdf")).toBe("pdf");
  });
  it("文本/JSON → text", () => {
    expect(resolvePreviewType("x", "text/plain")).toBe("text");
    expect(resolvePreviewType("x", "application/json")).toBe("text");
  });
  it("常见文本扩展名(无 mime 或 mime 为 octet-stream)→ text", () => {
    expect(resolvePreviewType("readme.txt")).toBe("text");
    expect(resolvePreviewType("NOTES.md")).toBe("text");
    expect(resolvePreviewType("data.csv", "application/octet-stream")).toBe("text");
    expect(resolvePreviewType("app.log")).toBe("text");
    expect(resolvePreviewType("config.yaml")).toBe("text");
    expect(resolvePreviewType("script.py")).toBe("text");
    expect(resolvePreviewType("page.html")).toBe("text");
  });
  it("Office 文档 → none(下载降级)", () => {
    expect(resolvePreviewType("合同.docx")).toBe("none");
    expect(resolvePreviewType("流水.xlsx")).toBe("none");
  });
  it("其余 → none", () => {
    expect(resolvePreviewType("v.mp4", "video/mp4")).toBe("none");
    expect(resolvePreviewType("blob.bin")).toBe("none");
  });
});

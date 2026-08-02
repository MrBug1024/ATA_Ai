import {
  File,
  FileArchive,
  FileAudio,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileVideo,
} from "lucide-react";

export type FileTypeInfo = { icon: React.ElementType; color: string };

/** 文件名/MIME → 图标与颜色,聊天附件与预览面板共用。 */
export function getFileTypeInfo(name?: string, contentType?: string): FileTypeInfo {
  const mime = contentType ?? "";
  const ext = (name ?? "").split(".").pop()?.toLowerCase() ?? "";

  if (mime.startsWith("image/") || /^(png|jpe?g|gif|webp|svg|bmp|ico|tiff?)$/.test(ext))
    return { icon: FileImage, color: "text-violet-500" };

  if (mime === "application/pdf" || ext === "pdf")
    return { icon: FileText, color: "text-destructive" };

  if (/^(msword|vnd\.openxmlformats-officedocument\.wordprocessingml)/.test(mime) || /^docx?$/.test(ext))
    return { icon: FileText, color: "text-blue-500" };

  if (/spreadsheet|excel|vnd\.ms-excel/.test(mime) || /^(xlsx?|csv)$/.test(ext))
    return { icon: FileSpreadsheet, color: "text-emerald-500" };

  if (/presentation|powerpoint/.test(mime) || /^(pptx?|key)$/.test(ext))
    return { icon: FileText, color: "text-orange-500" };

  if (mime.startsWith("video/") || /^(mp4|mov|avi|mkv|webm)$/.test(ext))
    return { icon: FileVideo, color: "text-pink-500" };

  if (mime.startsWith("audio/") || /^(mp3|wav|ogg|flac|aac|m4a)$/.test(ext))
    return { icon: FileAudio, color: "text-teal-500" };

  if (/zip|tar|gz|rar|7z/.test(mime) || /^(zip|tar|gz|rar|7z|bz2)$/.test(ext))
    return { icon: FileArchive, color: "text-yellow-500" };

  if (mime.startsWith("text/") || /^(js|ts|jsx|tsx|py|go|rs|java|c|cpp|cs|php|rb|sh|json|yaml|toml|xml|html|css|md)$/.test(ext))
    return { icon: FileCode, color: "text-sky-500" };

  return { icon: File, color: "text-muted-foreground" };
}

export type PreviewType = "image" | "pdf" | "text" | "none";

/** 内嵌文本预览支持的扩展名(纯文本 / 标记 / 数据 / 代码)。 */
const TEXT_PREVIEW_EXTS =
  /^(txt|md|markdown|csv|tsv|log|json|yaml|yml|toml|ini|xml|html|css|js|jsx|ts|tsx|py|go|rs|java|c|cpp|cs|php|rb|sh|sql)$/;

/** 判断文件可用哪种内嵌预览(图片 / PDF / 纯文本),其余不支持。 */
export function resolvePreviewType(name: string, contentType?: string): PreviewType {
  const mime = contentType ?? "";
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (mime.startsWith("image/") || /^(png|jpe?g|gif|webp|svg|bmp)$/.test(ext)) return "image";
  if (mime === "application/pdf" || ext === "pdf") return "pdf";
  if (mime.startsWith("text/") || mime === "application/json" || TEXT_PREVIEW_EXTS.test(ext))
    return "text";
  return "none";
}

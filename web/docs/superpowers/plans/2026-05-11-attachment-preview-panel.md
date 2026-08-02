# Attachment Preview Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the centered Dialog attachment preview in chat with a right-side split panel, unify with the files page using a shared component, and render PDFs with `react-pdf` instead of iframe.

**Architecture:** A shared `FilePreviewPanel` component accepts a `PreviewableFile` interface. In chat, a `PreviewContext` lets `MessageAttachmentItem` trigger the panel without prop drilling; `AssistantChat` holds state and renders the panel in a flex-row split beside the chat thread. The files page adapts its `FileRecord` to `PreviewableFile` and drops its inline panel implementation.

**Tech Stack:** react-pdf v9.x, pdfjs-dist, React context, Tailwind CSS, Lucide icons

---

### Task 1: Install react-pdf

**Files:**
- Modify: `package.json` (via pnpm)

- [ ] **Step 1: Install the package**

```bash
cd /Users/ashark/Code/ai_hunter && pnpm add react-pdf
```

Expected output: packages added successfully, `react-pdf` and `pdfjs-dist` appear in `node_modules`.

- [ ] **Step 2: Verify install**

```bash
node -e "require('react-pdf'); console.log('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add package.json pnpm-lock.yaml
git commit -m "chore: add react-pdf dependency"
```

---

### Task 2: Create PreviewableFile interface and PreviewContext

**Files:**
- Create: `lib/assistant-ui/preview-context.ts`

- [ ] **Step 1: Write the file**

```ts
// lib/assistant-ui/preview-context.ts
"use client";

import { createContext, useContext } from "react";

export interface PreviewableFile {
  name: string;
  contentType?: string;
  previewUrl?: string;
  file?: File;
}

interface PreviewContextValue {
  previewFile: PreviewableFile | null;
  openPreview: (file: PreviewableFile) => void;
  closePreview: () => void;
}

export const PreviewContext = createContext<PreviewContextValue>({
  previewFile: null,
  openPreview: () => {},
  closePreview: () => {},
});

export function usePreview() {
  return useContext(PreviewContext);
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /Users/ashark/Code/ai_hunter && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add lib/assistant-ui/preview-context.ts
git commit -m "feat: add PreviewContext and PreviewableFile interface"
```

---

### Task 3: Create shared FilePreviewPanel component

**Files:**
- Create: `components/shared/file-preview-panel.tsx`

- [ ] **Step 1: Create the directory and write the component**

```bash
mkdir -p /Users/ashark/Code/ai_hunter/components/shared
```

```tsx
// components/shared/file-preview-panel.tsx
"use client";

import { useState, useEffect, useRef } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { X, Download, FileText, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import type { PreviewableFile } from "@/lib/assistant-ui/preview-context";

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

function resolvePreviewType(file: PreviewableFile): "image" | "pdf" | "text" | "none" {
  const mime = file.contentType ?? "";
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (mime.startsWith("image/") || /^(png|jpe?g|gif|webp|svg|bmp)$/.test(ext)) return "image";
  if (mime === "application/pdf" || ext === "pdf") return "pdf";
  if (mime.startsWith("text/") || mime === "application/json") return "text";
  return "none";
}

function PdfViewer({ url }: { url: string }) {
  const [numPages, setNumPages] = useState<number>(0);
  const [page, setPage] = useState(1);
  const [loadError, setLoadError] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(380);

  useEffect(() => {
    if (!containerRef.current) return;
    const obs = new ResizeObserver(([entry]) => {
      setWidth(Math.floor(entry.contentRect.width) - 32);
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  if (loadError) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
        <FileText className="size-8 text-muted-foreground/40" />
        <p className="text-sm text-muted-foreground/60">PDF 加载失败</p>
        <a
          href={url}
          download
          className="inline-flex items-center gap-1.5 rounded-md border border-border/50 px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
        >
          <Download className="size-3" /> 下载文件
        </a>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="flex flex-col items-center gap-2 p-4">
      <Document
        file={url}
        onLoadSuccess={({ numPages: n }) => { setNumPages(n); setPage(1); }}
        onLoadError={() => setLoadError(true)}
        loading={
          <div className="flex items-center gap-2 py-8 text-muted-foreground/50">
            <Loader2 className="size-4 animate-spin" />
            <span className="text-xs">加载中…</span>
          </div>
        }
      >
        <Page
          pageNumber={page}
          width={width}
          renderTextLayer
          renderAnnotationLayer
        />
      </Document>
      {numPages > 1 && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="flex size-6 items-center justify-center rounded hover:bg-accent disabled:opacity-30"
          >
            <ChevronLeft className="size-3.5" />
          </button>
          <span className="tabular-nums">{page} / {numPages}</span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(numPages, p + 1))}
            disabled={page >= numPages}
            className="flex size-6 items-center justify-center rounded hover:bg-accent disabled:opacity-30"
          >
            <ChevronRight className="size-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}

interface FilePreviewPanelProps {
  file: PreviewableFile;
  onClose: () => void;
}

export function FilePreviewPanel({ file, onClose }: FilePreviewPanelProps) {
  const type = resolvePreviewType(file);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [imgSrc, setImgSrc] = useState<string | null>(null);

  useEffect(() => {
    if (type !== "image") { setImgSrc(null); return; }
    if (file.previewUrl) { setImgSrc(file.previewUrl); return; }
    if (!file.file) { setImgSrc(null); return; }
    const url = URL.createObjectURL(file.file);
    setImgSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [file.previewUrl, file.file, type]);

  useEffect(() => {
    setTextContent(null);
    if (type === "text" && file.previewUrl) {
      fetch(file.previewUrl)
        .then((r) => r.text())
        .then(setTextContent)
        .catch(() => setTextContent("无法加载文件内容"));
    }
  }, [file.previewUrl, type]);

  return (
    <div className="flex h-full flex-col border-l border-border/50 bg-background">
      <div className="flex shrink-0 items-center gap-2 border-b border-border/40 px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">{file.name}</p>
          <p className="text-[10px] uppercase text-muted-foreground/50">{file.contentType ?? "未知格式"}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {file.previewUrl && (
            <a
              href={file.previewUrl}
              download={file.name}
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground/50 hover:bg-accent hover:text-foreground transition-colors"
              title="下载"
            >
              <Download className="size-3.5" />
            </a>
          )}
          <button
            type="button"
            onClick={onClose}
            className="flex size-7 items-center justify-center rounded-md text-muted-foreground/50 hover:bg-accent hover:text-foreground transition-colors"
            aria-label="关闭预览"
          >
            <X className="size-3.5" />
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {type === "image" && imgSrc && (
          <div className="flex items-center justify-center p-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={imgSrc}
              alt={file.name}
              className="max-h-full max-w-full rounded-lg object-contain"
            />
          </div>
        )}
        {type === "pdf" && file.previewUrl && (
          <PdfViewer url={file.previewUrl} />
        )}
        {type === "text" && (
          <pre className="p-4 text-xs leading-relaxed text-foreground/80 whitespace-pre-wrap break-words">
            {textContent ?? (
              <span className="flex items-center gap-2 text-muted-foreground/50">
                <Loader2 className="size-3 animate-spin" /> 加载中...
              </span>
            )}
          </pre>
        )}
        {(type === "none" || (type === "image" && !imgSrc) || (type === "pdf" && !file.previewUrl)) && (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
            <div className="flex size-12 items-center justify-center rounded-xl border border-border/40 bg-muted/40">
              <FileText className="size-5 text-muted-foreground/40" />
            </div>
            <p className="text-sm text-muted-foreground/60">不支持预览此格式</p>
            {file.previewUrl && (
              <a
                href={file.previewUrl}
                download={file.name}
                className="inline-flex items-center gap-1.5 rounded-md border border-border/50 px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              >
                <Download className="size-3" /> 下载文件
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /Users/ashark/Code/ai_hunter && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add components/shared/file-preview-panel.tsx
git commit -m "feat: add shared FilePreviewPanel component with react-pdf"
```

---

### Task 4: Update AssistantChat with PreviewContext provider and split layout

**Files:**
- Modify: `components/chat/assistant-chat.tsx`

- [ ] **Step 1: Replace the file contents**

```tsx
// components/chat/assistant-chat.tsx
"use client";

import { useState } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useDifyRuntime } from "@/lib/assistant-ui/use-dify-runtime";
import { ThinkingContext } from "@/lib/assistant-ui/thinking-context";
import { PreviewContext, type PreviewableFile } from "@/lib/assistant-ui/preview-context";
import { ChatThread } from "./chatgpt-thread";
import { FilePreviewPanel } from "@/components/shared/file-preview-panel";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";
import type { DifyAppType } from "@/lib/dify";

export interface SerializableMessage {
  id: string;
  conversationId: string;
  role: "user" | "assistant";
  content: string;
  difyMessageId: string | null;
  files: string[] | null;
  metadata: Record<string, unknown> | null;
  createdAt: string;
}

interface AssistantChatProps {
  conversationId: string;
  appType?: DifyAppType;
  initialMessages?: SerializableMessage[];
  title?: string;
}

export function AssistantChat({
  conversationId,
  appType = "audit",
  initialMessages,
  title,
}: AssistantChatProps) {
  const { runtime, thinkingMap } = useDifyRuntime(conversationId, appType, initialMessages);
  const [previewFile, setPreviewFile] = useState<PreviewableFile | null>(null);

  return (
    <PreviewContext.Provider
      value={{
        previewFile,
        openPreview: setPreviewFile,
        closePreview: () => setPreviewFile(null),
      }}
    >
      <AssistantRuntimeProvider runtime={runtime}>
        <ThinkingContext.Provider value={thinkingMap}>
          <div className="flex h-full flex-col">
            <header className="flex h-14 shrink-0 items-center gap-2 px-4">
              <SidebarTrigger className="size-9 shrink-0 text-muted-foreground hover:bg-accent hover:text-foreground" />
              {title && (
                <span className="min-w-0 truncate text-sm text-foreground/70">
                  {title}
                </span>
              )}
              <span className="ml-auto shrink-0 rounded-md border border-border/50 px-2 py-0.5 text-xs text-muted-foreground">
                {appType === "audit" ? "文档审计" : "信息提取"}
              </span>
            </header>

            <div className="flex min-h-0 flex-1">
              <div
                className={cn(
                  "min-w-0 overflow-hidden transition-all duration-200",
                  previewFile ? "w-[55%]" : "flex-1"
                )}
              >
                <ChatThread hasInitialMessages={!!initialMessages?.length} />
              </div>
              {previewFile && (
                <div className="w-[45%] shrink-0">
                  <FilePreviewPanel
                    file={previewFile}
                    onClose={() => setPreviewFile(null)}
                  />
                </div>
              )}
            </div>
          </div>
        </ThinkingContext.Provider>
      </AssistantRuntimeProvider>
    </PreviewContext.Provider>
  );
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /Users/ashark/Code/ai_hunter && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add components/chat/assistant-chat.tsx
git commit -m "feat: add split panel layout and PreviewContext to AssistantChat"
```

---

### Task 5: Update MessageAttachmentItem to use PreviewContext

**Files:**
- Modify: `components/assistant-ui/attachment.tsx`

- [ ] **Step 1: Add usePreview import at the top of the file**

After the existing imports, add:
```tsx
import { usePreview } from "@/lib/assistant-ui/preview-context";
```

Remove this import (no longer needed):
```tsx
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
```

- [ ] **Step 2: Replace the MessageAttachmentItem function (lines 238–319)**

```tsx
function MessageAttachmentItem({ attachment }: { attachment: AttachmentLike }) {
  const id = attachment.id;
  const cachedBlobUrl = id ? getCachedPreviewUrl(id) : undefined;
  const serverPreviewUrl = id ? `/api/files/preview/${id}` : undefined;
  const resolved: AttachmentLike = {
    ...attachment,
    previewUrl: cachedBlobUrl ?? serverPreviewUrl,
  };

  const imgSrc = useImagePreview(resolved);
  const { openPreview } = usePreview();
  const previewUrl = resolved.previewUrl;
  const fileName = attachment.name ?? "附件";
  const isPdf =
    attachment.contentType === "application/pdf" ||
    fileName.toLowerCase().endsWith(".pdf");

  if (imgSrc) {
    return (
      <button
        type="button"
        onClick={() =>
          openPreview({
            name: fileName,
            contentType: attachment.contentType,
            previewUrl: imgSrc,
          })
        }
        className="size-36 shrink-0 overflow-hidden rounded-xl border border-border bg-muted focus:outline-none focus:ring-2 focus:ring-ring"
        aria-label={`预览图片: ${fileName}`}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={imgSrc}
          alt={fileName}
          className="size-full object-cover transition-opacity hover:opacity-90"
        />
      </button>
    );
  }

  const { icon: Icon, color } = getFileTypeInfo(attachment.name, attachment.contentType);

  if (isPdf && previewUrl) {
    return (
      <button
        type="button"
        onClick={() =>
          openPreview({
            name: fileName,
            contentType: attachment.contentType,
            previewUrl,
          })
        }
        className="flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
      >
        <Icon className={cn("size-3 shrink-0", color)} />
        <span className="max-w-[150px] truncate">{fileName}</span>
      </button>
    );
  }

  return (
    <a
      href={previewUrl}
      target="_blank"
      rel="noreferrer"
      className="flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
    >
      <Icon className={cn("size-3 shrink-0", color)} />
      <span className="max-w-[150px] truncate">{fileName}</span>
    </a>
  );
}
```

- [ ] **Step 3: Verify TypeScript**

```bash
cd /Users/ashark/Code/ai_hunter && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add components/assistant-ui/attachment.tsx
git commit -m "feat: replace Dialog with PreviewContext in MessageAttachmentItem"
```

---

### Task 6: Update files/page.tsx to use shared FilePreviewPanel

**Files:**
- Modify: `app/(main)/files/page.tsx`

- [ ] **Step 1: Replace the lucide import and add FilePreviewPanel import**

Replace:
```tsx
import {
  FileText, Loader2, File, MessageSquare, X, Download,
} from "lucide-react";
```
With:
```tsx
import {
  FileText, Loader2, File, MessageSquare,
} from "lucide-react";
import { FilePreviewPanel } from "@/components/shared/file-preview-panel";
```

- [ ] **Step 2: Remove the inline getPreviewType function and FilePreviewPanel component**

Delete lines 26–132 in the file (the `getPreviewType` function and the entire inline `FilePreviewPanel` component).

- [ ] **Step 3: Replace the preview panel usage in FilesPage**

Find this block near the bottom of `FilesPage`:
```tsx
{selectedFile && (
  <div className="w-[45%] shrink-0">
    <FilePreviewPanel file={selectedFile} onClose={() => setSelectedFileId(null)} />
  </div>
)}
```

Replace with:
```tsx
{selectedFile && (
  <div className="w-[45%] shrink-0">
    <FilePreviewPanel
      file={{
        name: selectedFile.originalName,
        contentType: selectedFile.mimeType ?? undefined,
        previewUrl: selectedFile.difyFileId
          ? `/api/files/preview/${selectedFile.difyFileId}`
          : undefined,
      }}
      onClose={() => setSelectedFileId(null)}
    />
  </div>
)}
```

- [ ] **Step 4: Verify TypeScript**

```bash
cd /Users/ashark/Code/ai_hunter && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add app/(main)/files/page.tsx
git commit -m "feat: use shared FilePreviewPanel in files page"
```

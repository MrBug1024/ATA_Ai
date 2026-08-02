# 附件右侧预览面板设计文档

**日期**: 2026-05-11  
**状态**: 已实现(2026-06-10,components/shared/preview-host.tsx;文件管理页与 CDN worker 两点按现状调整:无 files 页,workerSrc 用本地 /pdf.worker.min.mjs)

---

## 背景

当前聊天中已发送消息的附件（图片、PDF）点击后弹出居中 Dialog，PDF 渲染使用 iframe（Chrome 内置 PDF 查看器）。文件管理页的预览面板也用 iframe 渲染 PDF。

目标：统一两处体验，改为右侧分栏预览，PDF 改用 `react-pdf` 渲染。

---

## 需求

1. 聊天中已发送消息的附件点击后打开右侧分栏预览（替换现有 Dialog）
2. 文件管理页的预览面板使用相同组件
3. PDF 使用 `react-pdf` 渲染，不使用 iframe / Chrome 内置查看器
4. 预览面板打开时，左侧内容区平滑收窄（分栏推开式，非覆盖式）

---

## 架构

### 共享数据接口

```ts
interface PreviewableFile {
  name: string;
  contentType?: string;
  previewUrl?: string;   // 服务端 URL 或 blob URL
  file?: File;           // 本地 File 对象（新上传图片时使用）
}
```

### 共享预览面板组件

`components/shared/file-preview-panel.tsx`

- 接受 `PreviewableFile` + `onClose` 回调
- 根据 `contentType` / 文件名后缀判断预览类型：
  - `image/*` → `<img>`，居中展示
  - `application/pdf` → `<react-pdf Document + Page>`，含上下翻页、页码
  - `text/*` / `application/json` → `<pre>` 文本
  - 其他 → 下载链接
- PDF.js worker 通过 CDN URL 配置（无需修改 webpack）
- 头部：文件名、MIME 类型、下载按钮、关闭按钮

### 聊天侧 PreviewContext

`lib/assistant-ui/preview-context.ts`

```ts
interface PreviewContextValue {
  previewFile: PreviewableFile | null;
  openPreview: (file: PreviewableFile) => void;
  closePreview: () => void;
}
```

- Context 默认值为 noop（安全降级）
- Provider 放在 `AssistantChat` 组件内

### 布局变更（`AssistantChat`）

```
AssistantChat (flex flex-col h-full)
 ├─ Header (shrink-0)
 └─ 内容区 (flex flex-row min-h-0 flex-1)
     ├─ 聊天区 (transition-all, previewFile ? "w-[55%]" : "flex-1")
     │   └─ ChatThread
     └─ 预览区 (w-[45%] shrink-0, 无 previewFile 时隐藏)
         └─ FilePreviewPanel (共享组件)
```

### 附件组件变更（`MessageAttachmentItem`）

- 移除 `useState(false)` 和 `Dialog` 导入
- 图片和 PDF 的按钮 `onClick` 改为调用 `useContext(PreviewContext).openPreview`
- 其他格式（下载链接）保持不变

### 文件页变更（`files/page.tsx`）

- 删除内联 `FilePreviewPanel` 函数
- 引入 `components/shared/file-preview-panel.tsx`
- 将 `FileRecord` 适配为 `PreviewableFile`：
  ```ts
  const previewable: PreviewableFile = {
    name: file.originalName,
    contentType: file.mimeType ?? undefined,
    previewUrl: file.difyFileId ? `/api/files/preview/${file.difyFileId}` : undefined,
  };
  ```

---

## 文件清单

| 操作 | 路径 |
|------|------|
| 新建 | `lib/assistant-ui/preview-context.ts` |
| 新建 | `components/shared/file-preview-panel.tsx` |
| 修改 | `components/chat/assistant-chat.tsx` |
| 修改 | `components/assistant-ui/attachment.tsx` |
| 修改 | `app/(main)/files/page.tsx` |

---

## 依赖

- 新增：`react-pdf`（`pdfjs-dist` peer dep）
- PDF.js worker 配置：
  ```ts
  import { pdfjs } from 'react-pdf';
  pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;
  ```

---

## 错误处理

- PDF 加载失败：显示错误提示 + 下载链接降级
- 图片加载失败：显示文件图标
- 预览 URL 不存在：显示"暂无预览"+ 文件名

---

## 不在范围内

- 输入框待发附件（Composer）的预览
- PDF 缩放、搜索等高级功能
- 移动端响应式适配

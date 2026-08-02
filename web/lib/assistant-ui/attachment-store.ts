import type { FileItem } from "@/lib/types/chat-upload";

/**
 * 附件生命周期的单一事实来源(模块级,跨路由存活)。
 *
 * 每个 attachment id 对应一个条目:
 * - `fileItem`:待发送的上传结果,被 `consumeFileItemsByAttachmentIds` 一次性取走
 *   (发送后不应重复携带);
 * - `previewUrl`:渲染缩略图用,consume 之后仍保留——历史消息与已发送消息的
 *   `MessageAttachmentItem` 依赖它。
 */
interface AttachmentEntry {
  fileItem?: FileItem;
  previewUrl?: string;
}

const store = new Map<string, AttachmentEntry>();

/** 登记一个已上传文件(adapter add / 跨路由 prime 共用)。 */
export function stageFileItem(id: string, fi: FileItem): void {
  const entry = store.get(id) ?? {};
  store.set(id, { fileItem: fi, previewUrl: fi.url || entry.previewUrl });
}

/** 取走待发送的 FileItem(consume 语义);previewUrl 保留供渲染。 */
export function consumeFileItemsByAttachmentIds(ids: readonly string[]): FileItem[] {
  const out: FileItem[] = [];
  for (const id of ids) {
    const entry = store.get(id);
    if (entry?.fileItem) {
      out.push(entry.fileItem);
      if (entry.previewUrl) {
        store.set(id, { previewUrl: entry.previewUrl });
      } else {
        store.delete(id);
      }
    }
  }
  return out;
}

/**
 * 批量预填 FileItem。用于 /chat 新会话页暂存的附件在跳转进会话路由后重新水合,
 * 让路由页的 handleSend 像普通 adapter 附件一样 consume。
 */
export function primeFileItemsByAttachmentIds(
  entries: ReadonlyArray<readonly [string, FileItem]>
): void {
  for (const [id, fi] of entries) stageFileItem(id, fi);
}

/**
 * 只预填预览 URL(id → url)。用于持久化会话的历史附件:刷新后内存里没有
 * FileItem,缩略图渲染只依赖这些缓存 URL。
 */
export function seedPreviewUrls(entries: ReadonlyArray<{ id: string; url: string }>): void {
  for (const { id, url } of entries) {
    if (!url) continue;
    const entry = store.get(id) ?? {};
    store.set(id, { ...entry, previewUrl: url });
  }
}

/** 读取附件的预览 URL(若有)。 */
export function getAttachmentPreviewUrl(id: string): string | undefined {
  return store.get(id)?.previewUrl;
}

/** 清空全部状态(测试用)。 */
export function resetAttachmentStore(): void {
  store.clear();
}

import { toast } from "sonner";
import type { AttachmentAdapter } from "@assistant-ui/react";
import type {
  ChatUploadRequest,
  ChatUploadResponse,
} from "@/lib/types/chat-upload";
import { stageFileItem } from "./attachment-store";

export interface ChatAttachmentAdapterDeps {
  caseId: number;
  upload: (req: ChatUploadRequest, files: File[]) => Promise<ChatUploadResponse>;
}

export function createChatAttachmentAdapter(deps: ChatAttachmentAdapterDeps): AttachmentAdapter {
  return {
    accept: "*",
    async add({ file }: { file: File }) {
      const id = crypto.randomUUID();
      try {
        const res = await deps.upload({ caseId: deps.caseId }, [file]);
        if (res.duplicate_files.length > 0) {
          toast.warning(`本批重复文件已忽略: ${res.duplicate_files.join(", ")}`);
        }
        const fileItems = res.files.filter((f) => !res.duplicate_files.includes(f.name));
        if (fileItems.length === 0) {
          return {
            id,
            type: "file",
            name: file.name,
            contentType: file.type,
            file,
            content: [],
            status: { type: "incomplete", reason: "全部文件重复" },
          } as unknown as never;
        }
        const fi = fileItems[0];
        const attachmentId = `${id}-${fi.file_hash}`;
        stageFileItem(attachmentId, fi);
        return {
          id: attachmentId,
          type: "file",
          name: fi.name,
          contentType: fi.content_type,
          file,
          content: [],
          status: { type: "complete" },
        } as unknown as never;
      } catch (err) {
        const reason = err instanceof Error ? err.message : "上传失败";
        return {
          id,
          type: "file",
          name: file.name,
          contentType: file.type,
          file,
          content: [],
          status: { type: "incomplete", reason },
        } as unknown as never;
      }
    },
    async remove() {},
    async send() {},
  } as unknown as AttachmentAdapter;
}

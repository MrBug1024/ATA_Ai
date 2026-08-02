"use client";

import { useCallback } from "react";
import { uploadChatFiles } from "@/lib/backend/langgraph";
import type { ChatUploadRequest, ChatUploadResponse } from "@/lib/types/chat-upload";

export function useChatUpload() {
  const upload = useCallback(
    (req: ChatUploadRequest, files: File[]): Promise<ChatUploadResponse> =>
      uploadChatFiles(req, files),
    []
  );

  return { upload };
}

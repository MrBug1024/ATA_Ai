"use client";

import { useCallback } from "react";
import type { UploadAndIngestResponse } from "@/lib/types/doc-categories";
import { uploadAndIngest, type UploadIngestRequest } from "@/lib/backend/langgraph";

export function useUploadIngest() {
  const upload = useCallback(
    (req: UploadIngestRequest): Promise<UploadAndIngestResponse> => uploadAndIngest(req),
    []
  );

  return { upload };
}

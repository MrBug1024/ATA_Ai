"use client";

import { mutate } from "swr";
import {
  materialEventKey,
  retryUploadBatch,
  uploadBatchKey,
} from "@/lib/backend/langgraph";
import type { UploadRetryResponse, UploadRetryStage } from "@/lib/types/doc-categories";
import { useBackendMutation } from "./use-backend-mutation";

export function useRetryUploadBatch(batchId: string) {
  const { data, isMutating, error, trigger, reset } = useBackendMutation(
    async (stage: UploadRetryStage): Promise<UploadRetryResponse> => {
      const result = await retryUploadBatch(batchId, stage);
      const keys = [uploadBatchKey(batchId)];
      if (result.material_event_id) keys.push(materialEventKey(result.material_event_id));
      void Promise.all(keys.map((key) => mutate(key))).catch(() => undefined);
      return result;
    }
  );

  return { data, isMutating, error, retry: trigger, reset };
}

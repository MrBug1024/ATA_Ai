"use client";

import useSWR from "swr";
import type { UploadBatchDetail } from "@/lib/types/doc-categories";
import { uploadBatchKey, getUploadBatch } from "@/lib/backend/langgraph";

export function useUploadBatch(batchId: string | null, refreshInterval = 0) {
  const { data, error, isLoading, mutate } = useSWR<UploadBatchDetail>(
    batchId !== null ? uploadBatchKey(batchId) : null,
    () => getUploadBatch(batchId as string),
    { refreshInterval }
  );

  return {
    batch: data ?? null,
    isLoading,
    error: error ? (error instanceof Error ? error.message : "Unknown error") : null,
    refresh: mutate,
  };
}

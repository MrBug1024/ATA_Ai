"use client";

import useSWR from "swr";
import type { CaseUploadBatchItem } from "@/lib/types/doc-categories";
import { caseUploadBatchesKey, listCaseUploadBatches } from "@/lib/backend/langgraph";

export function useCaseUploadBatches(caseId: number | null) {
  const { data, error, isLoading, mutate } = useSWR<CaseUploadBatchItem[]>(
    caseId !== null ? caseUploadBatchesKey(caseId) : null,
    () => listCaseUploadBatches(caseId as number)
  );

  return {
    batches: data ?? [],
    isLoading,
    error: error ? (error instanceof Error ? error.message : "Unknown error") : null,
    refresh: mutate,
  };
}

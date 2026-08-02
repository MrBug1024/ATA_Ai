"use client";

import useSWR from "swr";
import type { ProgressBoard } from "@/lib/types/case-analytics";
import { caseProgressKey, getCaseProgress } from "@/lib/backend/langgraph";

export function useCaseProgress(caseId: number | null) {
  const key = caseId !== null ? caseProgressKey(caseId) : null;

  const { data, error, isLoading, mutate } = useSWR<ProgressBoard>(key, () =>
    getCaseProgress(caseId as number)
  );

  return {
    progress: data ?? null,
    isLoading,
    error: error instanceof Error ? error.message : null,
    refresh: mutate,
  };
}

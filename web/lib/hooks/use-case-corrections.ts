"use client";

import useSWR from "swr";
import type { CorrectionModel } from "@/lib/types/audit-corrections";
import { caseCorrectionsKey, listCaseCorrections } from "@/lib/backend/langgraph";

export function useCaseCorrections(caseId: number | null, includeHistory = false) {
  const { data, error, isLoading, mutate } = useSWR<CorrectionModel[]>(
    caseId !== null ? caseCorrectionsKey(caseId, includeHistory) : null,
    () => listCaseCorrections(caseId as number, includeHistory)
  );

  return {
    corrections: data ?? [],
    isLoading,
    error: error ? (error instanceof Error ? error.message : "Unknown error") : null,
    refresh: mutate,
  };
}

"use client";

import useSWR from "swr";
import type { RecoveryRecord } from "@/lib/types/case-analytics";
import { caseRecoveryKey, listCaseRecovery } from "@/lib/backend/langgraph";

export function useCaseRecovery(caseId: number | null) {
  const key = caseId !== null ? caseRecoveryKey(caseId) : null;

  const { data, error, isLoading, mutate } = useSWR<RecoveryRecord[]>(key, () =>
    listCaseRecovery(caseId as number)
  );

  return {
    records: data ?? [],
    isLoading,
    error: error instanceof Error ? error.message : null,
    refresh: mutate,
  };
}

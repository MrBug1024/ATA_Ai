"use client";

import useSWR from "swr";
import type { DeadlineBoardResponse } from "@/lib/types/case-analytics";
import { caseDeadlineBoardKey, getCaseDeadlineBoard } from "@/lib/backend/langgraph";

export function useCaseDeadlineBoard(caseId: number | null) {
  const { data, error, isLoading, mutate } = useSWR<DeadlineBoardResponse>(
    caseId !== null ? caseDeadlineBoardKey(caseId) : null,
    () => getCaseDeadlineBoard(caseId as number)
  );

  return {
    board: data ?? null,
    isLoading,
    error: error ? (error instanceof Error ? error.message : "Unknown error") : null,
    refresh: mutate,
  };
}

"use client";

import useSWR from "swr";
import type { CaseMaterialEventItem } from "@/lib/types/doc-categories";
import { caseMaterialEventsKey, listCaseMaterialEvents } from "@/lib/backend/langgraph";

export function useCaseMaterialEvents(caseId: number | null) {
  const { data, error, isLoading, mutate } = useSWR<CaseMaterialEventItem[]>(
    caseId !== null ? caseMaterialEventsKey(caseId) : null,
    () => listCaseMaterialEvents(caseId as number)
  );

  return {
    events: data ?? [],
    isLoading,
    error: error ? (error instanceof Error ? error.message : "Unknown error") : null,
    refresh: mutate,
  };
}

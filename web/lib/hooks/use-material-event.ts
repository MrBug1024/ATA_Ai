"use client";

import useSWR from "swr";
import type { MaterialEventDetail } from "@/lib/types/doc-categories";
import { materialEventKey, getMaterialEvent } from "@/lib/backend/langgraph";

export function useMaterialEvent(eventId: string | null, refreshInterval = 0) {
  const { data, error, isLoading, mutate } = useSWR<MaterialEventDetail>(
    eventId !== null ? materialEventKey(eventId) : null,
    () => getMaterialEvent(eventId as string),
    { refreshInterval }
  );

  return {
    event: data ?? null,
    isLoading,
    error: error ? (error instanceof Error ? error.message : "Unknown error") : null,
    refresh: mutate,
  };
}

"use client";

import useSWR from "swr";
import type { GraphEntityItem } from "@/lib/types/knowledge-graph";
import { graphEntitiesKey, listGraphEntities } from "@/lib/backend/langgraph";

export function useGraphEntities(caseId: number | null) {
  const key = caseId !== null ? graphEntitiesKey(caseId) : null;
  const { data, error, isLoading } = useSWR<GraphEntityItem[]>(key, () =>
    listGraphEntities(caseId as number)
  );

  return {
    entities: data ?? [],
    isLoading,
    error: error instanceof Error ? error.message : null,
  };
}

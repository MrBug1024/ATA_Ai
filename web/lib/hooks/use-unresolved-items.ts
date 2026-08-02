"use client";

import useSWR from "swr";
import type { UnresolvedItemsResponse } from "@/lib/types/knowledge-graph";
import { unresolvedItemsKey, getUnresolvedItems } from "@/lib/backend/langgraph";

export function useUnresolvedItems(
  caseId: number | null,
  status: "pending" | "resolved" | "" = "pending",
  limit = 50
) {
  const key = caseId !== null ? unresolvedItemsKey(caseId, status, limit) : null;

  const { data, error, isLoading, mutate } = useSWR<UnresolvedItemsResponse>(key, () =>
    getUnresolvedItems(caseId as number, status, limit)
  );

  return {
    data: data ?? null,
    isLoading,
    error: error instanceof Error ? error.message : null,
    refresh: mutate,
  };
}

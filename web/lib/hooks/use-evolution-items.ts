"use client";

import useSWR from "swr";
import type { EvolutionItem } from "@/lib/types/knowledge-graph";
import { evolutionItemsKey, listEvolutionItems } from "@/lib/backend/langgraph";

export function useEvolutionItems(
  caseId: number | null,
  action?: "ADD" | "OVERRIDE",
  limit = 50
) {
  const key = caseId !== null ? evolutionItemsKey(caseId, action, limit) : null;

  const { data, error, isLoading, mutate } = useSWR<EvolutionItem[]>(key, () =>
    listEvolutionItems(caseId as number, action, limit)
  );

  return {
    items: data ?? [],
    isLoading,
    error: error instanceof Error ? error.message : null,
    refresh: mutate,
  };
}

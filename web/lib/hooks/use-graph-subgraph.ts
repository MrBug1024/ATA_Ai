"use client";

import { fetchSubgraph } from "@/lib/backend/langgraph";
import { useBackendMutation } from "./use-backend-mutation";

export function useGraphSubgraph() {
  const { data, isMutating, error, trigger, reset } = useBackendMutation(fetchSubgraph);
  return { data, isMutating, error, fetch: trigger, reset };
}

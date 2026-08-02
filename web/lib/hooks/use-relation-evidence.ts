"use client";

import { fetchRelationEvidence } from "@/lib/backend/langgraph";
import { useBackendMutation } from "./use-backend-mutation";

export function useRelationEvidence() {
  const { data, isMutating, error, trigger, reset } = useBackendMutation(fetchRelationEvidence);
  return { data, isMutating, error, fetch: trigger, reset };
}

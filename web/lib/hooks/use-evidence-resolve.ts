"use client";

import { resolveEvidence } from "@/lib/backend/langgraph";
import { useBackendMutation } from "./use-backend-mutation";

export function useEvidenceResolve() {
  const { data, isMutating, error, trigger, reset } = useBackendMutation(resolveEvidence);
  return { data, isMutating, error, resolve: trigger, reset };
}

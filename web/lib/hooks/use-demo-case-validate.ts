"use client";

import { validateDemoCaseTrace } from "@/lib/backend/langgraph";
import { useBackendMutation } from "./use-backend-mutation";

export function useDemoCaseValidate() {
  const { data, isMutating, error, trigger, reset } = useBackendMutation(validateDemoCaseTrace);
  return { data, isMutating, error, validate: trigger, reset };
}

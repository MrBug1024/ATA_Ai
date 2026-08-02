"use client";

import { mutate } from "swr";
import { caseProgressKey, updateCaseProgress } from "@/lib/backend/langgraph";
import type { UpdateProgressRequest } from "@/lib/types/case-analytics";
import { useBackendMutation } from "./use-backend-mutation";

export function useUpdateProgress(caseId: number) {
  const { data, isMutating, error, trigger, reset } = useBackendMutation(
    async (req: UpdateProgressRequest) => {
      await updateCaseProgress(caseId, req);
      await mutate(caseProgressKey(caseId));
    }
  );
  return { data, isMutating, error, update: trigger, reset };
}

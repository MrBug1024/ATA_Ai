"use client";

import { mutate } from "swr";
import { caseCorrectionsKey, revokeCorrection } from "@/lib/backend/langgraph";
import type { CorrectionModel } from "@/lib/types/case-analytics";
import { useBackendMutation } from "./use-backend-mutation";

export function useRevokeCorrection(caseId: number) {
  const { data, isMutating, error, trigger, reset } = useBackendMutation(
    async (correctionId: number): Promise<CorrectionModel> => {
      const result = await revokeCorrection(caseId, correctionId);
      void Promise.all([
        mutate(caseCorrectionsKey(caseId)),
        mutate(caseCorrectionsKey(caseId, true)),
      ]).catch(() => undefined);
      return result;
    }
  );

  return { data, isMutating, error, revoke: trigger, reset };
}

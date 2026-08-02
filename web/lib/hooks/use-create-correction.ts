"use client";

import { mutate } from "swr";
import { caseCorrectionsKey, createCorrection } from "@/lib/backend/langgraph";
import type { CorrectionCreateRequest, CorrectionModel } from "@/lib/types/case-analytics";
import { useBackendMutation } from "./use-backend-mutation";

export function useCreateCorrection(caseId: number) {
  const { data, isMutating, error, trigger, reset } = useBackendMutation(
    async (req: CorrectionCreateRequest): Promise<CorrectionModel> => {
      const result = await createCorrection(caseId, req);
      void Promise.all([
        mutate(caseCorrectionsKey(caseId)),
        mutate(caseCorrectionsKey(caseId, true)),
      ]).catch(() => undefined);
      return result;
    }
  );

  return { data, isMutating, error, create: trigger, reset };
}

"use client";

import { mutate } from "swr";
import {
  caseRecoveryKey,
  caseProgressKey,
  createRecovery,
} from "@/lib/backend/langgraph";
import type { CreateRecoveryRequest, RecoveryRecord } from "@/lib/types/case-analytics";
import { useBackendMutation } from "./use-backend-mutation";

export function useCreateRecovery(caseId: number) {
  const { data, isMutating, error, trigger, reset } = useBackendMutation(
    async (req: CreateRecoveryRequest): Promise<RecoveryRecord> => {
      const rec = await createRecovery(caseId, req);
      await Promise.all([
        mutate(caseRecoveryKey(caseId)),
        mutate(caseProgressKey(caseId)),
      ]);
      return rec;
    }
  );
  return { data, isMutating, error, create: trigger, reset };
}

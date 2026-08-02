"use client";

import { mutate } from "swr";
import {
  caseRecoveryKey,
  caseProgressKey,
  confirmRecovery,
} from "@/lib/backend/langgraph";
import type { RecoveryRecord } from "@/lib/types/case-analytics";
import { useBackendMutation } from "./use-backend-mutation";

export function useConfirmRecovery(caseId: number) {
  const { data, isMutating, error, trigger, reset } = useBackendMutation(
    async (recordId: number): Promise<RecoveryRecord> => {
      const rec = await confirmRecovery(caseId, recordId);
      await Promise.all([
        mutate(caseRecoveryKey(caseId)),
        mutate(caseProgressKey(caseId)),
      ]);
      return rec;
    }
  );
  return { data, isMutating, error, confirm: trigger, reset };
}

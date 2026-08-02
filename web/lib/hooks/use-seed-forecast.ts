"use client";

import { mutate } from "swr";
import {
  caseForecastKey,
  caseProgressKey,
  seedCaseForecast,
} from "@/lib/backend/langgraph";
import type { ForecastSeedRequest } from "@/lib/types/case-analytics";
import { useBackendMutation } from "./use-backend-mutation";

export function useSeedForecast(caseId: number) {
  const { data, isMutating, error, trigger, reset } = useBackendMutation(
    async (req: ForecastSeedRequest) => {
      await seedCaseForecast(caseId, req);
      await Promise.all([
        mutate(caseForecastKey(caseId)),
        mutate(caseProgressKey(caseId)),
      ]);
    }
  );
  return { data, isMutating, error, seed: trigger, reset };
}

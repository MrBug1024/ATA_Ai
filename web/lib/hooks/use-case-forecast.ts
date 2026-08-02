"use client";

import useSWR from "swr";
import type { ForecastItem } from "@/lib/types/case-analytics";
import { caseForecastKey, listCaseForecasts } from "@/lib/backend/langgraph";

export function useCaseForecast(caseId: number | null) {
  const key = caseId !== null ? caseForecastKey(caseId) : null;

  const { data, error, isLoading, mutate } = useSWR<ForecastItem[]>(key, () =>
    listCaseForecasts(caseId as number)
  );

  return {
    forecasts: data ?? [],
    isLoading,
    error: error instanceof Error ? error.message : null,
    refresh: mutate,
  };
}

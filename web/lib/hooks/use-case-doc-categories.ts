"use client";

import useSWR from "swr";
import type { CaseDocCategoriesResp } from "@/lib/types/doc-categories";
import { caseDocCategoriesKey, getCaseDocCategories } from "@/lib/backend/cases";

export function useCaseDocCategories(caseId: number | null) {
  const { data, error, isLoading, mutate } = useSWR<CaseDocCategoriesResp>(
    caseId !== null ? caseDocCategoriesKey(caseId) : null,
    () => getCaseDocCategories(caseId as number)
  );
  return {
    caseDocCategories: data,
    isLoading,
    error,
    refresh: mutate,
  };
}

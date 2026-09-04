"use client";

import useSWR from "swr";
import {
  annualAuditEvidenceCandidatesKey,
  getAnnualAuditEvidenceCandidates,
  type AnnualAuditEvidenceCandidateResponse,
} from "@/lib/backend/annual-audit";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "获取项目证据候选失败";
}

export function useAnnualAuditEvidenceCandidates(
  caseId: number | null,
  query = "",
  limit = 100
) {
  const normalizedQuery = query.trim();
  const { data, error, isLoading, isValidating, mutate } =
    useSWR<AnnualAuditEvidenceCandidateResponse>(
      caseId === null
        ? null
        : annualAuditEvidenceCandidatesKey(caseId, normalizedQuery, limit),
      () => getAnnualAuditEvidenceCandidates(caseId as number, normalizedQuery, limit),
      { keepPreviousData: true }
    );

  return {
    candidates: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    isValidating,
    error: error ? errorMessage(error) : null,
    refresh: mutate,
  };
}

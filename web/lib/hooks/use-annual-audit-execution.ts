"use client";

import { useCallback, useState } from "react";
import useSWR from "swr";
import {
  annualAuditExecutionKey,
  evaluateAnnualAuditReleaseGate,
  freezeAnnualAuditPolicyBinding,
  getAnnualAuditExecution,
  recordAnnualAuditReview,
  updateAnnualAuditProfile,
  updateAnnualAuditProgramItem,
  type AnnualAuditExecutionSnapshot,
  type AnnualAuditPolicyBindingRequest,
  type AnnualAuditProgramItemUpdate,
  type AnnualAuditReviewDecisionRequest,
  type AnnualEngagementProfileUpdate,
} from "@/lib/backend/annual-audit";

export type AnnualAuditMutationName =
  | "profile"
  | "program"
  | "review"
  | "policy"
  | "release_gate"
  | null;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败";
}

export function useAnnualAuditExecution(caseId: number | null) {
  const { data, error, isLoading, mutate } = useSWR<AnnualAuditExecutionSnapshot>(
    caseId !== null ? annualAuditExecutionKey(caseId) : null,
    () => getAnnualAuditExecution(caseId as number)
  );
  const [mutationName, setMutationName] = useState<AnnualAuditMutationName>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);

  const run = useCallback(
    async <T,>(name: Exclude<AnnualAuditMutationName, null>, action: () => Promise<T>): Promise<T> => {
      setMutationName(name);
      setMutationError(null);
      try {
        const result = await action();
        // A successful governed write must not be reported as failed merely
        // because the follow-up snapshot request is temporarily unavailable.
        void Promise.resolve(mutate()).catch(() => undefined);
        return result;
      } catch (mutationFailure) {
        setMutationError(errorMessage(mutationFailure));
        throw mutationFailure;
      } finally {
        setMutationName(null);
      }
    },
    [mutate]
  );

  const saveProfile = useCallback(
    (payload: AnnualEngagementProfileUpdate) => {
      if (caseId === null) return Promise.reject(new Error("缺少项目编号"));
      return run("profile", () => updateAnnualAuditProfile(caseId, payload));
    },
    [caseId, run]
  );

  const saveProgramItem = useCallback(
    (procedureCode: string, payload: AnnualAuditProgramItemUpdate) => {
      if (caseId === null) return Promise.reject(new Error("缺少项目编号"));
      return run("program", () => updateAnnualAuditProgramItem(caseId, procedureCode, payload));
    },
    [caseId, run]
  );

  const saveReview = useCallback(
    (payload: AnnualAuditReviewDecisionRequest) => {
      if (caseId === null) return Promise.reject(new Error("缺少项目编号"));
      return run("review", () => recordAnnualAuditReview(caseId, payload));
    },
    [caseId, run]
  );

  const freezePolicyBinding = useCallback(
    (payload: AnnualAuditPolicyBindingRequest) => {
      if (caseId === null) return Promise.reject(new Error("缺少项目编号"));
      return run("policy", () => freezeAnnualAuditPolicyBinding(caseId, payload));
    },
    [caseId, run]
  );

  const evaluateReleaseGate = useCallback(() => {
    if (caseId === null) return Promise.reject(new Error("缺少项目编号"));
    return run("release_gate", () => evaluateAnnualAuditReleaseGate(caseId));
  }, [caseId, run]);

  return {
    execution: data ?? null,
    isLoading,
    error: error ? errorMessage(error) : null,
    refresh: mutate,
    mutationName,
    mutationError,
    saveProfile,
    saveProgramItem,
    saveReview,
    freezePolicyBinding,
    evaluateReleaseGate,
  };
}

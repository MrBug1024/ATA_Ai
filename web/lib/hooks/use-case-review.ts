"use client";

import { reviewCase } from "@/lib/backend/langgraph";
import type { ReviewRequest } from "@/lib/types/case-analytics";
import { useBackendMutation } from "./use-backend-mutation";

export function useCaseReview(caseId: number) {
  const { data, isMutating, error, trigger, reset } = useBackendMutation(
    (req: ReviewRequest) => reviewCase(caseId, req)
  );
  return { data, isMutating, error, review: trigger, reset };
}

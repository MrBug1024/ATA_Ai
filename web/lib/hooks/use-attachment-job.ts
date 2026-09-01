"use client";

import useSWR, { useSWRConfig } from "swr";
import {
  attachmentJobKey,
  cancelAttachmentJob,
  getAttachmentJob,
  isTerminalAttachmentJobStatus,
  retryAttachmentJob,
  type AttachmentJobRef,
} from "@/lib/backend/generated-artifacts";
import { BackendError } from "@/lib/backend/http";
import { useBackendMutation } from "./use-backend-mutation";

const POLL_INTERVAL_MS = 2_000;

function isPermanentError(error: unknown): boolean {
  return error instanceof BackendError && [400, 401, 403, 404, 409, 422].includes(error.status);
}

export function useAttachmentJob(jobRef: AttachmentJobRef | null | undefined) {
  const caseId = jobRef?.case_id;
  const jobId = jobRef?.job_id;
  const key = caseId && jobId ? attachmentJobKey(caseId, jobId) : null;
  const { data, error, isLoading, isValidating, mutate } = useSWR(
    key,
    () => getAttachmentJob(caseId as number, jobId as string),
    {
      refreshInterval: (latest) =>
        latest && isTerminalAttachmentJobStatus(latest.status) ? 0 : POLL_INTERVAL_MS,
      refreshWhenHidden: false,
      refreshWhenOffline: false,
      shouldRetryOnError: (retryError) => !isPermanentError(retryError),
      errorRetryCount: 3,
      errorRetryInterval: POLL_INTERVAL_MS,
    }
  );

  return {
    job: data ?? null,
    error: error instanceof Error ? error.message : error ? "获取附件进度失败" : null,
    isLoading,
    isValidating,
    refresh: mutate,
  };
}

export function useRetryAttachmentJob(jobRef: AttachmentJobRef) {
  const { mutate } = useSWRConfig();
  const mutation = useBackendMutation(async (_request: void) => {
    const result = await retryAttachmentJob(jobRef.case_id, jobRef.job_id);
    void mutate(attachmentJobKey(jobRef.case_id, jobRef.job_id), result, false);
    return result;
  });
  return { ...mutation, retryJob: mutation.trigger };
}

export function useCancelAttachmentJob(jobRef: AttachmentJobRef) {
  const { mutate } = useSWRConfig();
  const mutation = useBackendMutation(async (_request: void) => {
    const result = await cancelAttachmentJob(jobRef.case_id, jobRef.job_id);
    void mutate(attachmentJobKey(jobRef.case_id, jobRef.job_id), result, false);
    return result;
  });
  return { ...mutation, cancelJob: mutation.trigger };
}

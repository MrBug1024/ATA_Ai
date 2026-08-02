"use client";

import useSWR from "swr";
import { useCallback } from "react";
import {
  threadsKey,
  listThreads,
  type LangGraphThread,
  type ThreadListParams,
  type ThreadListResponse,
} from "@/lib/backend/langgraph";

export type { LangGraphThread };

export function useConversations(params: ThreadListParams = {}, enabled = true) {
  const key = enabled ? threadsKey(params) : null;
  const { data, error, isLoading, mutate } = useSWR<ThreadListResponse>(
    key,
    () => listThreads(params)
  );

  const refresh = useCallback(() => mutate(), [mutate]);

  return {
    conversations: data?.threads ?? [],
    total: data?.total ?? 0,
    limit: data?.limit ?? params.limit ?? 50,
    offset: data?.offset ?? params.offset ?? 0,
    isLoading,
    error: error ? (error instanceof Error ? error.message : "Unknown error") : null,
    refresh,
  };
}

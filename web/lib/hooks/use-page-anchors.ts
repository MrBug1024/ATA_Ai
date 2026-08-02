"use client";

import useSWR from "swr";
import type { PageAnchorsResponse } from "@/lib/types/knowledge-graph";
import { pageAnchorsKey, getPageAnchors } from "@/lib/backend/langgraph";

export function usePageAnchors(
  fileId: number | null,
  pageNo: number | null,
  chunkId?: string
) {
  const key =
    fileId !== null && pageNo !== null ? pageAnchorsKey(fileId, pageNo, chunkId) : null;

  const { data, error, isLoading } = useSWR<PageAnchorsResponse>(key, () =>
    getPageAnchors(fileId as number, pageNo as number, chunkId)
  );

  return {
    data: data ?? null,
    isLoading,
    error: error instanceof Error ? error.message : null,
  };
}

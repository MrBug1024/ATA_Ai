"use client";

import useSWR from "swr";
import type { DocCategoriesResp } from "@/lib/types/doc-categories";
import { docCategoriesKey, getDocCategories } from "@/lib/backend/cases";

export function useDocCategories() {
  const { data, error, isLoading } = useSWR<DocCategoriesResp["categories"]>(
    docCategoriesKey(),
    getDocCategories
  );
  return {
    categories: data ?? [],
    isLoading,
    error,
  };
}

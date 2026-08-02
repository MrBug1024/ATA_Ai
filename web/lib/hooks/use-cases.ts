"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import useSWR from "swr";
import { casesKey, listCases, type Case, type CasesPage } from "@/lib/backend/cases";

export type { Case };

export interface UseCasesResult {
  cases: Case[];
  isLoading: boolean;
  error: unknown;
  total: number;
  page: number;
  setPage: (p: number) => void;
  keyword: string;
  setKeyword: (k: string) => void;
  retry: () => void;
  refresh: () => void;
}

export function useCases(): UseCasesResult {
  const [keyword, setKeywordState] = useState("");
  const [page, setPageRaw] = useState(1);
  const [cases, setCases] = useState<Case[]>([]);
  const [total, setTotal] = useState(0);
  const keywordRef = useRef(keyword);

  const setKeyword = useCallback((k: string) => {
    if (keywordRef.current === k) return;
    keywordRef.current = k;
    setKeywordState(k);
    setCases([]);
    setPageRaw(1);
  }, []);

  const setPage = useCallback((p: number) => {
    if (p === 1) setCases([]);
    setPageRaw(p);
  }, []);

  const { data, isLoading, error, mutate } = useSWR<CasesPage>(casesKey(page, keyword), () =>
    listCases(page, keyword)
  );
  const retry = useCallback(() => { mutate(); }, [mutate]);
  const refresh = useCallback(() => {
    setCases([]);
    setPageRaw(1);
    mutate();
  }, [mutate]);

  useEffect(() => {
    if (!data) return;
    setTotal(data.total);
    setCases((prev) =>
      data.page === 1
        ? data.cases
        : [...prev, ...data.cases.filter((c) => !prev.some((p) => p.case_id === c.case_id))]
    );
  }, [data]);

  return {
    cases,
    isLoading,
    error,
    total,
    page,
    setPage,
    keyword,
    setKeyword,
    retry,
    refresh,
  };
}

"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import useSWR from "swr";
import { casesKey, deleteCase, listCases, type Case, type CasesPage } from "@/lib/backend/cases";

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
  remove: (caseId: number) => Promise<void>;
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
  const remove = useCallback(async (caseId: number) => {
    await deleteCase(caseId);
    setCases((current) => current.filter((item) => item.case_id !== caseId));
    setTotal((current) => Math.max(0, current - 1));
    await mutate();
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
    remove,
  };
}

// lib/assistant-ui/evidence-context.tsx
"use client";

import { createContext, useContext } from "react";

interface EvidenceContextValue {
  caseId: number | null;
  reportRef: string | null;
}

const EvidenceContext = createContext<EvidenceContextValue>({
  caseId: null,
  reportRef: null,
});

interface ProviderProps extends EvidenceContextValue {
  children: React.ReactNode;
}

export function EvidenceContextProvider({ caseId, reportRef, children }: ProviderProps) {
  return (
    <EvidenceContext.Provider value={{ caseId, reportRef }}>
      {children}
    </EvidenceContext.Provider>
  );
}

export function useEvidenceContext() {
  return useContext(EvidenceContext);
}

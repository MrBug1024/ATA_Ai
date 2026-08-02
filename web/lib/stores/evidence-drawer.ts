"use client";

import { create } from "zustand";
import type { PageAnchorsResponse } from "@/lib/types/knowledge-graph";

interface OpenDrawerParams {
  caseId: number;
  reportRef: string;
  citationId: string;
}

interface EvidenceDrawerState {
  open: boolean;
  caseId: number;
  reportRef: string;
  citationId: string;
  selectedEvidenceIndex: number;
  currentPage: PageAnchorsResponse | null;
  openDrawer: (params: OpenDrawerParams) => void;
  closeDrawer: () => void;
  setSelectedEvidenceIndex: (index: number) => void;
  setCurrentPage: (page: PageAnchorsResponse | null) => void;
}

export const useEvidenceDrawerStore = create<EvidenceDrawerState>((set) => ({
  open: false,
  caseId: 0,
  reportRef: "",
  citationId: "",
  selectedEvidenceIndex: 0,
  currentPage: null,

  openDrawer: ({ caseId, reportRef, citationId }) =>
    set({ open: true, caseId, reportRef, citationId, selectedEvidenceIndex: 0, currentPage: null }),

  closeDrawer: () =>
    set({ open: false, caseId: 0, reportRef: "", citationId: "", selectedEvidenceIndex: 0, currentPage: null }),

  setSelectedEvidenceIndex: (index) => set({ selectedEvidenceIndex: index }),

  setCurrentPage: (page) => set({ currentPage: page }),
}));

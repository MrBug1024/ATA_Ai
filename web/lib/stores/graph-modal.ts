"use client";

import { create } from "zustand";
import { useEvidenceDrawerStore } from "./evidence-drawer";

interface OpenModalParams {
  caseId: number;
  centerEntityId?: number;
  reportRef?: string | null;
}

interface GraphModalState {
  open: boolean;
  caseId: number;
  centerEntityId: number | undefined;
  reportRef: string | null;
  openModal: (params: OpenModalParams) => void;
  closeModal: () => void;
  setCenterEntityId: (id: number) => void;
}

export const useGraphModalStore = create<GraphModalState>((set) => ({
  open: false,
  caseId: 0,
  centerEntityId: undefined,
  reportRef: null,

  // 证据抽屉的开合不跨越图谱模态的边界:进入图谱时不带入聊天里打开的角标抽屉,
  // 退出图谱时也不把图谱内打开的证据残留给聊天的 inline 抽屉。
  openModal: ({ caseId, centerEntityId, reportRef = null }) => {
    useEvidenceDrawerStore.getState().closeDrawer();
    set({ open: true, caseId, centerEntityId, reportRef });
  },

  closeModal: () => {
    useEvidenceDrawerStore.getState().closeDrawer();
    set({ open: false, caseId: 0, centerEntityId: undefined, reportRef: null });
  },

  setCenterEntityId: (id) => set({ centerEntityId: id }),
}));

"use client";

import { create } from "zustand";
import type { UploadAndIngestResponse, MaterialEventDetail } from "@/lib/types/doc-categories";

export type UploadTaskStatus =
  | "uploading"
  | "processing"
  | "completed"
  | "failed";

export interface UploadTask {
  id: string;
  caseId: number;
  caseName: string;
  categoryName: string;
  batchName?: string;
  fileNames: string[];
  status: UploadTaskStatus;
  materialEventId: string | null;
  result: UploadAndIngestResponse | null;
  materialEvent: MaterialEventDetail | null;
  createdAt: number;
  updatedAt: number;
}

interface UploadQueueState {
  tasks: UploadTask[];
  addTask: (task: Omit<UploadTask, "id" | "createdAt" | "updatedAt">) => string;
  updateTask: (id: string, updates: Partial<UploadTask>) => void;
  removeTask: (id: string) => void;
  clearCompleted: () => void;
}

export const useUploadQueue = create<UploadQueueState>((set) => ({
  tasks: [],

  addTask: (task) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const now = Date.now();
    set((state) => ({
      tasks: [
        ...state.tasks,
        {
          ...task,
          id,
          createdAt: now,
          updatedAt: now,
        },
      ],
    }));
    return id;
  },

  updateTask: (id, updates) =>
    set((state) => ({
      tasks: state.tasks.map((t) =>
        t.id === id
          ? { ...t, ...updates, updatedAt: Date.now() }
          : t
      ),
    })),

  removeTask: (id) =>
    set((state) => ({
      tasks: state.tasks.filter((t) => t.id !== id),
    })),

  clearCompleted: () =>
    set((state) => ({
      tasks: state.tasks.filter(
        (t) => t.status !== "completed" && t.status !== "failed"
      ),
    })),
}));

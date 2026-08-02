import { createContext } from "react";

export interface ThinkingStep {
  title: string;
  nodeType: string;
  payload?: Record<string, unknown>;
}

export interface ThinkingState {
  steps: ThinkingStep[];
  isComplete: boolean;
  startedAt: number;
  completedAt?: number;
}

export type ThinkingUpdate = {
  type: "node";
  title: string;
  nodeType: string;
  payload?: Record<string, unknown>;
};

export const ThinkingContext = createContext<ReadonlyMap<string, ThinkingState>>(new Map());

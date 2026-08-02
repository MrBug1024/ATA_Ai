"use client";

import { useState, useCallback, useRef } from "react";
import type { ThinkingState, ThinkingUpdate } from "./thinking-context";

export function useThinking() {
  const [thinkingMap, setThinkingMap] = useState<Map<string, ThinkingState>>(new Map());
  const streamIdRef = useRef<string>("");

  const initThinking = useCallback((streamId: string) => {
    streamIdRef.current = streamId;
    setThinkingMap((prev) => {
      const next = new Map(prev);
      next.set(streamId, {
        steps: [],
        isComplete: false,
        startedAt: Date.now(),
      });
      return next;
    });
  }, []);

  const updateThinking = useCallback((update: ThinkingUpdate) => {
    const streamId = streamIdRef.current;
    if (!streamId) return;
    setThinkingMap((prev) => {
      const state = prev.get(streamId);
      if (!state) return prev;
      const next = new Map(prev);
      next.set(streamId, {
        ...state,
        steps: [
          ...state.steps,
          { title: update.title, nodeType: update.nodeType, payload: update.payload },
        ],
      });
      return next;
    });
  }, []);

  const completeThinking = useCallback(() => {
    const streamId = streamIdRef.current;
    if (!streamId) return;
    setThinkingMap((prev) => {
      const state = prev.get(streamId);
      if (!state) return prev;
      const next = new Map(prev);
      next.set(streamId, { ...state, isComplete: true, completedAt: Date.now() });
      return next;
    });
    streamIdRef.current = "";
  }, []);

  return { thinkingMap, setThinkingMap, streamIdRef, initThinking, updateThinking, completeThinking };
}

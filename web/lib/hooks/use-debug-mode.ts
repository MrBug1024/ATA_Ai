"use client";

import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "ai-hunter:debug-nodes";
const EVENT_NAME = "ai-hunter:debug-nodes-changed";

function read(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(STORAGE_KEY) === "1";
}

export function useDebugMode(): [boolean, (next: boolean) => void] {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    setEnabled(read());
    const handler = () => setEnabled(read());
    window.addEventListener(EVENT_NAME, handler);
    window.addEventListener("storage", (e) => {
      if (e.key === STORAGE_KEY) handler();
    });
    return () => {
      window.removeEventListener(EVENT_NAME, handler);
    };
  }, []);

  const set = useCallback((next: boolean) => {
    if (next) window.localStorage.setItem(STORAGE_KEY, "1");
    else window.localStorage.removeItem(STORAGE_KEY);
    window.dispatchEvent(new Event(EVENT_NAME));
    setEnabled(next);
  }, []);

  return [enabled, set];
}

"use client";

import { useEffect, useRef, useState } from "react";

/** 用 ResizeObserver 跟踪元素内容尺寸(整数像素)。 */
export function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!ref.current) return;
    const obs = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width: Math.floor(width), height: Math.floor(height) });
    });
    obs.observe(ref.current);
    return () => obs.disconnect();
  }, []);

  return [ref, size] as const;
}

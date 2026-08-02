"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useTheme } from "next-themes";

interface MermaidDiagramProps {
  code: string;
}

export function MermaidDiagram({ code }: MermaidDiagramProps) {
  const id = useId().replace(/:/g, "");
  const containerRef = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      const mermaid = (await import("mermaid")).default;

      mermaid.initialize({
        startOnLoad: false,
        theme: resolvedTheme === "dark" ? "dark" : "default",
        fontFamily: "inherit",
        securityLevel: "strict",
      });

      try {
        const { svg } = await mermaid.render(`mermaid-${id}`, code.trim());
        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg;
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "渲染失败");
        }
      }
    }

    render();
    return () => { cancelled = true; };
  }, [code, id, resolvedTheme]);

  if (error) {
    return (
      <pre className="my-2 overflow-x-auto rounded-lg bg-muted p-3 text-sm font-mono text-destructive">
        {code}
        <span className="mt-1 block text-xs text-destructive/70">{error}</span>
      </pre>
    );
  }

  return (
    <div
      ref={containerRef}
      className="my-3 flex justify-center overflow-x-auto rounded-lg bg-muted/40 p-4"
    />
  );
}

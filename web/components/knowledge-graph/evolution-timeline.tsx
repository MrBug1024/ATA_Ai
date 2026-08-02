"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";
import type { EvolutionItem } from "@/lib/types/knowledge-graph";

type ActionFilter = "ALL" | "ADD" | "OVERRIDE";

interface EvolutionTimelineProps {
  items: EvolutionItem[];
  isLoading: boolean;
}

export function EvolutionTimeline({ items, isLoading }: EvolutionTimelineProps) {
  const [filter, setFilter] = useState<ActionFilter>("ALL");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  if (isLoading) {
    return <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">加载中…</div>;
  }

  const filtered = filter === "ALL" ? items : items.filter((i) => i.action === filter);

  if (filtered.length === 0) {
    return (
      <div className="space-y-4">
        <FilterBar filter={filter} onChange={setFilter} />
        <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">暂无结论演进</div>
      </div>
    );
  }

  function toggleExpanded(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="space-y-4">
      <FilterBar filter={filter} onChange={setFilter} />
      <div className="space-y-3">
        {filtered.map((item) => {
          const itemKey = item.id ?? item.new_claim_id ?? Math.random();
          const isExpanded = expanded.has(itemKey);
          return (
            <div key={itemKey} className="rounded-md border p-3">
              <div className="flex items-start justify-between gap-2">
                <span className={cn(
                  "mt-0.5 rounded px-1.5 py-0.5 text-xs font-medium shrink-0",
                  item.action === "ADD"
                    ? "bg-emerald-500/10 text-emerald-500"
                    : "bg-amber-500/10 text-amber-500"
                )}>
                  {item.action === "ADD" ? "新增" : "替代"}
                </span>
                <div className="flex-1 space-y-1.5">
                  {item.action === "ADD" ? (
                    <p className="text-sm">{item.new_claim_text}</p>
                  ) : (
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <p className="text-sm text-muted-foreground line-through">{item.superseded_claim_text}</p>
                      <p className="text-sm">{item.new_claim_text}</p>
                    </div>
                  )}
                  <div className="text-xs text-muted-foreground">
                    {item.batch_name} · {item.doc_category}
                    {item.created_at && <> · {new Date(item.created_at).toLocaleDateString("zh-CN")}</>}
                  </div>
                  {item.action === "OVERRIDE" && item.rationale && (
                    <p className="text-xs text-muted-foreground">
                      {item.rationale.length > 60 && !isExpanded
                        ? item.rationale.slice(0, 60) + "…"
                        : item.rationale}
                    </p>
                  )}
                </div>
                {item.evidences.length > 0 && (
                  <button
                    type="button"
                    className="shrink-0 text-xs text-primary hover:text-primary/80"
                    onClick={() => toggleExpanded(itemKey)}
                  >
                    {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                  </button>
                )}
              </div>
              {isExpanded && item.evidences.length > 0 && (
                <div className="mt-2 space-y-1 border-t pt-2">
                  {item.evidences.map((ev) => (
                    <div key={ev.chunk_id} className="flex gap-2 text-xs text-muted-foreground">
                      <span className="shrink-0">{ev.file_name} P.{ev.page_no}</span>
                      <span className="line-clamp-1">{ev.quote_text}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface FilterBarProps {
  filter: ActionFilter;
  onChange: (f: ActionFilter) => void;
}

function FilterBar({ filter, onChange }: FilterBarProps) {
  const options: { value: ActionFilter; label: string }[] = [
    { value: "ALL", label: "全部" },
    { value: "ADD", label: "新增" },
    { value: "OVERRIDE", label: "替代" },
  ];
  return (
    <div className="flex gap-1">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            "rounded px-2.5 py-1 text-xs transition-colors",
            filter === opt.value ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-muted"
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

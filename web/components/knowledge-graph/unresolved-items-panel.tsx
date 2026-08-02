"use client";

import { CheckCircle } from "lucide-react";
import type { UnresolvedItemsResponse } from "@/lib/types/knowledge-graph";

interface UnresolvedItemsPanelProps {
  data: UnresolvedItemsResponse | null;
  isLoading: boolean;
}

export function UnresolvedItemsPanel({ data, isLoading }: UnresolvedItemsPanelProps) {
  if (isLoading) {
    return <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">加载中…</div>;
  }

  if (!data) return null;

  const totalUnresolved = data.unresolved_relation_count + data.unresolved_claim_count;

  if (totalUnresolved === 0) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-emerald-500">
        <CheckCircle className="h-4 w-4" />
        全部依赖已补齐
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        <span>{data.unresolved_relation_count} 条关系未决</span>
        <span>·</span>
        <span>{data.unresolved_claim_count} 条断言未决</span>
      </div>

      {data.unresolved_relations.length > 0 && (
        <section>
          <h4 className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">未决关系</h4>
          <div className="space-y-2">
            {data.unresolved_relations.map((r) => (
              <div key={r.id ?? r.relation_temp_id} className="rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-muted px-1.5 py-0.5 text-xs">{r.relation_type}</span>
                  <span className="text-sm">{r.relation_label}</span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{r.reason}</p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {r.missing_dependencies.map((dep) => (
                    <span key={dep} className="rounded bg-destructive/10 px-1.5 py-0.5 text-xs text-destructive">
                      {dep}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {data.unresolved_claims.length > 0 && (
        <section>
          <h4 className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">未决断言</h4>
          <div className="space-y-2">
            {data.unresolved_claims.map((c) => (
              <div key={c.id ?? c.entity_key} className="rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-muted px-1.5 py-0.5 text-xs">{c.claim_type}</span>
                  <span className="text-sm">{c.claim_text}</span>
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">{c.entity_name}</div>
                <p className="mt-1 text-xs text-muted-foreground">{c.reason}</p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {c.missing_dependencies.map((dep) => (
                    <span key={dep} className="rounded bg-destructive/10 px-1.5 py-0.5 text-xs text-destructive">
                      {dep}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

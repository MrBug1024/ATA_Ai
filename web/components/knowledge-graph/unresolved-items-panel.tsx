"use client";

import { CheckCircle } from "lucide-react";
import type { CaseDocCategoriesResp } from "@/lib/types/doc-categories";
import type { UnresolvedItemsResponse } from "@/lib/types/knowledge-graph";

interface UnresolvedItemsPanelProps {
  data: UnresolvedItemsResponse | null;
  isLoading: boolean;
  caseDocCategories?: CaseDocCategoriesResp | null;
  docCategoriesLoading?: boolean;
}

export function UnresolvedItemsPanel({
  data,
  isLoading,
  caseDocCategories = null,
  docCategoriesLoading = false,
}: UnresolvedItemsPanelProps) {
  if (isLoading || docCategoriesLoading) {
    return <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">加载中…</div>;
  }

  if (!data && !caseDocCategories) return null;

  const totalUnresolved = data
    ? data.unresolved_relation_count + data.unresolved_claim_count
    : 0;
  const missingCodes = new Set(caseDocCategories?.missing_categories ?? []);
  const availableCategories = (caseDocCategories?.categories ?? []).filter(
    (category) => category.uploaded && !missingCodes.has(category.code)
  );
  const missingCategories = (caseDocCategories?.categories ?? []).filter(
    (category) => !category.uploaded || missingCodes.has(category.code)
  );

  return (
    <div className="space-y-4">
      {caseDocCategories && (
        <div data-testid="material-coverage-summary" className="rounded-md border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
          已识别 <span className="font-medium text-foreground">{availableCategories.length}</span> 类资料
          <span className="mx-2">·</span>
          仍缺 <span className="font-medium text-destructive">{missingCategories.length}</span> 类资料
        </div>
      )}

      <section className="space-y-2">
        <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">当前已有资料类别</h4>
        {availableCategories.length > 0 ? (
          <div className="space-y-2">
            {availableCategories.map((category) => (
              <div key={category.code} className="rounded-md border border-emerald-200/70 bg-emerald-50/40 p-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <CheckCircle className="h-4 w-4 text-emerald-600" />
                  {category.name}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {category.file_count} 个文件 · {category.record_count} 条结构化记录
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="py-2 text-sm text-muted-foreground">当前没有已识别的资料类别。</p>
        )}
      </section>

      <section className="space-y-2">
        <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">仍缺资料类别</h4>
        {missingCategories.length > 0 ? (
          <div className="space-y-2">
            {missingCategories.map((category) => (
              <div key={category.code} className="rounded-md border p-3">
                <div className="text-sm font-medium">{category.name}</div>
                <p className="mt-1 text-xs text-muted-foreground">
                  尚未上传可识别资料 · 当前 {category.record_count} 条结构化记录
                </p>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2 py-2 text-sm text-emerald-500">
            <CheckCircle className="h-4 w-4" />
            必需资料类别已上传
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">图谱未决项</h4>
        {data && totalUnresolved > 0 ? (
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <span>{data.unresolved_relation_count} 条关系未决</span>
            <span>·</span>
            <span>{data.unresolved_claim_count} 条断言未决</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 py-2 text-sm text-emerald-500">
            <CheckCircle className="h-4 w-4" />
            无图谱未决关系或断言
          </div>
        )}
      </section>

      {data && data.unresolved_relations.length > 0 && (
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

      {data && data.unresolved_claims.length > 0 && (
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

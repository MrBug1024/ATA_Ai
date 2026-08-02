"use client";

import { useState, useEffect } from "react";
import { useCases, type Case } from "@/lib/hooks/use-cases";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Scale, Search, Loader2, RefreshCw, SlidersHorizontal, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { RISK_BADGE_CLASS, scoreToRiskLevel } from "@/lib/utils/risk-style";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuCheckboxItem,
} from "@/components/ui/dropdown-menu";
import { formatDistanceToNow, format } from "date-fns";
import { zhCN } from "date-fns/locale";
import Link from "next/link";
import { AddMaterialDialog } from "@/components/cases/add-material-dialog";
import { CreateCaseDialog } from "@/components/cases/create-case-dialog";
import { CaseUploadStatus } from "@/components/cases/case-upload-status";

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true, locale: zhCN });
  } catch {
    return "—";
  }
}

function exactTime(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return format(new Date(iso), "yyyy-MM-dd HH:mm");
  } catch {
    return "";
  }
}

function fmt(score: number | null | undefined): string {
  if (score == null) return "—";
  return Number.isInteger(score) ? String(score) : score.toFixed(1);
}

function scoreColor(score: number | null | undefined): string {
  if (score == null) return "text-muted-foreground/30";
  if (score >= 75) return "text-destructive";
  if (score >= 50) return "text-amber-500";
  return "text-emerald-500";
}

function CompositeBadge({ score }: { score?: number | null }) {
  if (score == null) {
    return <span className="inline-flex items-center rounded-md bg-muted/60 px-2 py-0.5 text-xs font-medium tabular-nums text-muted-foreground/40">—</span>;
  }
  const cls = RISK_BADGE_CLASS[scoreToRiskLevel(score)];
  return (
    <span className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-sm font-semibold tabular-nums", cls)}>
      {fmt(score)}
    </span>
  );
}

function MiniScore({ score }: { score?: number | null }) {
  return (
    <span className={cn("tabular-nums text-xs font-medium", scoreColor(score))}>
      {fmt(score)}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground/70 whitespace-nowrap">
      {status}
    </span>
  );
}

const ENGINE_COLS: { key: keyof Case; label: string }[] = [
  { key: "delta_score",      label: "轧差审计" },
  { key: "valuation_score",  label: "瑕疵挤水" },
  { key: "deadline_score",   label: "时效预警" },
  { key: "behavioral_score", label: "行为扫描" },
];

const OPTIONAL_COLS: { key: string; label: string }[] = [
  { key: "created_at", label: "创建时间" },
  { key: "updated_at", label: "更新时间" },
];

function ColumnPicker({
  visible,
  onToggle,
}: {
  visible: Set<string>;
  onToggle: (key: string) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            "flex items-center gap-1.5 rounded-md border border-border/50 px-2.5 py-1.5 text-xs transition-colors",
            "text-muted-foreground hover:border-border hover:bg-accent hover:text-foreground",
            "data-[state=open]:border-border data-[state=open]:bg-accent data-[state=open]:text-foreground"
          )}
        >
          <SlidersHorizontal className="size-3" />
          列显示
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-36">
        {OPTIONAL_COLS.map(({ key, label }) => (
          <DropdownMenuCheckboxItem
            key={key}
            checked={visible.has(key)}
            onCheckedChange={() => onToggle(key)}
            onSelect={(e) => e.preventDefault()}
          >
            {label}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export default function CasesPage() {
  const { cases, isLoading, error, total, page, setPage, keyword, setKeyword, retry, refresh } = useCases();
  const [inputValue, setInputValue] = useState("");
  const [materialCase, setMaterialCase] = useState<Case | null>(null);
  const [visibleCols, setVisibleCols] = useState<Set<string>>(new Set());
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setKeyword(inputValue), 300);
    return () => clearTimeout(t);
  }, [inputValue, setKeyword]);

  const toggleCol = (key: string) =>
    setVisibleCols((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });

  const hasMore = cases.length < total;

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 px-4">
        <SidebarTrigger className="size-9 shrink-0 text-muted-foreground hover:bg-accent hover:text-foreground" />
        <span className="text-sm text-foreground/70">案件列表</span>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-scroll p-5">
        <div className="flex flex-col gap-4">

          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground/40" />
              <input
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder="搜索案件名称或债务人…"
                className="w-full rounded-lg border border-border/50 bg-background pl-9 pr-4 py-2 text-sm placeholder:text-muted-foreground/40 outline-none focus:border-border"
              />
            </div>
            <ColumnPicker visible={visibleCols} onToggle={toggleCol} />
            <button
              type="button"
              onClick={() => setCreateOpen(true)}
              className="flex items-center gap-1.5 rounded-md border border-border/50 bg-foreground/5 px-2.5 py-1.5 text-xs font-medium text-foreground/80 transition-colors hover:border-border hover:bg-accent hover:text-foreground"
            >
              <Plus className="size-3" />
              创建案件
            </button>
          </div>

          {isLoading && cases.length === 0 && (
            <div className="flex items-center justify-center py-24">
              <Loader2 className="size-4 animate-spin text-muted-foreground/30" />
            </div>
          )}

          {!!error && cases.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
              <p className="text-sm text-muted-foreground/60">加载失败</p>
              <button
                type="button"
                onClick={retry}
                className="inline-flex items-center gap-1.5 rounded-md border border-border/50 px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              >
                <RefreshCw className="size-3" /> 重试
              </button>
            </div>
          )}

          {!isLoading && !error && cases.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
              <div className="flex size-12 items-center justify-center rounded-xl border border-border/40 bg-muted/40">
                <Scale className="size-5 text-muted-foreground/40" />
              </div>
              <p className="text-sm text-muted-foreground/60">
                {keyword ? "未找到匹配案件" : "暂无案件"}
              </p>
            </div>
          )}

          {cases.length > 0 && (
            <div className="overflow-x-scroll rounded-xl border border-border/50">
              <table className="w-full min-w-max">
                <thead>
                  <tr className="border-b border-border/40">
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60 whitespace-nowrap">ID</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60 whitespace-nowrap">案件名称</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60 whitespace-nowrap">债务人</th>
                    <th className="px-4 py-3 text-center text-xs font-medium text-muted-foreground/60 whitespace-nowrap">综合风险</th>
                    {ENGINE_COLS.map(({ key, label }) => (
                      <th key={key} className="px-4 py-3 text-center text-xs font-medium text-muted-foreground/60 whitespace-nowrap">
                        {label}
                      </th>
                    ))}
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60 whitespace-nowrap">状态</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60 whitespace-nowrap">卷宗上传</th>
                    {visibleCols.has("created_at") && (
                      <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60 whitespace-nowrap">创建时间</th>
                    )}
                    {visibleCols.has("updated_at") && (
                      <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60 whitespace-nowrap">更新时间</th>
                    )}
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60 whitespace-nowrap">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/30">
                  {cases.map((c, i) => (
                    <tr
                      key={c.case_id ?? i}
                      className="transition-colors hover:bg-accent/20"
                    >
                      <td className="px-4 py-3">
                        <span className="font-mono text-xs text-muted-foreground/50">
                          #{c.case_id}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          <div className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-border/30 bg-muted/50">
                            <Scale className="size-3.5 text-muted-foreground/50" />
                          </div>
                          <div className="min-w-0">
                            <p className="max-w-[220px] truncate text-xs font-medium text-foreground/90">
                              {c.case_name}
                            </p>
                            <p className="text-[10px] text-muted-foreground/50">{c.case_type}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground/70">
                        <span className="block max-w-[160px] truncate">{c.debtor_names ?? "—"}</span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <CompositeBadge score={c.composite_score} />
                      </td>
                      {ENGINE_COLS.map(({ key }) => (
                        <td key={key} className="px-4 py-3 text-center">
                          <MiniScore score={c[key] as number | null | undefined} />
                        </td>
                      ))}
                      <td className="px-4 py-3">
                        <StatusBadge status={c.status} />
                      </td>
                      <td className="px-4 py-3">
                        <CaseUploadStatus caseId={c.case_id} />
                      </td>
                      {visibleCols.has("created_at") && (
                        <td className="px-4 py-3" title={exactTime(c.created_at)}>
                          <span className="text-xs text-muted-foreground/50 whitespace-nowrap">
                            {relativeTime(c.created_at)}
                          </span>
                        </td>
                      )}
                      {visibleCols.has("updated_at") && (
                        <td className="px-4 py-3" title={exactTime(c.updated_at)}>
                          <span className="text-xs text-muted-foreground/50 whitespace-nowrap">
                            {relativeTime(c.updated_at)}
                          </span>
                        </td>
                      )}
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => setMaterialCase(c)}
                            className="inline-flex items-center rounded-md border border-border/50 px-2.5 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors whitespace-nowrap"
                          >
                            添加材料
                          </button>
                          <Link
                            href={`/cases/${c.case_id}`}
                            className="text-xs text-muted-foreground hover:text-foreground transition-colors whitespace-nowrap"
                          >
                            治理 →
                          </Link>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {hasMore && (
            <div className="flex justify-center pt-2">
              <button
                type="button"
                onClick={() => setPage(page + 1)}
                disabled={isLoading}
                className="inline-flex items-center gap-2 rounded-lg border border-border/50 px-4 py-2 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors disabled:opacity-50"
              >
                {isLoading && <Loader2 className="size-3 animate-spin" />}
                {isLoading ? "加载中…" : "加载更多"}
              </button>
            </div>
          )}

          {total > 0 && (
            <p className="text-center text-xs text-muted-foreground/40">
              共 {total} 个案件，已显示 {cases.length} 个
            </p>
          )}

        </div>
      </div>

      {materialCase && (
        <AddMaterialDialog
          open={!!materialCase}
          onOpenChange={(open) => { if (!open) setMaterialCase(null); }}
          caseItem={materialCase}
        />
      )}

      <CreateCaseDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={refresh}
      />
    </div>
  );
}

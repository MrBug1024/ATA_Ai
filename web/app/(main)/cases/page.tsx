"use client";

import { useState, useEffect } from "react";
import { useCases, type Case } from "@/lib/hooks/use-cases";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { ClipboardCheck, Search, Loader2, RefreshCw, Plus } from "lucide-react";
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

function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    planning: "计划阶段",
    fieldwork: "现场执行",
    review: "复核中",
    reporting: "报告中",
    completed: "已完成",
    archived: "已归档",
  };
  return (
    <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground/70 whitespace-nowrap">
      {labels[status] ?? status}
    </span>
  );
}

export default function CasesPage() {
  const { cases, isLoading, error, total, page, setPage, keyword, setKeyword, retry, refresh, remove } = useCases();
  const [inputValue, setInputValue] = useState("");
  const [materialCase, setMaterialCase] = useState<Case | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [removingCaseId, setRemovingCaseId] = useState<number | null>(null);

  const handleRemove = async (caseItem: Case) => {
    const confirmed = window.confirm(
      `确认移除年审项目“${caseItem.case_name}”吗？\n\n项目会从当前项目列表隐藏，原始材料、审计底稿和审计留痕会保留。`
    );
    if (!confirmed) return;
    setRemovingCaseId(caseItem.case_id);
    try {
      await remove(caseItem.case_id);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "移除年审项目失败");
    } finally {
      setRemovingCaseId(null);
    }
  };

  useEffect(() => {
    const t = setTimeout(() => setKeyword(inputValue), 300);
    return () => clearTimeout(t);
  }, [inputValue, setKeyword]);

  const hasMore = cases.length < total;

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 px-4">
        <SidebarTrigger className="size-9 shrink-0 text-muted-foreground hover:bg-accent hover:text-foreground" />
        <span className="text-sm text-foreground/70">年度审计项目</span>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-scroll p-5">
        <div className="flex flex-col gap-4">

          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground/40" />
              <input
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder="搜索项目名称、被审计单位或项目编号…"
                className="w-full rounded-lg border border-border/50 bg-background pl-9 pr-4 py-2 text-sm placeholder:text-muted-foreground/40 outline-none focus:border-border"
              />
            </div>
            <button
              type="button"
              onClick={() => setCreateOpen(true)}
              className="flex items-center gap-1.5 rounded-md border border-border/50 bg-foreground/5 px-2.5 py-1.5 text-xs font-medium text-foreground/80 transition-colors hover:border-border hover:bg-accent hover:text-foreground"
            >
              <Plus className="size-3" />
              创建年审项目
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
                <ClipboardCheck className="size-5 text-muted-foreground/40" />
              </div>
              <p className="text-sm text-muted-foreground/60">
                {keyword ? "未找到匹配年审项目" : "暂无年审项目"}
              </p>
            </div>
          )}

          {cases.length > 0 && (
            <div className="overflow-x-scroll rounded-xl border border-border/50">
              <table className="w-full min-w-max">
                <thead>
                  <tr className="border-b border-border/40">
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60 whitespace-nowrap">ID</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60 whitespace-nowrap">项目名称</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60 whitespace-nowrap">被审计单位</th>
                    <th className="px-4 py-3 text-center text-xs font-medium text-muted-foreground/60 whitespace-nowrap">审计年度</th>
                    <th className="px-4 py-3 text-center text-xs font-medium text-muted-foreground/60 whitespace-nowrap">待办 / 总任务</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60 whitespace-nowrap">状态</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60 whitespace-nowrap">资料完整性</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground/60 whitespace-nowrap">更新时间</th>
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
                            <ClipboardCheck className="size-3.5 text-muted-foreground/50" />
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
                        <span className="block max-w-[160px] truncate">{c.entity_name || "—"}</span>
                      </td>
                      <td className="px-4 py-3 text-center text-xs tabular-nums text-foreground/80">
                        {c.fiscal_year ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-center text-xs tabular-nums text-muted-foreground/70">
                        {c.pending_task_count ?? 0} / {c.task_count ?? 0}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={c.status} />
                      </td>
                      <td className="px-4 py-3">
                        <CaseUploadStatus caseId={c.case_id} />
                      </td>
                      <td className="px-4 py-3" title={exactTime(c.updated_at)}>
                        <span className="text-xs text-muted-foreground/50 whitespace-nowrap">
                          {relativeTime(c.updated_at)}
                        </span>
                      </td>
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
                            href={`/chat?caseId=${c.case_id}`}
                            className="text-xs font-medium text-primary hover:text-primary/80 transition-colors whitespace-nowrap"
                          >
                            AI 审计 →
                          </Link>
                          <Link
                            href={`/cases/${c.case_id}`}
                            className="text-xs text-muted-foreground hover:text-foreground transition-colors whitespace-nowrap"
                          >
                            项目工作台 →
                          </Link>
                          <button
                            type="button"
                            onClick={() => void handleRemove(c)}
                            disabled={removingCaseId === c.case_id}
                            className="text-xs text-destructive/70 hover:text-destructive transition-colors whitespace-nowrap disabled:opacity-50"
                          >
                            {removingCaseId === c.case_id ? "移除中…" : "移除项目"}
                          </button>
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
              共 {total} 个年审项目，已显示 {cases.length} 个
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

"use client";

import { useMemo } from "react";
import { useCaseMaterialEvents } from "@/lib/hooks/use-case-material-events";
import { useCaseDocCategories } from "@/lib/hooks/use-case-doc-categories";
import type { CaseDocCategoryItem } from "@/lib/types/doc-categories";
import { Loader2, CheckCircle2, AlertTriangle, CircleDashed } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  caseId: number;
}

function hasUsableCoverage(category: CaseDocCategoryItem | undefined): boolean {
  if (!category) return false;

  // Newer APIs expose the stricter evidence status; retain the legacy fields for
  // servers that have not yet added it.
  if (category.coverage_status !== undefined) {
    return category.coverage_status === "ready";
  }

  return category.uploaded || Boolean(category.covered_by_case_workpaper);
}

export function CaseUploadStatus({ caseId }: Props) {
  const { events, isLoading } = useCaseMaterialEvents(caseId);
  const { caseDocCategories, isLoading: isCoverageLoading } = useCaseDocCategories(caseId);

  const status = useMemo(() => {
    const categories = caseDocCategories?.categories ?? [];
    const categoriesByCode = new Map(categories.map((category) => [category.code, category]));

    const hasProcessing = events.some((e) => e.status === "processing");
    if (hasProcessing) return { label: "处理中", variant: "processing" as const };

    const hasManualReview = events.some(
      (event) =>
        event.stage === "manual_review_required" ||
        event.stage === "raw_preserved_pending_review" ||
        event.event_payload?.stage === "manual_review_required" ||
        event.event_payload?.stage === "raw_preserved_pending_review" ||
        (event.status === "failed" &&
          (event.event_payload?.retryable === false ||
            event.event_payload?.retry_policy === "manual_review_required"))
    );
    if (hasManualReview) return { label: "待人工复核", variant: "manual_review" as const };

    // A failed event is historical once its category has current usable evidence.
    // Failures without a ready category remain visible for recovery.
    const hasFailed = events.some(
      (event) =>
        event.status === "failed" &&
        !hasUsableCoverage(categoriesByCode.get(event.doc_category))
    );
    if (hasFailed) return { label: "上传失败", variant: "failed" as const };

    const total = categories.length;
    const available = categories.filter(hasUsableCoverage).length;
    const missing = Math.max(total - available, 0);
    if (total > 0 && missing === 0) {
      return { label: `完整 ${available}/${total} 类`, variant: "completed" as const };
    }
    if (available > 0) {
      return { label: `已有 ${available}/${total} 类`, variant: "partial" as const };
    }

    return { label: total > 0 ? `待上传 0/${total} 类` : "待上传", variant: "pending" as const };
  }, [caseDocCategories, events]);

  if (isLoading || isCoverageLoading) return <Loader2 className="size-3 animate-spin text-muted-foreground/40" />;

  const variantCls = {
    processing: "text-blue-600 bg-blue-50 border-blue-200",
    manual_review: "text-amber-700 bg-amber-50 border-amber-200",
    failed: "text-red-600 bg-red-50 border-red-200",
    completed: "text-emerald-600 bg-emerald-100 border-emerald-300",
    partial: "text-amber-700 bg-amber-50 border-amber-200",
    pending: "text-muted-foreground bg-muted/50 border-border/60",
  }[status.variant];

  const icon = {
    processing: <Loader2 className="size-3 animate-spin" />,
    manual_review: <AlertTriangle className="size-3" />,
    failed: <AlertTriangle className="size-3" />,
    completed: <CheckCircle2 className="size-3" />,
    partial: <AlertTriangle className="size-3" />,
    pending: <CircleDashed className="size-3" />,
  }[status.variant];

  const totalCategories = caseDocCategories?.categories.length ?? 0;
  const availableCategories = caseDocCategories?.categories.filter(hasUsableCoverage).length ?? 0;
  const missingCategories = Math.max(totalCategories - availableCategories, 0);
  const title = totalCategories > 0
    ? `已识别 ${availableCategories} 类，仍缺 ${missingCategories} 类；${events.length} 个材料事件`
    : (events.length > 0 ? `${events.length} 个材料事件` : undefined);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
        variantCls
      )}
      title={title}
    >
      {icon}
      {status.label}
    </span>
  );
}

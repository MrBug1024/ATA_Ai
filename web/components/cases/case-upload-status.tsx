"use client";

import { useMemo } from "react";
import { useCaseMaterialEvents } from "@/lib/hooks/use-case-material-events";
import { Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  caseId: number;
}

export function CaseUploadStatus({ caseId }: Props) {
  const { events, isLoading } = useCaseMaterialEvents(caseId);

  const status = useMemo(() => {
    const hasProcessing = events.some((e) => e.status === "processing");
    if (hasProcessing) return { label: "处理中", variant: "processing" as const };

    const hasFailed = events.some((e) => e.status === "failed");
    if (hasFailed) return { label: "失败", variant: "failed" as const };

    const hasCompleted = events.some((e) => e.status === "completed");
    if (hasCompleted) return { label: "已完成", variant: "completed" as const };

    return null;
  }, [events]);

  if (isLoading || !status) return null;

  const variantCls = {
    processing: "text-blue-600 bg-blue-50 border-blue-200",
    failed: "text-red-600 bg-red-50 border-red-200",
    completed: "text-emerald-600 bg-emerald-100 border-emerald-300",
  }[status.variant];

  const icon = {
    processing: <Loader2 className="size-3 animate-spin" />,
    failed: <AlertTriangle className="size-3" />,
    completed: <CheckCircle2 className="size-3" />,
  }[status.variant];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
        variantCls
      )}
      title={events.length > 0 ? `${events.length} 个材料事件` : undefined}
    >
      {icon}
      {status.label}
    </span>
  );
}

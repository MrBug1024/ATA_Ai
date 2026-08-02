"use client";

import { useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { CaseMaterialEventItem } from "@/lib/types/doc-categories";
import { useRetryUploadBatch } from "@/lib/hooks/use-retry-upload-batch";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const STATUS_DOT: Record<string, string> = {
  completed: "bg-primary",
  processing: "animate-pulse bg-muted-foreground",
  failed: "bg-destructive",
  received: "bg-muted-foreground/50",
};

const STAGE_LABELS: Record<string, string> = {
  stored: "已存储",
  ocr_running: "OCR进行中",
  graph_running: "图谱提取中",
  completed: "已完成",
  failed: "失败",
};

interface MaterialEventTimelineProps {
  events: CaseMaterialEventItem[];
  isLoading: boolean;
  onRetried?: () => void | Promise<unknown>;
}

function RetryFailedBatch({
  uploadBatchId,
  batchName,
  onRetried,
}: {
  uploadBatchId: string;
  batchName: string;
  onRetried?: () => void | Promise<unknown>;
}) {
  const { retry, isMutating, error } = useRetryUploadBatch(uploadBatchId);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (!submitted || !onRetried) return;
    const interval = window.setInterval(() => {
      void Promise.resolve(onRetried()).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(interval);
  }, [submitted, onRetried]);

  const handleRetry = async () => {
    try {
      const result = await retry("auto");
      if (result.accepted === false) {
        throw new Error("后端未接受本次重试");
      }
      setSubmitted(true);
      void Promise.resolve(onRetried?.()).catch(() => undefined);
      toast.success("失败批次已重新提交");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "批次重试失败");
    }
  };

  return (
    <div className="flex flex-col items-end gap-2">
      <Button
        type="button"
        variant="outline"
        size="xs"
        disabled={isMutating || submitted}
        onClick={handleRetry}
        aria-label={`重试批次 ${batchName}`}
      >
        {isMutating ? (
          <LoaderCircle data-icon="inline-start" className="animate-spin" />
        ) : (
          <RefreshCw data-icon="inline-start" />
        )}
        {isMutating ? "提交中" : submitted ? "已提交" : "重试批次"}
      </Button>
      {error && <p className="max-w-64 text-right text-xs text-destructive">{error}</p>}
    </div>
  );
}

export function MaterialEventTimeline({
  events,
  isLoading,
  onRetried,
}: MaterialEventTimelineProps) {
  const [expandedError, setExpandedError] = useState<string | null>(null);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4" aria-label="正在加载材料事件">
        <span className="sr-only">加载中…</span>
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
      </div>
    );
  }

  if (events.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">暂无材料事件</p>;
  }

  return (
    <div>
      {events.map((event, index) => {
        const changeCount =
          (event.add_item_count ?? 0) + (event.override_item_count ?? 0);
        const isErrorExpanded = expandedError === event.material_event_id;

        return (
          <div key={event.material_event_id} className="relative flex gap-4 pb-6">
            {index < events.length - 1 && (
              <div className="absolute left-[7px] top-4 h-full w-px bg-border" />
            )}
            <div
              className={cn(
                "mt-1 size-3.5 shrink-0 rounded-full",
                STATUS_DOT[event.status] ?? STATUS_DOT.received
              )}
              aria-hidden="true"
            />
            <Card className="min-w-0 flex-1">
              <CardHeader className="items-stretch justify-between gap-3 p-3 pb-2 sm:flex-row sm:items-start">
                <div className="min-w-0 flex-1">
                  <CardTitle className="truncate text-sm leading-5">{event.batch_name}</CardTitle>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {event.doc_category}
                    {event.operator_name ? ` · ${event.operator_name}` : ""}
                  </p>
                </div>
                <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                  <span className="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">
                    {STAGE_LABELS[event.stage] ?? event.stage}
                  </span>
                  {event.has_conclusion_changes && (
                    <span className="rounded-md border px-2 py-1 text-xs text-foreground">
                      {changeCount} 条结论变化
                    </span>
                  )}
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-3 p-3 pt-0">
                <p className="text-xs text-muted-foreground">
                  {event.file_count} 个文件
                  {event.records_inserted !== undefined
                    ? ` · ${event.records_inserted} 条记录`
                    : ""}
                  {event.created_at
                    ? ` · ${new Date(event.created_at).toLocaleString("zh-CN")}`
                    : ""}
                </p>

                {event.status === "failed" && (
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    {event.error_message ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="xs"
                        aria-expanded={isErrorExpanded}
                        aria-controls={`material-error-${event.material_event_id}`}
                        onClick={() =>
                          setExpandedError(isErrorExpanded ? null : event.material_event_id)
                        }
                      >
                        {isErrorExpanded ? (
                          <ChevronUp data-icon="inline-start" />
                        ) : (
                          <ChevronDown data-icon="inline-start" />
                        )}
                        {isErrorExpanded ? "收起错误" : "查看错误"}
                      </Button>
                    ) : (
                      <span />
                    )}
                    <RetryFailedBatch
                      uploadBatchId={event.upload_batch_id}
                      batchName={event.batch_name}
                      onRetried={onRetried}
                    />
                  </div>
                )}

                {event.status === "failed" && event.error_message && isErrorExpanded && (
                  <Alert
                    id={`material-error-${event.material_event_id}`}
                    variant="destructive"
                  >
                    <div>
                      <AlertTitle>处理失败</AlertTitle>
                      <AlertDescription>{event.error_message}</AlertDescription>
                    </div>
                  </Alert>
                )}
              </CardContent>
            </Card>
          </div>
        );
      })}
    </div>
  );
}

"use client";

import { useEffect, useMemo } from "react";
import { cn } from "@/lib/utils";
import { useUploadQueue } from "@/lib/stores/upload-queue";
import { useMaterialEvent } from "@/lib/hooks/use-material-event";
import {
  Upload,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  X,
  FileText,
} from "lucide-react";

function TaskPoller({ taskId, eventId }: { taskId: string; eventId: string }) {
  const { event } = useMaterialEvent(eventId, 3000);
  const updateTask = useUploadQueue((s) => s.updateTask);

  useEffect(() => {
    if (!event) return;
    if (event.status === "completed") {
      updateTask(taskId, {
        status: "completed",
        materialEvent: event,
      });
    } else if (event.status === "failed") {
      updateTask(taskId, {
        status: "failed",
        materialEvent: event,
      });
    } else {
      updateTask(taskId, {
        materialEvent: event,
      });
    }
  }, [event, taskId, updateTask]);

  return null;
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case "uploading":
      return <Loader2 className="size-3.5 animate-spin text-amber-500" />;
    case "processing":
      return <Loader2 className="size-3.5 animate-spin text-blue-500" />;
    case "completed":
      return <CheckCircle2 className="size-3.5 text-emerald-600" />;
    case "failed":
      return <AlertTriangle className="size-3.5 text-red-500" />;
    default:
      return null;
  }
}

function StatusLabel({ status }: { status: string }) {
  switch (status) {
    case "uploading":
      return <span className="text-[10px] text-amber-600">上传中</span>;
    case "processing":
      return <span className="text-[10px] text-blue-600">解析中</span>;
    case "completed":
      return <span className="text-[10px] text-emerald-600">已完成</span>;
    case "failed":
      return <span className="text-[10px] text-red-600">失败</span>;
    default:
      return null;
  }
}

export function GlobalUploadFloat() {
  const tasks = useUploadQueue((s) => s.tasks);
  const removeTask = useUploadQueue((s) => s.removeTask);
  const clearCompleted = useUploadQueue((s) => s.clearCompleted);

  const activeCount = tasks.filter(
    (t) => t.status === "uploading" || t.status === "processing"
  ).length;

  const sortedTasks = useMemo(
    () => [...tasks].sort((a, b) => b.createdAt - a.createdAt),
    [tasks]
  );

  if (tasks.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 group">
      {/* Hidden pollers for active tasks */}
      {sortedTasks
        .filter((t) => t.status === "processing" && t.materialEventId)
        .map((t) => (
          <TaskPoller key={t.id} taskId={t.id} eventId={t.materialEventId!} />
        ))}

      {/* Collapsed indicator */}
      <div
        className={cn(
          "flex items-center gap-2 rounded-full border border-border/60 bg-popover px-3 py-2 shadow-lg shadow-black/10 transition-all",
          "group-hover:opacity-0 group-hover:pointer-events-none group-hover:scale-95"
        )}
      >
        {activeCount > 0 ? (
          <Loader2 className="size-4 animate-spin text-amber-500" />
        ) : (
          <CheckCircle2 className="size-4 text-emerald-600" />
        )}
        <span className="text-xs font-medium text-foreground/80">
          {activeCount > 0
            ? `${activeCount} 个任务进行中`
            : `${tasks.length} 个任务`}
        </span>
      </div>

      {/* Expanded panel on hover */}
      <div
        className={cn(
          "absolute bottom-0 right-0 w-80 overflow-hidden rounded-xl border border-border/60 bg-popover shadow-xl shadow-black/15 transition-all",
          "opacity-0 pointer-events-none scale-95 origin-bottom-right",
          "group-hover:opacity-100 group-hover:pointer-events-auto group-hover:scale-100"
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border/40 px-3 py-2.5">
          <div className="flex items-center gap-2">
            <Upload className="size-3.5 text-muted-foreground/60" />
            <span className="text-xs font-medium text-foreground/80">
              上传任务
            </span>
            {activeCount > 0 && (
              <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                {activeCount}
              </span>
            )}
          </div>
          {tasks.some((t) => t.status === "completed" || t.status === "failed") && (
            <button
              type="button"
              onClick={clearCompleted}
              className="text-[10px] text-muted-foreground/60 hover:text-muted-foreground transition-colors"
            >
              清除已完成
            </button>
          )}
        </div>

        {/* Task list */}
        <div className="max-h-72 overflow-y-auto">
          {sortedTasks.map((task) => (
            <div
              key={task.id}
              className="flex items-start gap-2 border-b border-border/30 px-3 py-2.5 last:border-b-0"
            >
              <div className="mt-0.5 shrink-0">
                <StatusIcon status={task.status} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-1">
                  <span className="truncate text-xs font-medium text-foreground/80">
                    {task.caseName}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeTask(task.id)}
                    className="shrink-0 text-muted-foreground/30 hover:text-muted-foreground/70 transition-colors"
                  >
                    <X className="size-3" />
                  </button>
                </div>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <StatusLabel status={task.status} />
                  <span className="text-[10px] text-muted-foreground/50">
                    {task.categoryName}
                  </span>
                </div>
                <div className="flex items-center gap-1 mt-1">
                  <FileText className="size-3 text-muted-foreground/40" />
                  <span className="text-[10px] text-muted-foreground/50 truncate">
                    {task.fileNames.join(", ")}
                  </span>
                  <span className="text-[10px] text-muted-foreground/40 shrink-0">
                    ({task.fileNames.length})
                  </span>
                </div>
                {task.materialEvent?.change_summary && (
                  <p className="mt-1 text-[10px] text-muted-foreground/60 leading-relaxed line-clamp-2">
                    {task.materialEvent.change_summary}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

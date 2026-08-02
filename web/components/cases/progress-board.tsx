"use client";

import { AlertTriangle, Info } from "lucide-react";
import type { ProgressBoard, ReminderModel, RiskAlert } from "@/lib/types/case-analytics";
import { Card, CardContent } from "@/components/ui/card";

const LEVEL_CLASS: Record<string, string> = {
  info: "bg-sky-500/10 text-sky-600",
  warning: "bg-amber-500/10 text-amber-600",
  warn: "bg-amber-500/10 text-amber-600",
  danger: "bg-destructive/10 text-destructive",
  error: "bg-destructive/10 text-destructive",
};

function levelClass(level?: string): string {
  return LEVEL_CLASS[(level ?? "").toLowerCase()] ?? "bg-muted text-muted-foreground";
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="mt-1 text-xl font-semibold">{value}</div>
      </CardContent>
    </Card>
  );
}

interface Props {
  progress: ProgressBoard | null;
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
}

export function ProgressBoardPanel({ progress, isLoading, error, onRetry }: Props) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
        加载中…
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex flex-col items-center gap-2 py-8 text-sm text-muted-foreground">
        <span>加载进度失败:{error}</span>
        <button onClick={onRetry} className="rounded border px-2 py-1 text-xs hover:bg-muted">
          重试
        </button>
      </div>
    );
  }
  if (!progress) return null;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm">
        {progress.stage && (
          <span className="rounded bg-muted px-2 py-0.5 text-xs">{progress.stage}</span>
        )}
        {progress.status && (
          <span className="rounded bg-primary/10 px-2 py-0.5 text-xs text-primary">
            {progress.status}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Metric label="回款率" value={`${Math.round(progress.recovery_ratio_pct)}%`} />
        <Metric label="预期回款" value={`${progress.expected_recovery_total_wan} 万`} />
        <Metric label="实际回款" value={`${progress.actual_recovery_total_wan} 万`} />
        <Metric label="可分配利润" value={`${progress.profit_distributable_wan} 万`} />
        <Metric label="已分配利润" value={`${progress.profit_distributed_wan} 万`} />
      </div>

      {progress.reminders.length > 0 && (
        <section>
          <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            提醒
          </h4>
          <div className="space-y-2">
            {progress.reminders.map((r: ReminderModel, i) => (
              <div
                key={i}
                className={`flex items-start gap-2 rounded-md px-3 py-2 text-sm ${levelClass(r.level)}`}
              >
                <Info className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{r.message}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {progress.risk_alerts.length > 0 && (
        <section>
          <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            风险预警
          </h4>
          <div className="space-y-2">
            {progress.risk_alerts.map((a: RiskAlert, i) => (
              <div
                key={i}
                className={`flex items-start gap-2 rounded-md px-3 py-2 text-sm ${levelClass(a.level)}`}
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{a.message ?? JSON.stringify(a)}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

"use client";

import {
  CalendarClock,
  CircleAlert,
  CircleCheck,
  CircleHelp,
  Clock3,
  RefreshCw,
} from "lucide-react";
import type { DeadlineBoardResponse } from "@/lib/types/case-analytics";
import { useCaseDeadlineBoard } from "@/lib/hooks/use-case-deadline-board";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const GROUPS = [
  { key: "expired", label: "已过期", icon: CircleAlert },
  { key: "red", label: "紧急", icon: CircleAlert },
  { key: "yellow", label: "临近", icon: Clock3 },
  { key: "safe", label: "安全", icon: CircleCheck },
  { key: "unknown", label: "待核实", icon: CircleHelp },
] as const;

type DeadlineGroupKey = (typeof GROUPS)[number]["key"];

interface DeadlineDisplayItem {
  type: string;
  dueDate: string;
  remainingDays: number | null;
  relatedAsset: string;
  action: string;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function normalizeGroup(value: unknown): DeadlineDisplayItem[] {
  if (!Array.isArray(value)) return [];
  return value
    .map(asRecord)
    .map((item) => ({
      type: stringValue(item.type),
      dueDate: stringValue(item.due_date),
      remainingDays: numberValue(item.remaining_days) ?? null,
      relatedAsset: stringValue(item.related_asset),
      action: stringValue(item.action),
    }));
}

function remainingLabel(item: DeadlineDisplayItem): string {
  if (item.remainingDays === null) return "剩余天数未知";
  if (item.remainingDays < 0) return `已逾期 ${Math.abs(item.remainingDays)} 天`;
  if (item.remainingDays === 0) return "今天到期";
  return `剩余 ${item.remainingDays} 天`;
}

function DeadlineItemCard({ item }: { item: DeadlineDisplayItem }) {
  return (
    <Card>
      <CardHeader className="p-4 pb-2">
        <div className="flex flex-col items-start justify-between gap-1 sm:flex-row sm:gap-3">
          <CardTitle className="text-sm leading-5">{item.type || "未命名时效事项"}</CardTitle>
          <span className="shrink-0 text-xs font-medium text-muted-foreground">
            {remainingLabel(item)}
          </span>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 p-4 pt-0 text-xs text-muted-foreground">
        <p>到期日：{item.dueDate || "待核实"}</p>
        {item.relatedAsset && <p>关联标的：{item.relatedAsset}</p>}
        {item.action && <p className="text-sm leading-5 text-foreground">处置建议：{item.action}</p>}
      </CardContent>
    </Card>
  );
}

function DeadlineContent({ board }: { board: DeadlineBoardResponse }) {
  const rawGroups = asRecord(board.groups);
  const groups = Object.fromEntries(
    GROUPS.map(({ key }) => [key, normalizeGroup(rawGroups[key])])
  ) as Record<DeadlineGroupKey, DeadlineDisplayItem[]>;
  const counts = asRecord(board.counts);
  const thresholds = asRecord(board.thresholds);
  const totalItems = GROUPS.reduce(
    (total, group) => total + (groups[group.key]?.length ?? 0),
    0
  );

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-sm font-medium">司法时效总览</h2>
          <p className="text-xs text-muted-foreground">
            基准日期：{stringValue(board.today) || "未知"}
          </p>
        </div>
        <p className="text-xs text-muted-foreground">
          红色阈值 {numberValue(thresholds.red_days) ?? "-"} 天 · 黄色阈值 {numberValue(thresholds.yellow_days) ?? "-"} 天
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Card>
          <CardHeader className="p-3 pb-1">
            <CardTitle className="text-xs text-muted-foreground">全部事项</CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-0 text-xl font-semibold tabular-nums">
            {numberValue(counts.total) ?? totalItems}
          </CardContent>
        </Card>
        {GROUPS.map(({ key, label, icon: Icon }) => (
          <Card key={key}>
            <CardHeader className="flex-row items-center gap-2 p-3 pb-1">
              <Icon aria-hidden="true" />
              <CardTitle className="text-xs text-muted-foreground">{label}</CardTitle>
            </CardHeader>
            <CardContent className="p-3 pt-0 text-xl font-semibold tabular-nums">
              {numberValue(counts[key]) ?? groups[key].length}
            </CardContent>
          </Card>
        ))}
      </div>

      {totalItems === 0 ? (
        <Alert>
          <CircleCheck aria-hidden="true" />
          <div>
            <AlertTitle>暂无时效事项</AlertTitle>
            <AlertDescription>当前扫描结果没有需要展示的司法时效记录。</AlertDescription>
          </div>
        </Alert>
      ) : (
        GROUPS.map(({ key, label, icon: Icon }) => {
          const items = groups[key];
          if (items.length === 0) return null;
          return (
            <section key={key} aria-labelledby={`deadline-group-${key}`} className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <Icon aria-hidden="true" className="size-4 text-muted-foreground" />
                <h3 id={`deadline-group-${key}`} className="text-sm font-medium">
                  {label}（{items.length}）
                </h3>
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                {items.map((item, index) => (
                  <DeadlineItemCard
                    key={`${key}-${item.type}-${item.dueDate}-${index}`}
                    item={item}
                  />
                ))}
              </div>
            </section>
          );
        })
      )}
    </div>
  );
}

export function DeadlineBoard({ caseId }: { caseId: number }) {
  const { board, isLoading, error, refresh } = useCaseDeadlineBoard(caseId);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4" aria-label="正在加载司法时效看板">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-20" />
          ))}
        </div>
        <Skeleton className="h-36" />
      </div>
    );
  }

  if (error) {
    return (
      <Alert variant="destructive" className="flex-wrap">
        <CircleAlert aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <AlertTitle>时效看板加载失败</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={() => refresh()}>
          <RefreshCw data-icon="inline-start" />
          重试
        </Button>
      </Alert>
    );
  }

  if (!board) return null;

  if (!board.available) {
    return (
      <Alert>
        <CalendarClock aria-hidden="true" />
        <div>
          <AlertTitle>时效扫描暂不可用</AlertTitle>
          <AlertDescription>审计引擎当前没有返回时效数据，请稍后刷新。</AlertDescription>
        </div>
      </Alert>
    );
  }

  return <DeadlineContent board={board} />;
}

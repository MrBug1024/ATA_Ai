"use client";

import { FormEvent, useId, useState } from "react";
import { History, LoaderCircle, Plus, RefreshCw, Undo2 } from "lucide-react";
import { toast } from "sonner";
import type { CorrectionModel } from "@/lib/types/case-analytics";
import { useCaseCorrections } from "@/lib/hooks/use-case-corrections";
import { useCreateCorrection } from "@/lib/hooks/use-create-correction";
import { useRevokeCorrection } from "@/lib/hooks/use-revoke-correction";
import { useAuth } from "@/lib/hooks/use-auth";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

const STATUS_LABELS: Record<string, string> = {
  active: "有效",
  superseded: "已被覆盖",
  revoked: "已撤销",
};

function formatDate(value: string | null): string {
  if (!value) return "时间未知";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function CorrectionCard({
  correction,
  revoking,
  onRevoke,
}: {
  correction: CorrectionModel;
  revoking: boolean;
  onRevoke: (id: number) => void;
}) {
  return (
    <Card aria-label={`订正：${correction.target}`}>
      <CardHeader className="flex-row items-start justify-between gap-3 p-4 pb-2">
        <div className="min-w-0 flex-1">
          <CardTitle className="truncate text-sm leading-5">{correction.target}</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            {STATUS_LABELS[correction.status] ?? correction.status} · {correction.scope || "全案"}
          </p>
        </div>
        {correction.status === "active" && (
          <Button
            type="button"
            variant="destructive"
            size="xs"
            disabled={revoking}
            onClick={() => onRevoke(correction.id)}
            aria-label={`撤销订正 ${correction.target}`}
          >
            {revoking ? (
              <LoaderCircle data-icon="inline-start" className="animate-spin" />
            ) : (
              <Undo2 data-icon="inline-start" />
            )}
            撤销
          </Button>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3 p-4 pt-0">
        <p className="whitespace-pre-wrap text-sm leading-6">{correction.instruction}</p>
        {correction.source_query && (
          <div className="rounded-md bg-muted p-3 text-xs text-muted-foreground">
            原始话术：{correction.source_query}
          </div>
        )}
        <p className="text-xs text-muted-foreground">
          {correction.operator_name || "操作人未知"} · {formatDate(correction.created_at)}
          {correction.superseded_by ? ` · 被订正 #${correction.superseded_by} 覆盖` : ""}
        </p>
      </CardContent>
    </Card>
  );
}

export function CorrectionsPanel({ caseId }: { caseId: number }) {
  const formId = useId();
  const [includeHistory, setIncludeHistory] = useState(false);
  const [target, setTarget] = useState("");
  const [instruction, setInstruction] = useState("");
  const [sourceQuery, setSourceQuery] = useState("");
  const [scope, setScope] = useState("全案");
  const [revokingId, setRevokingId] = useState<number | null>(null);
  const { user } = useAuth();

  const { corrections, isLoading, error, refresh } = useCaseCorrections(
    caseId,
    includeHistory
  );
  const { create, isMutating: isCreating, error: createError } =
    useCreateCorrection(caseId);
  const { revoke, isMutating: isRevoking } = useRevokeCorrection(caseId);

  const canCreate = target.trim().length > 0 && instruction.trim().length > 0;

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canCreate) return;

    try {
      await create({
        target: target.trim(),
        instruction: instruction.trim(),
        source_query: sourceQuery.trim(),
        scope: scope.trim() || "全案",
        operator_id: user?.user_id || undefined,
        operator_name: user?.username || undefined,
      });
      void Promise.resolve(refresh()).catch(() => undefined);
      setTarget("");
      setInstruction("");
      setSourceQuery("");
      setScope("全案");
      toast.success("权威订正已生效");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "新增订正失败");
    }
  };

  const handleRevoke = async (correctionId: number) => {
    setRevokingId(correctionId);
    try {
      await revoke(correctionId);
      void Promise.resolve(refresh()).catch(() => undefined);
      toast.success("订正已撤销");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "撤销订正失败");
    } finally {
      setRevokingId(null);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardHeader className="p-4 pb-3">
          <CardTitle className="text-sm">新增权威订正</CardTitle>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          <form onSubmit={handleCreate}>
            <FieldGroup>
              <FieldGroup className="grid gap-4 md:grid-cols-[minmax(0,1fr)_12rem]">
                <Field>
                  <FieldLabel htmlFor={`${formId}-target`}>订正标的</FieldLabel>
                  <Input
                    id={`${formId}-target`}
                    value={target}
                    onChange={(event) => setTarget(event.target.value)}
                    placeholder="例如：某房产估值结论"
                    required
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor={`${formId}-scope`}>生效范围</FieldLabel>
                  <Input
                    id={`${formId}-scope`}
                    value={scope}
                    onChange={(event) => setScope(event.target.value)}
                    placeholder="全案"
                  />
                </Field>
              </FieldGroup>
              <Field>
                <FieldLabel htmlFor={`${formId}-instruction`}>强制修正指令</FieldLabel>
                <Textarea
                  id={`${formId}-instruction`}
                  value={instruction}
                  onChange={(event) => setInstruction(event.target.value)}
                  placeholder="写明后续审计必须采用的事实或结论"
                  rows={3}
                  required
                />
                <FieldDescription>同一标的的新订正会覆盖旧的有效订正，历史记录仍可追溯。</FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor={`${formId}-source-query`}>原始话术（选填）</FieldLabel>
                <Textarea
                  id={`${formId}-source-query`}
                  value={sourceQuery}
                  onChange={(event) => setSourceQuery(event.target.value)}
                  placeholder="记录触发本次订正的原始描述"
                  rows={2}
                />
              </Field>
              {createError && (
                <Alert variant="destructive">
                  <AlertDescription>{createError}</AlertDescription>
                </Alert>
              )}
              <Field orientation="horizontal" className="justify-end">
                <Button type="submit" disabled={!canCreate || isCreating}>
                  {isCreating ? (
                    <LoaderCircle data-icon="inline-start" className="animate-spin" />
                  ) : (
                    <Plus data-icon="inline-start" />
                  )}
                  {isCreating ? "提交中" : "新增订正"}
                </Button>
              </Field>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>

      <section aria-labelledby="corrections-list-title" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 id="corrections-list-title" className="text-sm font-medium">
              订正记录
            </h2>
            <p className="text-xs text-muted-foreground">
              {includeHistory ? "包含已覆盖和已撤销记录" : "仅显示当前生效记录"}
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-pressed={includeHistory}
            onClick={() => setIncludeHistory((current) => !current)}
          >
            <History data-icon="inline-start" />
            {includeHistory ? "仅看有效" : "查看历史"}
          </Button>
        </div>

        {isLoading ? (
          <div className="grid gap-3 lg:grid-cols-2" aria-label="正在加载订正记录">
            <Skeleton className="h-32" />
            <Skeleton className="h-32" />
          </div>
        ) : error ? (
          <Alert variant="destructive" className="flex-wrap">
            <div className="min-w-0 flex-1">
              <AlertTitle>订正记录加载失败</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={() => refresh()}>
              <RefreshCw data-icon="inline-start" />
              重试
            </Button>
          </Alert>
        ) : corrections.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">暂无订正记录</p>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {corrections.map((correction) => (
              <CorrectionCard
                key={correction.id}
                correction={correction}
                revoking={isRevoking && revokingId === correction.id}
                onRevoke={handleRevoke}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

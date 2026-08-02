"use client";

import { useState } from "react";
import { toast } from "sonner";
import type { RecoveryRecord } from "@/lib/types/case-analytics";
import { useCaseRecovery } from "@/lib/hooks/use-case-recovery";
import { useConfirmRecovery } from "@/lib/hooks/use-confirm-recovery";
import { useCreateRecovery } from "@/lib/hooks/use-create-recovery";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function statusClass(status: string): string {
  if (status === "confirmed") return "bg-emerald-500/10 text-emerald-600";
  if (status === "pending") return "bg-amber-500/10 text-amber-600";
  return "bg-muted text-muted-foreground";
}

function statusLabel(status: string): string {
  if (status === "pending") return "待确认";
  if (status === "confirmed") return "已确认";
  return status;
}

export function RecoveryPanel({ caseId }: { caseId: number }) {
  const { records, isLoading, error, refresh } = useCaseRecovery(caseId);
  const { confirm, isMutating: confirming } = useConfirmRecovery(caseId);
  const { create, isMutating: creating } = useCreateRecovery(caseId);

  const [amount, setAmount] = useState("");
  const [recoveredAt, setRecoveredAt] = useState("");
  const [sourceDesc, setSourceDesc] = useState("");

  const onConfirm = async (id: number) => {
    try {
      await confirm(id);
      toast.success("已确认收款");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "确认失败");
    }
  };

  const onCreate = async () => {
    const amt = Number(amount);
    if (!amt || !recoveredAt) {
      toast.error("请填写金额与收款日期");
      return;
    }
    try {
      await create({ amount: amt, recovered_at: recoveredAt, source_desc: sourceDesc });
      toast.success("已记录收款");
      setAmount("");
      setRecoveredAt("");
      setSourceDesc("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "记录失败");
    }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-md border p-3">
        <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          记一笔收款
        </h4>
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">金额(元)</label>
            <Input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="h-8 w-32"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">收款日期</label>
            <Input
              type="date"
              value={recoveredAt}
              onChange={(e) => setRecoveredAt(e.target.value)}
              className="h-8 w-40"
            />
          </div>
          <div className="flex flex-1 flex-col gap-1">
            <label className="text-xs text-muted-foreground">来源说明</label>
            <Input
              value={sourceDesc}
              onChange={(e) => setSourceDesc(e.target.value)}
              className="h-8"
            />
          </div>
          <Button size="sm" className="h-8" onClick={onCreate} disabled={creating}>
            {creating ? "提交中…" : "添加"}
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="py-8 text-center text-sm text-muted-foreground">加载中…</div>
      ) : error ? (
        <div className="flex flex-col items-center gap-2 py-8 text-sm text-muted-foreground">
          <span>加载回款明细失败:{error}</span>
          <button
            onClick={() => refresh()}
            className="rounded border px-2 py-1 text-xs hover:bg-muted"
          >
            重试
          </button>
        </div>
      ) : records.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">暂无回款记录</div>
      ) : (
        <div className="space-y-2">
          {records.map((r: RecoveryRecord) => (
            <div key={r.id} className="flex items-center gap-3 rounded-md border p-3">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">¥{r.amount.toLocaleString("zh-CN")}</span>
                  <span className={`rounded px-1.5 py-0.5 text-xs ${statusClass(r.status)}`}>
                    {statusLabel(r.status)}
                  </span>
                  {r.origin === "auto" && (
                    <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                      自动抽取
                    </span>
                  )}
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  {r.recovered_at?.slice(0, 10) ?? "—"}
                  {r.source_desc ? ` · ${r.source_desc}` : ""}
                </div>
              </div>
              {r.status === "pending" && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs"
                  onClick={() => onConfirm(r.id)}
                  disabled={confirming}
                >
                  确认
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

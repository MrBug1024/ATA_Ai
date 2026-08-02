"use client";

import { useState } from "react";
import { toast } from "sonner";
import type { ForecastItem } from "@/lib/types/case-analytics";
import { useCaseForecast } from "@/lib/hooks/use-case-forecast";
import { useSeedForecast } from "@/lib/hooks/use-seed-forecast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  caseId: number;
  reportRef: string | null;
}

export function ForecastPanel({ caseId, reportRef }: Props) {
  const { forecasts, isLoading, error, refresh } = useCaseForecast(caseId);
  const { seed, isMutating } = useSeedForecast(caseId);

  const [tranche, setTranche] = useState("");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");

  const onAdd = async () => {
    if (!reportRef) {
      toast.error("缺少报告引用,无法写入预期回款");
      return;
    }
    const amt = Number(amount);
    if (!tranche || !amt) {
      toast.error("请填写期次与预期金额");
      return;
    }
    const next: ForecastItem = {
      tranche,
      expected_amount: amt,
      expected_date: date || null,
      basis: "",
    };
    try {
      await seed({ report_ref: reportRef, tranches: [...forecasts, next] });
      toast.success("已写入预期回款");
      setTranche("");
      setAmount("");
      setDate("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "写入失败");
    }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-md border p-3">
        <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          添加预期回款
        </h4>
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">期次</label>
            <Input
              value={tranche}
              onChange={(e) => setTranche(e.target.value)}
              className="h-8 w-28"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">预期金额(元)</label>
            <Input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="h-8 w-32"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">预期日期</label>
            <Input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="h-8 w-40"
            />
          </div>
          <Button size="sm" className="h-8" onClick={onAdd} disabled={isMutating || !reportRef}>
            {isMutating ? "提交中…" : "添加"}
          </Button>
        </div>
        {!reportRef && (
          <p className="mt-2 text-xs text-muted-foreground">无可用报告引用,暂不能写入。</p>
        )}
      </div>

      {isLoading ? (
        <div className="py-8 text-center text-sm text-muted-foreground">加载中…</div>
      ) : error ? (
        <div className="flex flex-col items-center gap-2 py-8 text-sm text-muted-foreground">
          <span>加载预期回款失败:{error}</span>
          <button
            onClick={() => refresh()}
            className="rounded border px-2 py-1 text-xs hover:bg-muted"
          >
            重试
          </button>
        </div>
      ) : forecasts.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">暂无预期回款</div>
      ) : (
        <div className="space-y-2">
          {forecasts.map((f: ForecastItem, i) => (
            <div key={i} className="flex items-center gap-3 rounded-md border p-3">
              <span className="rounded bg-muted px-1.5 py-0.5 text-xs">{f.tranche}</span>
              <span className="text-sm font-medium">
                ¥{Number(f.expected_amount).toLocaleString("zh-CN")}
              </span>
              <span className="text-xs text-muted-foreground">
                {f.expected_date?.slice(0, 10) ?? "未定"}
              </span>
              {f.basis && <span className="text-xs text-muted-foreground">· {f.basis}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

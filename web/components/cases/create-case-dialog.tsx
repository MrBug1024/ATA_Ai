"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { createCase } from "@/lib/backend/cases";

const CASE_TYPES = ["年度财务报表审计"];

interface CreateCasePayload {
  case_name: string;
  case_type: string;
  entity_name: string;
  company_id: string;
  entity_uscc: string;
  fiscal_year: string;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}

const EMPTY: CreateCasePayload = {
  case_name: "",
  case_type: CASE_TYPES[0],
  entity_name: "",
  company_id: "co_annual_local",
  entity_uscc: "",
  fiscal_year: String(new Date().getFullYear() - 1),
};

export function CreateCaseDialog({ open, onOpenChange, onCreated }: Props) {
  const [form, setForm] = useState<CreateCasePayload>(EMPTY);
  const [submitting, setSubmitting] = useState(false);

  const set = (field: keyof CreateCasePayload, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  const handleClose = (next: boolean) => {
    if (!next) setForm(EMPTY);
    onOpenChange(next);
  };

  const handleSubmit = async () => {
    if (!form.case_name.trim() || !form.case_type || !form.entity_name.trim() || !form.fiscal_year) return;
    setSubmitting(true);
    try {
      const result = await createCase({
        case_name: form.case_name.trim(),
        case_type: form.case_type,
        entity_name: form.entity_name.trim(),
        company_id: form.company_id.trim(),
        entity_uscc: form.entity_uscc.trim() || undefined,
        fiscal_year: Number(form.fiscal_year),
      });
      toast.success(result.message ?? `年审项目 #${result.case_id} 已创建`);
      handleClose(false);
      onCreated();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "创建失败，请重试");
    } finally {
      setSubmitting(false);
    }
  };

  const canSubmit =
    form.case_name.trim().length > 0 &&
    form.entity_name.trim().length > 0 &&
    form.company_id.trim().length > 0 &&
    Number(form.fiscal_year) >= 2000 &&
    !submitting;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle className="text-base">创建年审项目</DialogTitle>
          <DialogDescription className="sr-only">
            录入被审计单位、审计年度和项目基本信息。
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <Field label="项目名称" required>
            <input
              value={form.case_name}
              onChange={(e) => set("case_name", e.target.value)}
              placeholder="例如：某某公司 2025 年度财务报表审计"
              className="w-full rounded-md border border-border/50 bg-background px-3 py-2 text-sm placeholder:text-muted-foreground/40 outline-none focus:border-border"
            />
          </Field>

          <Field label="业务类型" required>
            <select
              value={form.case_type}
              onChange={(e) => set("case_type", e.target.value)}
              className="w-full rounded-md border border-border/50 bg-background px-3 py-2 text-sm outline-none focus:border-border"
            >
              {CASE_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </Field>

          <Field label="被审计单位" required>
            <input
              value={form.entity_name}
              onChange={(e) => set("entity_name", e.target.value)}
              placeholder="请输入被审计单位全称"
              className="w-full rounded-md border border-border/50 bg-background px-3 py-2 text-sm placeholder:text-muted-foreground/40 outline-none focus:border-border"
            />
          </Field>

          <Field label="机构标识" required>
            <input
              value={form.company_id}
              onChange={(e) => set("company_id", e.target.value)}
              placeholder="请输入公司/机构 ID"
              className="w-full rounded-md border border-border/50 bg-background px-3 py-2 text-sm placeholder:text-muted-foreground/40 outline-none focus:border-border"
            />
          </Field>

          <Field label="审计年度" required>
            <input
              type="number"
              min="2000"
              max="2200"
              value={form.fiscal_year}
              onChange={(e) => set("fiscal_year", e.target.value)}
              className="w-full rounded-md border border-border/50 bg-background px-3 py-2 text-sm outline-none focus:border-border"
            />
          </Field>

          <Field label="统一社会信用代码">
            <input
              value={form.entity_uscc}
              onChange={(e) => set("entity_uscc", e.target.value)}
              placeholder="选填"
              className="w-full rounded-md border border-border/50 bg-background px-3 py-2 text-sm placeholder:text-muted-foreground/40 outline-none focus:border-border font-mono"
            />
          </Field>
        </div>

        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={() => handleClose(false)} disabled={submitting}>
            取消
          </Button>
          <Button size="sm" onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? "创建中…" : "创建"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium text-muted-foreground/80">
        {label}
        {required && <span className="ml-0.5 text-destructive">*</span>}
      </label>
      {children}
    </div>
  );
}

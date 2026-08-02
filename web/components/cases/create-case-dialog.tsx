"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { createCase } from "@/lib/backend/cases";

const CASE_TYPES = ["破产重整", "破产清算", "破产和解"];

interface CreateCasePayload {
  case_name: string;
  case_type: string;
  debtor_name: string;
  debtor_uscc: string;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}

const EMPTY: CreateCasePayload = {
  case_name: "",
  case_type: CASE_TYPES[0],
  debtor_name: "",
  debtor_uscc: "",
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
    if (!form.case_name.trim() || !form.case_type) return;
    setSubmitting(true);
    try {
      const result = await createCase({
        case_name: form.case_name.trim(),
        case_type: form.case_type,
        debtor_name: form.debtor_name.trim() || undefined,
        debtor_uscc: form.debtor_uscc.trim() || undefined,
      });
      toast.success(result.message ?? `案件 #${result.case_id} 已创建`);
      handleClose(false);
      onCreated();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "创建失败，请重试");
    } finally {
      setSubmitting(false);
    }
  };

  const canSubmit = form.case_name.trim().length > 0 && !submitting;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle className="text-base">创建案件</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <Field label="案件名称" required>
            <input
              value={form.case_name}
              onChange={(e) => set("case_name", e.target.value)}
              placeholder="请输入案件名称"
              className="w-full rounded-md border border-border/50 bg-background px-3 py-2 text-sm placeholder:text-muted-foreground/40 outline-none focus:border-border"
            />
          </Field>

          <Field label="案件类型" required>
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

          <Field label="债务人名称">
            <input
              value={form.debtor_name}
              onChange={(e) => set("debtor_name", e.target.value)}
              placeholder="选填"
              className="w-full rounded-md border border-border/50 bg-background px-3 py-2 text-sm placeholder:text-muted-foreground/40 outline-none focus:border-border"
            />
          </Field>

          <Field label="统一社会信用代码">
            <input
              value={form.debtor_uscc}
              onChange={(e) => set("debtor_uscc", e.target.value)}
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

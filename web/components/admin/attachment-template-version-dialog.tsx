"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type {
  AttachmentTemplateBusinessType,
  AttachmentTemplateVersionSummary,
} from "@/lib/backend/attachment-templates";
import {
  useCreateAttachmentTemplateVersion,
  useUpdateAttachmentTemplateVersion,
} from "@/lib/hooks/use-attachment-templates";

interface AttachmentTemplateVersionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  businessTypes: AttachmentTemplateBusinessType[];
  version?: AttachmentTemplateVersionSummary | null;
}

export function AttachmentTemplateVersionDialog({
  open,
  onOpenChange,
  businessTypes,
  version = null,
}: AttachmentTemplateVersionDialogProps) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [businessType, setBusinessType] = useState("");
  const [description, setDescription] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const createMutation = useCreateAttachmentTemplateVersion();
  const updateMutation = useUpdateAttachmentTemplateVersion(version?.id ?? "__new__");
  const editing = Boolean(version);
  const isSaving = createMutation.isMutating || updateMutation.isMutating;
  const requestError = createMutation.error || updateMutation.error;

  useEffect(() => {
    if (!open) return;
    setName(version?.name ?? "");
    setBusinessType(version?.business_type ?? businessTypes[0]?.code ?? "");
    setDescription(version?.description ?? "");
    setSubmitted(false);
    createMutation.reset();
    updateMutation.reset();
  }, [
    open,
    version,
    businessTypes,
    createMutation.reset,
    updateMutation.reset,
  ]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
    const normalizedName = name.trim();
    if (!normalizedName || !businessType) return;
    try {
      if (version) {
        await updateMutation.updateVersion({
          name: normalizedName,
          description: description.trim(),
          revision: version.revision,
        });
        toast.success("模板版本信息已更新");
        onOpenChange(false);
        return;
      }
      const created = await createMutation.createVersion({
        name: normalizedName,
        business_type: businessType,
        description: description.trim(),
      });
      toast.success(`${created.version_label} 已创建，请上传模板文件`);
      onOpenChange(false);
      router.push(`/admin/templates/${encodeURIComponent(created.id)}`);
    } catch {
      // The mutation error is rendered below the form.
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !isSaving && onOpenChange(next)}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{editing ? "编辑模板版本" : "创建模板版本"}</DialogTitle>
          <DialogDescription>
            {editing
              ? "草稿的名称和描述可以修改，业务类型及版本号保持不变。"
              : "服务端会为业务类型分配下一个版本号，创建后再上传模板文件。"}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-5">
          <FieldGroup>
            <Field data-invalid={(submitted && !name.trim()) || undefined}>
              <FieldLabel htmlFor="attachment-template-name">版本名称</FieldLabel>
              <Input
                id="attachment-template-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={isSaving}
                placeholder="例如：2026 年度一般企业模板"
                autoFocus
              />
              {submitted && !name.trim() && <FieldError>请输入版本名称</FieldError>}
            </Field>
            <Field data-invalid={(submitted && !businessType) || undefined}>
              <FieldLabel htmlFor="attachment-template-business-type">业务类型</FieldLabel>
              <Select
                value={businessType}
                onValueChange={setBusinessType}
                disabled={editing || isSaving}
              >
                <SelectTrigger id="attachment-template-business-type" className="w-full">
                  <SelectValue placeholder="选择业务类型" />
                </SelectTrigger>
                <SelectContent>
                  {businessTypes.map((item) => (
                    <SelectItem key={item.code} value={item.code}>
                      {item.label}{item.generator_enabled ? "" : "（生成能力未启用）"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {submitted && !businessType && <FieldError>请选择业务类型</FieldError>}
            </Field>
            <Field>
              <FieldLabel htmlFor="attachment-template-description">描述</FieldLabel>
              <Textarea
                id="attachment-template-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                disabled={isSaving}
                rows={4}
                placeholder="记录适用企业、期间或模板来源等管理说明"
              />
            </Field>
          </FieldGroup>
          {requestError && (
            <Alert variant="destructive">
              <AlertDescription>{requestError}</AlertDescription>
            </Alert>
          )}
          <DialogFooter className="gap-2 sm:gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSaving}>
              取消
            </Button>
            <Button type="submit" disabled={isSaving}>
              {isSaving && <Loader2 className="animate-spin" data-icon="inline-start" />}
              {isSaving ? "保存中…" : editing ? "保存更改" : "创建并继续"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

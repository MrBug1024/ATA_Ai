"use client";

import { useEffect, useState } from "react";
import {
  Building2,
  CircleAlert,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  WandSparkles,
} from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import type {
  CompanyRecord,
  CompanyStatus,
  CompanyUpsertRequest,
} from "@/lib/backend/admin";
import {
  useAdminCompanies,
  useGenerateCompanyId,
  useSaveCompany,
} from "@/lib/hooks/use-admin";

interface CompanyFormValues {
  company_name: string;
  company_type: string;
  status: CompanyStatus;
  notes: string;
}

const EMPTY_FORM: CompanyFormValues = {
  company_name: "",
  company_type: "",
  status: "active",
  notes: "",
};

function isCompanyStatus(value: string): value is CompanyStatus {
  return value === "active" || value === "disabled";
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function CompanyTableSkeleton() {
  return (
    <div className="flex flex-col gap-3 p-4">
      {Array.from({ length: 5 }, (_, index) => (
        <Skeleton key={index} className="h-10 w-full" />
      ))}
    </div>
  );
}

interface CompanyDialogProps {
  open: boolean;
  company: CompanyRecord | null;
  onOpenChange: (open: boolean) => void;
  onSaved: () => Promise<unknown> | unknown;
}

function CompanyDialog({
  open,
  company,
  onOpenChange,
  onSaved,
}: CompanyDialogProps) {
  const [form, setForm] = useState<CompanyFormValues>(EMPTY_FORM);
  const [submitted, setSubmitted] = useState(false);
  const { saveCompany, isMutating, error, reset } = useSaveCompany();
  const companyIdMutation = useGenerateCompanyId();
  const isEditing = Boolean(company);
  const nameInvalid = submitted && form.company_name.trim().length === 0;

  useEffect(() => {
    if (!open) return;
    setForm(
      company
        ? {
            company_name: company.company_name,
            company_type: company.company_type ?? "",
            status: company.status,
            notes: company.notes ?? "",
          }
        : EMPTY_FORM
    );
    setSubmitted(false);
    reset();
    companyIdMutation.reset();
  }, [company, open, reset, companyIdMutation.reset]);

  const setValue = <Key extends keyof CompanyFormValues>(
    key: Key,
    value: CompanyFormValues[Key]
  ) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (isMutating) return;
    onOpenChange(nextOpen);
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    const companyName = form.company_name.trim();
    if (!companyName) return;

    const request: CompanyUpsertRequest = {
      company_id:
        company?.company_id ??
        (companyIdMutation.data?.company_name === companyName
          ? companyIdMutation.data.company_id
          : undefined),
      company_name: companyName,
      company_type: form.company_type.trim(),
      status: form.status,
      notes: form.notes.trim(),
    };

    try {
      await saveCompany(request);
      toast.success(isEditing ? "公司信息已更新" : "公司已创建");
      onOpenChange(false);
      void Promise.resolve(onSaved()).catch(() => {
        toast.warning("公司已保存，但列表刷新失败，请手动重试");
      });
    } catch (saveError) {
      toast.error(saveError instanceof Error ? saveError.message : "保存公司失败");
    }
  };

  const handleGenerateCompanyId = async () => {
    const companyName = form.company_name.trim();
    setSubmitted(true);
    if (!companyName) return;
    try {
      await companyIdMutation.generateCompanyId(companyName);
    } catch (generateError) {
      toast.error(
        generateError instanceof Error ? generateError.message : "生成公司 ID 失败"
      );
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEditing ? "编辑公司" : "创建公司"}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? `更新 ${company?.company_name ?? "公司"} 的基础信息和状态。`
              : "创建新的公司目录项，公司 ID 将由后端生成。"}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex flex-col gap-5">
          <FieldGroup>
            <Field
              data-invalid={nameInvalid || undefined}
              data-disabled={isMutating || undefined}
            >
              <FieldLabel htmlFor="company-name">公司名称</FieldLabel>
              <Input
                id="company-name"
                value={form.company_name}
                onChange={(event) => {
                  setValue("company_name", event.target.value);
                  companyIdMutation.reset();
                }}
                aria-invalid={nameInvalid || undefined}
                disabled={isMutating}
                autoFocus
                required
              />
              {nameInvalid && <FieldError>请输入公司名称</FieldError>}
            </Field>

            {!isEditing && (
              <Field data-disabled={isMutating || undefined}>
                <FieldLabel>公司 ID</FieldLabel>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Input
                    value={companyIdMutation.data?.company_id ?? ""}
                    placeholder="可由后端根据公司名称生成"
                    readOnly
                    aria-label="生成的公司 ID"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    disabled={isMutating || companyIdMutation.isMutating}
                    onClick={handleGenerateCompanyId}
                  >
                    {companyIdMutation.isMutating ? (
                      <Loader2 className="animate-spin" data-icon="inline-start" />
                    ) : (
                      <WandSparkles data-icon="inline-start" />
                    )}
                    生成 ID
                  </Button>
                </div>
                <FieldDescription>
                  可先预览并在创建时提交；不生成则由保存接口决定默认 ID。
                </FieldDescription>
                {companyIdMutation.error && (
                  <FieldError>{companyIdMutation.error}</FieldError>
                )}
              </Field>
            )}

            <Field data-disabled={isMutating || undefined}>
              <FieldLabel htmlFor="company-type">公司类型</FieldLabel>
              <Input
                id="company-type"
                value={form.company_type}
                onChange={(event) => setValue("company_type", event.target.value)}
                placeholder="例如：律所、资产管理公司"
                disabled={isMutating}
              />
            </Field>

            <Field data-disabled={isMutating || undefined}>
              <FieldLabel htmlFor="company-status">状态</FieldLabel>
              <Select
                value={form.status}
                onValueChange={(value) => {
                  if (isCompanyStatus(value)) setValue("status", value);
                }}
                disabled={isMutating}
              >
                <SelectTrigger id="company-status" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="active">启用</SelectItem>
                    <SelectItem value="disabled">停用</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
              <FieldDescription>
                停用后公司仍保留在目录中，不会执行删除操作。
              </FieldDescription>
            </Field>

            <Field data-disabled={isMutating || undefined}>
              <FieldLabel htmlFor="company-notes">备注</FieldLabel>
              <Textarea
                id="company-notes"
                value={form.notes}
                onChange={(event) => setValue("notes", event.target.value)}
                placeholder="补充公司背景、管理说明等信息"
                disabled={isMutating}
                rows={4}
              />
            </Field>
          </FieldGroup>

          {error && (
            <Alert variant="destructive">
              <CircleAlert aria-hidden="true" />
              <div>
                <AlertTitle>保存失败</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </div>
            </Alert>
          )}

          <DialogFooter className="gap-2 sm:gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={isMutating}
            >
              取消
            </Button>
            <Button type="submit" disabled={isMutating}>
              {isMutating && (
                <Loader2 className="animate-spin" data-icon="inline-start" />
              )}
              {isMutating ? "保存中…" : "保存"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function CompanyManagement() {
  const { companies, isLoading, error, refresh } = useAdminCompanies(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingCompany, setEditingCompany] = useState<CompanyRecord | null>(null);

  const openCreateDialog = () => {
    setEditingCompany(null);
    setDialogOpen(true);
  };

  const openEditDialog = (company: CompanyRecord) => {
    setEditingCompany(company);
    setDialogOpen(true);
  };

  return (
    <section className="flex flex-col gap-6" aria-labelledby="company-management-title">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex flex-col gap-1">
          <h2 id="company-management-title" className="text-xl font-semibold">
            公司管理
          </h2>
          <p className="text-sm text-muted-foreground">
            维护公司名称、类型、状态和备注。停用项仍会显示在列表中。
          </p>
        </div>
        <Button type="button" onClick={openCreateDialog}>
          <Plus data-icon="inline-start" />
          创建公司
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <CircleAlert aria-hidden="true" />
          <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <AlertTitle>
                {companies.length > 0 ? "公司列表刷新失败" : "公司列表加载失败"}
              </AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                void Promise.resolve(refresh()).catch(() => undefined)
              }
            >
              <RefreshCw data-icon="inline-start" />
              重试
            </Button>
          </div>
        </Alert>
      )}

      {isLoading && companies.length === 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">公司目录</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <CompanyTableSkeleton />
          </CardContent>
        </Card>
      )}

      {!isLoading && !error && companies.length === 0 && (
        <Empty className="min-h-72 border border-dashed">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Building2 />
            </EmptyMedia>
            <EmptyTitle>暂无公司</EmptyTitle>
            <EmptyDescription>
              创建第一家公司后，即可在用户管理中关联所属组织。
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button type="button" onClick={openCreateDialog}>
              <Plus data-icon="inline-start" />
              创建公司
            </Button>
          </EmptyContent>
        </Empty>
      )}

      {companies.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="text-base">公司目录</CardTitle>
              <Badge variant="secondary">共 {companies.length} 家</Badge>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>公司</TableHead>
                  <TableHead className="hidden md:table-cell">公司 ID</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="hidden lg:table-cell">备注</TableHead>
                  <TableHead className="hidden xl:table-cell">更新时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {companies.map((company) => (
                  <TableRow key={company.company_id}>
                    <TableCell>
                      <div className="flex min-w-48 flex-col gap-0.5">
                        <span className="font-medium">{company.company_name}</span>
                        <span className="text-xs text-muted-foreground">
                          {company.company_type || "未设置类型"}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="hidden font-mono text-xs text-muted-foreground md:table-cell">
                      {company.company_id}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={company.status === "active" ? "secondary" : "outline"}
                      >
                        {company.status === "active" ? "启用" : "停用"}
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden lg:table-cell">
                      <span className="block max-w-64 truncate text-muted-foreground">
                        {company.notes || "—"}
                      </span>
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground xl:table-cell">
                      {formatDate(company.updated_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => openEditDialog(company)}
                      >
                        <Pencil data-icon="inline-start" />
                        编辑
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <CompanyDialog
        open={dialogOpen}
        company={editingCompany}
        onOpenChange={setDialogOpen}
        onSaved={refresh}
      />
    </section>
  );
}

"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArchiveRestore,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Copy,
  Eye,
  FileStack,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
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
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
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
import type {
  AttachmentTemplateVersionStatus,
  AttachmentTemplateVersionSummary,
} from "@/lib/backend/attachment-templates";
import {
  useAttachmentTemplateBusinessTypes,
  useAttachmentTemplateVersions,
  useCloneAttachmentTemplateVersion,
  useDeleteAttachmentTemplateVersion,
  useSetAttachmentTemplateVersionActivation,
} from "@/lib/hooks/use-attachment-templates";
import { AttachmentTemplateVersionDialog } from "./attachment-template-version-dialog";

const PAGE_SIZE = 25;

const STATUS_LABELS: Record<AttachmentTemplateVersionStatus, string> = {
  draft: "草稿",
  validating: "校验中",
  ready: "可激活",
  active: "已激活",
  retired: "已停用",
  archived: "已归档",
};

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function statusVariant(status: AttachmentTemplateVersionStatus) {
  if (status === "active") return "default" as const;
  if (status === "ready") return "secondary" as const;
  if (status === "archived") return "outline" as const;
  if (status === "validating") return "secondary" as const;
  return "outline" as const;
}

function VersionActions({
  version,
  onEdit,
}: {
  version: AttachmentTemplateVersionSummary;
  onEdit: () => void;
}) {
  const router = useRouter();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const cloneMutation = useCloneAttachmentTemplateVersion(version.id);
  const deleteMutation = useDeleteAttachmentTemplateVersion(version.id);
  const activationMutation = useSetAttachmentTemplateVersionActivation(version.id);
  const busy =
    cloneMutation.isMutating ||
    deleteMutation.isMutating ||
    activationMutation.isMutating;

  async function clone() {
    try {
      const created = await cloneMutation.cloneVersion({});
      toast.success(`${created.version_label} 草稿已创建`);
      router.push(`/admin/templates/${encodeURIComponent(created.id)}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "复制模板版本失败");
    }
  }

  async function remove() {
    try {
      await deleteMutation.deleteVersion(version.revision);
      toast.success("模板草稿已删除");
      setDeleteOpen(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除模板草稿失败");
    }
  }

  async function deactivate() {
    try {
      await activationMutation.setActivation({ active: false, revision: version.revision });
      toast.success("模板版本已停用");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "更新激活状态失败");
    }
  }

  return (
    <div className="flex justify-end gap-1">
      <Button asChild type="button" size="icon-sm" variant="ghost" title="查看详情">
        <Link href={`/admin/templates/${encodeURIComponent(version.id)}`}>
          <Eye />
          <span className="sr-only">查看 {version.name}</span>
        </Link>
      </Button>
      {version.status === "draft" && (
        <Button type="button" size="icon-sm" variant="ghost" title="编辑草稿" onClick={onEdit} disabled={busy}>
          <Pencil />
          <span className="sr-only">编辑 {version.name}</span>
        </Button>
      )}
      {version.status !== "draft" && version.status !== "validating" && (
        <Button type="button" size="icon-sm" variant="ghost" title="复制为新版本" onClick={() => void clone()} disabled={busy}>
          <Copy />
          <span className="sr-only">复制 {version.name}</span>
        </Button>
      )}
      {version.status === "active" && (
        <Button type="button" size="icon-sm" variant="ghost" title="停用" onClick={() => void deactivate()} disabled={busy}>
          <ArchiveRestore />
          <span className="sr-only">停用 {version.name}</span>
        </Button>
      )}
      {version.status === "draft" && (
        <Button type="button" size="icon-sm" variant="ghost" title="删除草稿" onClick={() => setDeleteOpen(true)} disabled={busy}>
          <Trash2 />
          <span className="sr-only">删除 {version.name}</span>
        </Button>
      )}

      <Dialog open={deleteOpen} onOpenChange={(open) => !busy && setDeleteOpen(open)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>删除模板草稿</DialogTitle>
            <DialogDescription>
              将删除“{version.name}”及其未发布文件。已激活、已停用或被任务使用的版本无法物理删除。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-2">
            <Button type="button" variant="outline" onClick={() => setDeleteOpen(false)} disabled={busy}>取消</Button>
            <Button type="button" variant="destructive" onClick={() => void remove()} disabled={busy}>
              {deleteMutation.isMutating && <Loader2 className="animate-spin" data-icon="inline-start" />}
              删除草稿
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function AttachmentTemplateVersionList() {
  const [businessType, setBusinessType] = useState("");
  const [status, setStatus] = useState<AttachmentTemplateVersionStatus | "">("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingVersion, setEditingVersion] = useState<AttachmentTemplateVersionSummary | null>(null);
  const businessTypesQuery = useAttachmentTemplateBusinessTypes();
  const versionsQuery = useAttachmentTemplateVersions({
    businessType,
    status,
    page,
    pageSize: PAGE_SIZE,
  });
  const businessTypeLabels = useMemo(
    () => new Map(businessTypesQuery.businessTypes.map((item) => [item.code, item.label])),
    [businessTypesQuery.businessTypes]
  );
  const filteredVersions = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return versionsQuery.versions;
    return versionsQuery.versions.filter((version) =>
      [version.name, version.version_label, version.description, version.updated_by]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase().includes(needle))
    );
  }, [query, versionsQuery.versions]);
  const pageCount = Math.max(1, Math.ceil(versionsQuery.total / PAGE_SIZE));
  const error = versionsQuery.error || businessTypesQuery.error;
  const createDisabled =
    businessTypesQuery.isLoading ||
    Boolean(businessTypesQuery.error) ||
    businessTypesQuery.businessTypes.length === 0;

  useEffect(() => {
    setPage((current) => Math.min(current, pageCount));
  }, [pageCount]);

  function create() {
    setEditingVersion(null);
    setDialogOpen(true);
  }

  return (
    <section className="flex flex-col gap-6" aria-labelledby="attachment-template-title">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 id="attachment-template-title" className="text-xl font-semibold">附件模板</h2>
          <p className="text-sm text-muted-foreground">
            管理模板版本、可交付文件和激活状态。版本号由服务端按业务类型分配。
          </p>
        </div>
        <Button type="button" onClick={create} disabled={createDisabled}>
          <Plus data-icon="inline-start" />创建版本
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <CircleAlert aria-hidden="true" />
          <div className="flex flex-1 items-center justify-between gap-3">
            <div>
              <AlertTitle>模板目录加载失败</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => void Promise.allSettled([
                versionsQuery.refresh(),
                businessTypesQuery.refresh(),
              ])}
            >
              <RefreshCw data-icon="inline-start" />重试
            </Button>
          </div>
        </Alert>
      )}

      <Card>
        <CardHeader className="gap-3 pb-4">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <CardTitle className="text-base">模板版本</CardTitle>
            <div className="grid gap-2 sm:grid-cols-3">
              <div className="relative min-w-56">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                <Input value={query} onChange={(event) => setQuery(event.target.value)} className="pl-8" placeholder="筛选当前页" aria-label="筛选模板版本" />
              </div>
              <Select value={businessType || "__all__"} onValueChange={(value) => { setBusinessType(value === "__all__" ? "" : value); setPage(1); }}>
                <SelectTrigger aria-label="按业务类型筛选"><SelectValue placeholder="全部业务类型" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">全部业务类型</SelectItem>
                  {businessTypesQuery.businessTypes.map((item) => <SelectItem key={item.code} value={item.code}>{item.label}</SelectItem>)}
                </SelectContent>
              </Select>
              <Select value={status || "__all__"} onValueChange={(value) => { setStatus(value === "__all__" ? "" : value as AttachmentTemplateVersionStatus); setPage(1); }}>
                <SelectTrigger aria-label="按版本状态筛选"><SelectValue placeholder="全部状态" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">全部状态</SelectItem>
                  {Object.entries(STATUS_LABELS).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {versionsQuery.isLoading && versionsQuery.versions.length === 0 ? (
            <div className="flex flex-col gap-2 p-4">{Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-12 w-full" />)}</div>
          ) : filteredVersions.length === 0 ? (
            <Empty className="min-h-64">
              <EmptyHeader>
                <EmptyMedia variant="icon"><FileStack /></EmptyMedia>
                <EmptyTitle>没有匹配的模板版本</EmptyTitle>
                <EmptyDescription>{query || status || businessType ? "调整筛选条件后重试。" : "创建首个附件模板版本。"}</EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>版本名称</TableHead>
                  <TableHead>业务类型</TableHead>
                  <TableHead>版本</TableHead>
                  <TableHead>文件</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="hidden xl:table-cell">更新时间 / 操作人</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredVersions.map((version) => (
                  <TableRow key={version.id}>
                    <TableCell>
                      <div className="max-w-72">
                        <Link href={`/admin/templates/${encodeURIComponent(version.id)}`} className="font-medium hover:underline">{version.name}</Link>
                        <p className="truncate text-xs text-muted-foreground">{version.description || "无描述"}</p>
                      </div>
                    </TableCell>
                    <TableCell>{businessTypeLabels.get(version.business_type) ?? version.business_type}</TableCell>
                    <TableCell className="font-mono text-xs">{version.version_label}</TableCell>
                    <TableCell>{version.ready_file_count}/{version.file_count} 就绪</TableCell>
                    <TableCell><Badge variant={statusVariant(version.status)}>{STATUS_LABELS[version.status]}</Badge></TableCell>
                    <TableCell className="hidden xl:table-cell">
                      <div className="text-xs"><div>{formatDate(version.updated_at)}</div><div className="text-muted-foreground">{version.updated_by || "—"}</div></div>
                    </TableCell>
                    <TableCell><VersionActions version={version} onEdit={() => { setEditingVersion(version); setDialogOpen(true); }} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {versionsQuery.total > PAGE_SIZE && (
            <div className="flex items-center justify-between border-t px-4 py-3 text-sm">
              <span className="text-muted-foreground">第 {page}/{pageCount} 页，共 {versionsQuery.total} 个版本</span>
              <div className="flex gap-1">
                <Button type="button" variant="outline" size="icon-sm" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}><ChevronLeft /><span className="sr-only">上一页</span></Button>
                <Button type="button" variant="outline" size="icon-sm" disabled={page >= pageCount} onClick={() => setPage((current) => Math.min(pageCount, current + 1))}><ChevronRight /><span className="sr-only">下一页</span></Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <AttachmentTemplateVersionDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        businessTypes={businessTypesQuery.businessTypes}
        version={editingVersion}
      />
    </section>
  );
}

"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { ArrowLeft, FileUp, RefreshCw, Trash2, Zap } from "lucide-react";
import useSWR from "swr";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  activateTemplateVersion,
  deleteGenericTemplateFile,
  getTemplateVersion,
  uploadTemplateVersionFiles,
  type GenericTemplateVersion,
} from "@/lib/backend/annual-audit";

const ACCEPTED = ".doc,.docx,.xls,.xlsx,.xlsm,.pdf,.md,.markdown,.txt,.csv";
const USAGE_OPTIONS = [
  ["annual_report", "年度审计报告"],
  ["financial_statements", "财务报表"],
  ["notes", "财务报表附注"],
  ["audit_workpaper", "审计工作底稿（过程资料）"],
  ["management_letter", "管理建议书"],
  ["confirmations", "函证模板（过程资料）"],
] as const;
const TEMPLATE_TYPE_LABELS: Record<string, string> = {
  annual_audit: "年度审计",
  bookkeeping: "代理记账",
  tax_filing: "税务业务",
};

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function TemplateVersionFiles({ templateCode, versionNo }: { templateCode: string; versionNo: number }) {
  const key = `generic-template-version:${templateCode}:${versionNo}`;
  const { data, error, isLoading, mutate } = useSWR<GenericTemplateVersion>(key, () => getTemplateVersion(templateCode, versionNo));
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [usages, setUsages] = useState<string[]>([]);
  const [remarks, setRemarks] = useState<string[]>([]);
  const [busyKey, setBusyKey] = useState("");
  const fileInput = useRef<HTMLInputElement | null>(null);

  async function upload() {
    const files = selectedFiles;
    if (!files.length) return;
    try {
      setBusyKey("upload");
      await uploadTemplateVersionFiles(templateCode, versionNo, files, usages, remarks);
      setSelectedFiles([]); setUsages([]); setRemarks([]);
      if (fileInput.current) fileInput.current.value = "";
      toast.success("模板文件已上传");
      await mutate();
    } catch (uploadError) {
      toast.error(uploadError instanceof Error ? uploadError.message : "上传模板文件失败");
    } finally { setBusyKey(""); }
  }

  async function removeFile(fileId: number) {
    try {
      setBusyKey(`delete:${fileId}`);
      await deleteGenericTemplateFile(fileId);
      toast.success("模板文件已删除");
      await mutate();
    } catch (deleteError) {
      toast.error(deleteError instanceof Error ? deleteError.message : "删除模板文件失败");
    } finally { setBusyKey(""); }
  }

  async function activate() {
    if (!data) return;
    try {
      setBusyKey("activate");
      await activateTemplateVersion(templateCode, versionNo);
      toast.success("模板版本已激活");
      await mutate();
    } catch (activateError) {
      toast.error(activateError instanceof Error ? activateError.message : "激活模板版本失败");
    } finally { setBusyKey(""); }
  }

  const canEdit = data?.status === "draft";
  return (
    <section className="flex flex-col gap-6">
      <Link href="/admin/templates" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />返回模板管理</Link>
      {error && <Alert variant="destructive"><RefreshCw aria-hidden="true" /><div><AlertTitle>模板版本加载失败</AlertTitle><AlertDescription>{error.message}</AlertDescription></div></Alert>}
      {isLoading && <p className="text-sm text-muted-foreground">正在加载模板文件…</p>}
      {data && <>
        <div><h2 className="text-xl font-semibold">{TEMPLATE_TYPE_LABELS[data.business_line] || data.business_line}模板 {data.version_label || `v${data.version_no}`}</h2><p className="mt-1 text-sm text-muted-foreground">{TEMPLATE_TYPE_LABELS[data.business_line] || data.business_line} · {data.file_count} 个文件 · {data.status}</p></div>
        <Card>
          <CardHeader><CardTitle className="text-base">上传模板文件</CardTitle></CardHeader>
          <CardContent className="grid gap-3">
            <Input ref={fileInput} type="file" multiple accept={ACCEPTED} disabled={!canEdit} onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              setSelectedFiles(files);
              setUsages(files.map((file) => file.name.includes("函证") || file.name.includes("询证") ? "confirmations" : file.name.includes("附注") ? "notes" : file.name.includes("审计报告") ? "annual_report" : file.name.includes("报表") ? "financial_statements" : file.name.includes("底稿") || /^\d{3,4}(?:-\d+)?\b|^[A-Z]\d/.test(file.name) ? "audit_workpaper" : ""));
              setRemarks(files.map(() => ""));
            }} />
            {!!selectedFiles.length && <div className="flex flex-col gap-2 rounded-lg border bg-muted/20 p-3">
              <div className="text-xs text-muted-foreground">逐个确认模板用途和备注，避免多个文件被归入同一类。</div>
              {selectedFiles.map((file, index) => <div key={`${file.name}-${index}`} className="grid gap-2 md:grid-cols-[minmax(0,1fr)_200px_minmax(0,1fr)] md:items-center">
                <div className="min-w-0 truncate text-sm" title={file.name}>{file.name} <span className="text-xs text-muted-foreground">({formatBytes(file.size)})</span></div>
                <Select value={usages[index] || undefined} onValueChange={(value) => setUsages((current) => current.map((item, i) => i === index ? value : item))} disabled={!canEdit}>
                  <SelectTrigger aria-label={`${file.name}模板用途`}><SelectValue placeholder="选择模板用途" /></SelectTrigger>
                  <SelectContent>
                    {USAGE_OPTIONS.map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Input placeholder="该文件备注（可选）" value={remarks[index] ?? ""} onChange={(event) => setRemarks((current) => current.map((value, i) => i === index ? event.target.value : value))} disabled={!canEdit} />
              </div>)}
            </div>}
            <Button type="button" className="w-fit" onClick={() => void upload()} disabled={!canEdit || busyKey === "upload"}><FileUp data-icon="inline-start" />上传文件</Button>
            {!canEdit && <div className="flex items-center text-sm text-muted-foreground">已激活版本不可修改，请创建新版本。</div>}
            {canEdit && !!data.file_count && <Button type="button" variant="outline" onClick={() => void activate()} disabled={busyKey === "activate"}><Zap data-icon="inline-start" />激活此版本</Button>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">版本文件</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2">
            {!data.files.length && <p className="text-sm text-muted-foreground">暂无模板文件。</p>}
            {data.files.map((file) => <div key={file.id} className="flex flex-wrap items-center justify-between gap-3 rounded border p-3"><div><div className="flex flex-wrap items-center gap-2 font-medium"><span>{file.file_name}</span><Badge variant="outline">{file.file_ext.replace('.', '').toUpperCase() || "未知格式"}</Badge><span className="text-xs font-normal text-muted-foreground">{formatBytes(file.file_size)}</span></div><div className="mt-1 text-xs text-muted-foreground">用途：{file.template_usage_label || file.template_usage || "未备注"} · {file.remark || "无备注"} · 生成时保持此文件格式</div></div>{canEdit && <Button type="button" size="sm" variant="ghost" disabled={busyKey === `delete:${file.id}`} onClick={() => void removeFile(file.id)}><Trash2 data-icon="inline-start" />删除</Button>}</div>)}
          </CardContent>
        </Card>
      </>}
    </section>
  );
}

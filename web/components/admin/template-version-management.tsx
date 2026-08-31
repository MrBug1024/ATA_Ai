"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import useSWR from "swr";
import { AlertTriangle, CheckCircle2, RefreshCw, Save, Trash2, Zap } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { annualAuditTemplateReadiness } from "@/lib/admin-template-contract-readiness";
import {
  activateTemplateVersion,
  createTemplateVersion,
  deleteTemplateVersion,
  getTemplateVersions,
  type GenericTemplateVersion,
} from "@/lib/backend/annual-audit";

const ACCEPTED = ".doc,.docx,.xls,.xlsx,.xlsm,.pdf,.md,.markdown,.txt,.csv";
const USAGE_OPTIONS = [
  ["annual_report", "年度审计报告（审计报告正文.docx）"],
  ["financial_statements", "年度审计财务报表（一般企业报表.xlsx / 经审计的财务报表.xls）"],
  ["notes", "财务报表附注（一般企业附注.docx / 会计报表附注.doc）"],
  ["audit_workpaper", "审计工作底稿（过程资料）"],
  ["management_letter", "管理建议书（管理建议书模板.docx）"],
  ["confirmations", "函证（过程资料）"],
] as const;
const TEMPLATE_TYPE_OPTIONS = [
  ["annual_audit", "年度审计"],
  ["bookkeeping", "代理记账"],
  ["tax_filing", "税务业务"],
] as const;

function templateTypeLabel(value: string): string {
  return TEMPLATE_TYPE_OPTIONS.find(([key]) => key === value)?.[1] ?? value;
}

function versionTitle(version: GenericTemplateVersion): string {
  const label = version.version_label?.match(/v\d+/i)?.[0] || `v${version.version_no}`;
  return `${templateTypeLabel(version.business_line)}模板 ${label}`;
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function inferUsage(fileName: string): string {
  if (fileName.includes("审计报告") && !fileName.includes("财务报表") && !fileName.includes("附注")) return "annual_report";
  if (fileName.includes("财务报表") || fileName.includes("一般企业报表") || fileName.includes("经审计的财务报表")) return "financial_statements";
  if (fileName.includes("附注")) return "notes";
  if (fileName.includes("管理建议")) return "management_letter";
  if (fileName.includes("函证") || fileName.includes("询证")) return "confirmations";
  if (fileName.includes("底稿") || /^\d{3,4}(?:-\d+)?\b|^[A-Z]\d/.test(fileName)) return "audit_workpaper";
  return "";
}

export function TemplateVersionManagement() {
  const { data, error, isLoading, mutate } = useSWR("generic-template-versions", getTemplateVersions);
  const [templateType, setTemplateType] = useState("annual_audit");
  const [versionLabel, setVersionLabel] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [fileUsages, setFileUsages] = useState<string[]>([]);
  const [fileRemarks, setFileRemarks] = useState<string[]>([]);
  const [busyKey, setBusyKey] = useState("");
  const fileInput = useRef<HTMLInputElement | null>(null);
  const versions = data?.versions ?? [];

  async function createVersion() {
    const files = selectedFiles;
    if (!files.length) {
      toast.error("创建模板版本时至少上传一个模板文件");
      return;
    }
    try {
      setBusyKey("create");
      await createTemplateVersion({
        template_name: `${templateTypeLabel(templateType)}模板`,
        business_line: templateType,
        version_label: versionLabel.trim(),
        template_usages: fileUsages,
        remarks: fileRemarks,
        files,
      });
      setVersionLabel("");
      setSelectedFiles([]);
      setFileUsages([]);
      setFileRemarks([]);
      if (fileInput.current) fileInput.current.value = "";
      toast.success("模板版本和文件已创建");
      await mutate();
    } catch (createError) {
      toast.error(createError instanceof Error ? createError.message : "创建模板版本失败");
    } finally {
      setBusyKey("");
    }
  }

  async function removeVersion(version: GenericTemplateVersion) {
    if (!window.confirm(`确定删除“${versionTitle(version)}”及其 ${version.file_count} 个模板文件吗？`)) return;
    try {
      setBusyKey(`delete:${version.id}`);
      await deleteTemplateVersion(version.template_code, version.version_no);
      toast.success("模板版本及其文件已删除");
      await mutate();
    } catch (deleteError) {
      toast.error(deleteError instanceof Error ? deleteError.message : "删除模板版本失败");
    } finally {
      setBusyKey("");
    }
  }

  async function activate(version: GenericTemplateVersion) {
    try {
      setBusyKey(`activate:${version.id}`);
      await activateTemplateVersion(version.template_code, version.version_no);
      toast.success(`${versionTitle(version)} 已激活`);
      await mutate();
    } catch (activateError) {
      toast.error(activateError instanceof Error ? activateError.message : "激活模板版本失败");
    } finally {
      setBusyKey("");
    }
  }

  return (
    <section className="flex flex-col gap-6" aria-labelledby="template-management-title">
      <div className="flex flex-col gap-1">
        <h2 id="template-management-title" className="text-xl font-semibold">模板管理</h2>
        <p className="text-sm text-muted-foreground">模板类型由系统选择；同一类型同一时间只允许一个激活版本。年度审计核心交付必须同时配置审计报告、财务报表和财务报表附注。模板用于定义附件应包含的章节、字体、段落、表格和页面样式；系统结合项目审计结果与全部证据独立编制内容，并按源文件格式交付，不会把模板业务正文原样作为项目结论返回。</p>
      </div>

      {error && <Alert variant="destructive"><RefreshCw aria-hidden="true" /><div><AlertTitle>模板目录加载失败</AlertTitle><AlertDescription>{error.message}</AlertDescription></div></Alert>}

      <Card>
        <CardHeader><CardTitle className="text-base">创建模板版本</CardTitle></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <Select value={templateType} onValueChange={setTemplateType}>
            <SelectTrigger aria-label="模板类型"><SelectValue placeholder="选择模板类型" /></SelectTrigger>
            <SelectContent>
              {TEMPLATE_TYPE_OPTIONS.map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Input placeholder="版本标签，如 v1" value={versionLabel} onChange={(event) => setVersionLabel(event.target.value)} />
          <Input ref={fileInput} type="file" multiple accept={ACCEPTED} onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            setSelectedFiles(files);
            setFileUsages(files.map((file) => inferUsage(file.name)));
            setFileRemarks(files.map(() => ""));
          }} />
          <div className="md:col-span-2 lg:col-span-4 rounded-lg border bg-muted/20 p-3">
            <div className="mb-2 text-xs text-muted-foreground">每个文件单独填写用途和备注；系统会根据文件名预填，提交前请核对。</div>
            {!selectedFiles.length && <div className="text-sm text-muted-foreground">请选择一个或多个模板文件。</div>}
            <div className="flex flex-col gap-2">
              {selectedFiles.map((file, index) => (
                <div key={`${file.name}-${index}`} className="grid gap-2 md:grid-cols-[minmax(0,1fr)_200px_minmax(0,1fr)] md:items-center">
                  <div className="min-w-0 truncate text-sm" title={file.name}>{file.name} <span className="text-xs text-muted-foreground">({formatBytes(file.size)})</span></div>
                  <Select value={fileUsages[index] || undefined} onValueChange={(value) => setFileUsages((current) => current.map((item, i) => i === index ? value : item))}>
                    <SelectTrigger aria-label={`${file.name}模板用途`}><SelectValue placeholder="选择模板用途" /></SelectTrigger>
                    <SelectContent>
                      {USAGE_OPTIONS.map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Input placeholder="该文件备注（可选）" value={fileRemarks[index] ?? ""} onChange={(event) => setFileRemarks((current) => current.map((value, i) => i === index ? event.target.value : value))} />
                </div>
              ))}
            </div>
          </div>
          <Button type="button" className="lg:col-span-2" onClick={() => void createVersion()} disabled={busyKey === "create" || !templateType}><Save data-icon="inline-start" />创建版本并上传文件</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">模板版本</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-2">
          {isLoading && <p className="text-sm text-muted-foreground">正在加载模板版本…</p>}
          {!isLoading && !versions.length && <p className="text-sm text-muted-foreground">暂未创建模板版本。</p>}
          {versions.map((version) => {
            const isActive = version.active_version_no === version.version_no && version.status === "active";
            const isAnnualAudit = version.business_line === "annual_audit";
            const readiness = isAnnualAudit ? annualAuditTemplateReadiness(version.template_contract) : null;
            return (
              <div key={version.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-4">
                <Link href={`/admin/templates/${encodeURIComponent(version.template_code)}/versions/${version.version_no}`} className="min-w-0 flex-1 hover:underline">
                  <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{versionTitle(version)}</span>{isActive && <Badge>当前激活</Badge>}<Badge variant="outline">{version.status}</Badge></div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span>{templateTypeLabel(version.business_line)} · {version.file_count} 个模板文件 · {version.created_at || ""}</span>
                    {isAnnualAudit && readiness && <span className={readiness.tone === "ready" ? "inline-flex items-center gap-1 text-emerald-700" : readiness.tone === "pending" ? "inline-flex items-center gap-1 text-sky-700" : "inline-flex items-center gap-1 text-amber-700"}>
                      {readiness.tone === "ready" ? <CheckCircle2 className="size-3" aria-hidden="true" /> : <AlertTriangle className="size-3" aria-hidden="true" />}
                      {readiness.message}
                    </span>}
                  </div>
                </Link>
                <div className="flex flex-wrap gap-2">
                  {!isActive && <Button type="button" size="sm" variant="outline" title={readiness?.activationBlocked ? readiness.message : undefined} disabled={!version.file_count || Boolean(readiness?.activationBlocked) || busyKey === `activate:${version.id}`} onClick={() => void activate(version)}><Zap data-icon="inline-start" />激活</Button>}
                  <Button type="button" size="sm" variant="ghost" disabled={busyKey === `delete:${version.id}`} onClick={() => void removeVersion(version)}><Trash2 data-icon="inline-start" />删除版本</Button>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>
    </section>
  );
}

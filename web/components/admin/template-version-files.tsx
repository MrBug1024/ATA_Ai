"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, ClipboardCheck, Copy, FileSearch, FileUp, RefreshCw, Trash2, WandSparkles, Zap } from "lucide-react";
import useSWR from "swr";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { annualAuditTemplateReadiness } from "@/lib/admin-template-contract-readiness";
import {
  activateTemplateVersion,
  draftTemplateVersionDocxSlotContract,
  deleteGenericTemplateFile,
  getTemplateVersion,
  previewTemplateVersionDocxSlots,
  updateTemplateVersionFieldSchema,
  type GenericTemplateDocxSlotContractDraft,
  type GenericTemplateDocxSlotPreview,
  type GenericTemplateFile,
  uploadTemplateVersionFiles,
  type GenericTemplateFieldSchema,
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

const PLACEMENT_LABELS: Record<string, string> = {
  annual_report: "填充报告正文中的主体、年度、编号和意见草稿位置",
  financial_statements: "填充科目行及期末/期初、本期/上期金额列",
  notes: "填充附注正文占位和报表项目表格",
  management_letter: "仅填充模板显式结果字段或字段映射",
  audit_workpaper: "过程资料，按模板设计与项目证据编制",
  confirmations: "过程资料，按模板设计与项目证据编制",
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
  const [fieldSchemaText, setFieldSchemaText] = useState("");
  const [slotPreview, setSlotPreview] = useState<GenericTemplateDocxSlotPreview | null>(null);
  const [slotPreviewFile, setSlotPreviewFile] = useState<GenericTemplateFile | null>(null);
  const [contractDraft, setContractDraft] = useState<GenericTemplateDocxSlotContractDraft | null>(null);
  const [contractDraftFile, setContractDraftFile] = useState<GenericTemplateFile | null>(null);
  const [busyKey, setBusyKey] = useState("");
  const fileInput = useRef<HTMLInputElement | null>(null);
  const fieldSchemaSeed = data ? JSON.stringify(data.field_schema ?? {}, null, 2) : "";

  useEffect(() => {
    setFieldSchemaText(fieldSchemaSeed);
  }, [fieldSchemaSeed]);

  async function upload() {
    const files = selectedFiles;
    if (!files.length) return;
    try {
      setBusyKey("upload");
      await uploadTemplateVersionFiles(templateCode, versionNo, files, usages, remarks);
      setSelectedFiles([]); setUsages([]); setRemarks([]);
      setSlotPreview(null); setSlotPreviewFile(null);
      setContractDraft(null); setContractDraftFile(null);
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
      if (slotPreviewFile?.id === fileId) {
        setSlotPreview(null); setSlotPreviewFile(null);
      }
      if (contractDraftFile?.id === fileId) {
        setContractDraft(null); setContractDraftFile(null);
      }
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

  async function saveFieldSchema() {
    if (!data) return;
    let fieldSchema: GenericTemplateFieldSchema;
    try {
      const parsed: unknown = JSON.parse(fieldSchemaText);
      if (parsed === null || typeof parsed !== "object") {
        throw new Error("字段配置必须是 JSON 对象或数组");
      }
      fieldSchema = parsed as GenericTemplateFieldSchema;
    } catch (schemaError) {
      toast.error(schemaError instanceof Error ? schemaError.message : "字段配置不是有效的 JSON");
      return;
    }

    try {
      setBusyKey("field-schema");
      const updated = await updateTemplateVersionFieldSchema(templateCode, versionNo, fieldSchema);
      setSlotPreview(null); setSlotPreviewFile(null);
      setContractDraft(null); setContractDraftFile(null);
      toast.success("模板字段配置已保存");
      await mutate(updated, { revalidate: false });
    } catch (saveError) {
      toast.error(saveError instanceof Error ? saveError.message : "保存模板字段配置失败");
    } finally { setBusyKey(""); }
  }

  async function previewDocxSlots(file: GenericTemplateFile, offset = 0, includeEmpty = false) {
    try {
      setBusyKey(`slot-preview:${file.id}`);
      const preview = await previewTemplateVersionDocxSlots(templateCode, versionNo, file.id, { offset, limit: 80, includeEmpty });
      setSlotPreview(preview);
      setSlotPreviewFile(file);
      toast.success("已读取 DOCX 槽位候选");
    } catch (previewError) {
      toast.error(previewError instanceof Error ? previewError.message : "读取 DOCX 槽位候选失败");
    } finally { setBusyKey(""); }
  }

  async function draftDocxSlotContract(file: GenericTemplateFile, offset = 0) {
    try {
      setBusyKey(`contract-draft:${file.id}`);
      const draft = await draftTemplateVersionDocxSlotContract(templateCode, versionNo, file.id, {
        offset,
        limit: 80,
      });
      setContractDraft(draft);
      setContractDraftFile(file);
      toast.success(draft.validation.state === "valid" ? "已生成并校验槽位合同草案" : "本页没有可自动草拟的槽位");
    } catch (draftError) {
      toast.error(draftError instanceof Error ? draftError.message : "生成 DOCX 槽位合同草案失败");
    } finally { setBusyKey(""); }
  }

  function loadContractDraftIntoFieldSchema() {
    const contract = contractDraft?.proposal?.slot_contract;
    const fileName = contractDraft?.structure.file_name;
    if (!contract || !fileName) {
      toast.error("当前草案没有可载入的已验证合同");
      return;
    }
    try {
      const parsed: unknown = JSON.parse(fieldSchemaText || "{}");
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("年度审计模板字段配置必须是 JSON 对象");
      }
      const fieldSchema = parsed as Record<string, unknown>;
      const currentDocx = fieldSchema.docx;
      const docx = currentDocx !== null && typeof currentDocx === "object" && !Array.isArray(currentDocx)
        ? currentDocx as Record<string, unknown>
        : {};
      const currentContracts = docx.slot_contracts;
      const slotContracts = currentContracts !== null && typeof currentContracts === "object" && !Array.isArray(currentContracts)
        ? currentContracts as Record<string, unknown>
        : {};
      const currentContract = slotContracts[fileName];
      const existingContract = currentContract !== null && typeof currentContract === "object" && !Array.isArray(currentContract)
        ? currentContract as Record<string, unknown>
        : {};
      const existingTemplateSha = typeof existingContract.template_sha256 === "string"
        ? existingContract.template_sha256
        : "";
      if (existingTemplateSha && existingTemplateSha !== contract.template_sha256) {
        throw new Error("已有合同绑定的模板 SHA-256 不同，不能合并草案");
      }
      const existingSlots = Array.isArray(existingContract.slots) ? existingContract.slots : [];
      const executableSlots = contract.slots.map((slot) => {
        const { candidate_id: _candidateId, source_id: _sourceId, ...executableSlot } = slot;
        return executableSlot;
      });
      const slotsByTarget = new Map<string, unknown>();
      for (const slot of existingSlots) {
        if (slot !== null && typeof slot === "object" && !Array.isArray(slot)) {
          const target = (slot as Record<string, unknown>).target;
          if (typeof target === "string" && target) slotsByTarget.set(target, slot);
        }
      }
      for (const slot of executableSlots) slotsByTarget.set(slot.target, slot);
      setFieldSchemaText(JSON.stringify({
        ...fieldSchema,
        docx: {
          ...docx,
          slot_contracts: {
            ...slotContracts,
            [fileName]: {
              contract_version: contract.contract_version || existingContract.contract_version || "docx-slot-contract-v1",
              template_sha256: contract.template_sha256,
              slots: [...slotsByTarget.values()],
            },
          },
        },
      }, null, 2));
      toast.success("草案已合并到编辑区，核对后仍需显式保存字段配置");
    } catch (schemaError) {
      toast.error(schemaError instanceof Error ? schemaError.message : "无法载入合同草案");
    }
  }

  async function copySlotValue(value: string, label: string) {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(`${label}已复制`);
    } catch {
      toast.error("浏览器未允许复制，请手动选择文本");
    }
  }

  const canEdit = data?.status === "draft";
  const readiness = data?.business_line === "annual_audit"
    ? annualAuditTemplateReadiness(data.template_contract)
    : null;
  return (
    <section className="flex flex-col gap-6">
      <Link href="/admin/templates" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />返回模板管理</Link>
      {error && <Alert variant="destructive"><RefreshCw aria-hidden="true" /><div><AlertTitle>模板版本加载失败</AlertTitle><AlertDescription>{error.message}</AlertDescription></div></Alert>}
      {isLoading && <p className="text-sm text-muted-foreground">正在加载模板文件…</p>}
      {data && <>
        <div>
          <h2 className="text-xl font-semibold">{TEMPLATE_TYPE_LABELS[data.business_line] || data.business_line}模板 {data.version_label || `v${data.version_no}`}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{TEMPLATE_TYPE_LABELS[data.business_line] || data.business_line} · {data.file_count} 个文件 · {data.status}</p>
          {readiness && <div className={`mt-3 flex items-start gap-2 rounded-md border p-3 text-sm ${readiness.tone === "ready" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : readiness.tone === "pending" ? "border-sky-200 bg-sky-50 text-sky-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
            {readiness.tone === "ready" ? <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden="true" /> : <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />}
            <span>{readiness.message}</span>
          </div>}
        </div>
        <Card>
          <CardHeader><CardTitle className="text-base">字段与 DOCX 槽位配置</CardTitle></CardHeader>
          <CardContent className="grid gap-3">
            <Textarea
              aria-label="模板字段配置 JSON"
              className="min-h-36 font-mono text-xs"
              disabled={!canEdit || busyKey === "field-schema"}
              onChange={(event) => setFieldSchemaText(event.target.value)}
              placeholder={'{"docx":{"slot_contracts":{"模板文件.docx":{"slots":[...]}}}}'}
              spellCheck={false}
              value={fieldSchemaText}
            />
            <Button type="button" className="w-fit" onClick={() => void saveFieldSchema()} disabled={!canEdit || busyKey === "field-schema"}>
              <CheckCircle2 data-icon="inline-start" />保存字段配置
            </Button>
            {!canEdit && <div className="text-sm text-muted-foreground">已激活版本的字段配置已冻结，请创建新版本。</div>}
          </CardContent>
        </Card>
        {slotPreview && <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle className="text-base">DOCX 槽位候选：{slotPreview.file_name}</CardTitle>
              <Badge variant={slotPreview.contract.state === "valid" ? "default" : slotPreview.contract.state === "invalid" ? "destructive" : "outline"}>
                {slotPreview.contract.state === "valid" ? "当前契约可绑定" : slotPreview.contract.state === "invalid" ? "当前契约无效" : "尚未声明契约"}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="grid gap-4">
            {slotPreview.contract.message && <Alert variant="destructive"><AlertTriangle aria-hidden="true" /><div><AlertTitle>槽位契约需要修正</AlertTitle><AlertDescription>{slotPreview.contract.message}</AlertDescription></div></Alert>}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-4">
                <span>正文段落 {slotPreview.observations.body.body_paragraph_count}</span>
                <span>表格 {slotPreview.observations.tables.table_count}</span>
                <span>分节 {slotPreview.observations.body.section_count}</span>
                <span>已声明槽位 {slotPreview.contract.slot_count}</span>
              </div>
              {slotPreviewFile && <Button type="button" size="sm" variant="outline" disabled={busyKey === `slot-preview:${slotPreviewFile.id}`} onClick={() => void previewDocxSlots(slotPreviewFile, 0, !slotPreview.page.include_empty)}>{slotPreview.page.include_empty ? "隐藏空槽位" : "包含空槽位"}</Button>}
            </div>
            <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
              <span className="shrink-0">模板 SHA-256</span>
              <code className="min-w-0 truncate font-mono" title={slotPreview.template_sha256}>{slotPreview.template_sha256}</code>
              <Button type="button" variant="ghost" size="icon-xs" title="复制模板 SHA-256" aria-label="复制模板 SHA-256" onClick={() => void copySlotValue(slotPreview.template_sha256, "模板 SHA-256")}><Copy /></Button>
            </div>
            <div className="grid gap-2">
              {slotPreview.candidates.map((candidate) => <div key={candidate.target} className="grid gap-2 border-b pb-3 last:border-b-0 last:pb-0 md:grid-cols-[minmax(13rem,0.7fr)_minmax(0,1.8fr)] md:items-start">
                <div className="flex min-w-0 items-center gap-1.5">
                  <code className="min-w-0 truncate font-mono text-xs" title={candidate.target}>{candidate.target}</code>
                  <Button type="button" variant="ghost" size="icon-xs" title="复制槽位地址" aria-label={`复制槽位地址 ${candidate.target}`} onClick={() => void copySlotValue(candidate.target, "槽位地址")}><Copy /></Button>
                  <Badge variant="outline" className="shrink-0 text-[0.7rem]">{candidate.recommended_mode}</Badge>
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span>{candidate.location}</span><span>{candidate.classification}</span><span>{candidate.field_kind}</span></div>
                  <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words rounded border bg-muted/30 p-2 font-mono text-xs text-foreground">{candidate.source_text || "（空槽位）"}</pre>
                  <div className="mt-1 flex min-w-0 items-center gap-2 text-[0.7rem] text-muted-foreground"><span className="shrink-0">原文 SHA-256</span><code className="min-w-0 truncate" title={candidate.source_text_sha256}>{candidate.source_text_sha256}</code><Button type="button" variant="ghost" size="icon-xs" title="复制原文 SHA-256" aria-label={`复制 ${candidate.target} 原文 SHA-256`} onClick={() => void copySlotValue(candidate.source_text_sha256, "原文 SHA-256")}><Copy /></Button>{!candidate.source_text_complete && <span>原文较长，当前仅显示预览</span>}</div>
                </div>
              </div>)}
            </div>
            {slotPreview.page.has_more && slotPreviewFile && <Button type="button" variant="outline" className="w-fit" disabled={busyKey === `slot-preview:${slotPreviewFile.id}`} onClick={() => void previewDocxSlots(slotPreviewFile, slotPreview.page.next_offset ?? 0, slotPreview.page.include_empty)}><FileSearch data-icon="inline-start" />读取下一批候选</Button>}
            {slotPreview.candidate_collection_truncated && <p className="text-xs text-amber-700">模板中的可绑定目标超过预览上限，当前结果已截断。</p>}
          </CardContent>
        </Card>}
        {contractDraft && <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle className="text-base">DOCX 槽位合同草案：{contractDraft.structure.file_name}</CardTitle>
              <Badge variant={contractDraft.validation.state === "valid" ? "default" : "outline"}>
                {contractDraft.validation.state === "valid" ? "已通过模板绑定校验" : "无自动草案"}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="grid gap-4">
            <Alert>
              <ClipboardCheck aria-hidden="true" />
              <div>
                <AlertTitle>草案尚未保存</AlertTitle>
                <AlertDescription>{contractDraft.persistence.reason}</AlertDescription>
              </div>
            </Alert>
            <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-muted-foreground">
              <span>本批候选 {contractDraft.structure.page.returned}</span>
              <span>模板候选总数 {contractDraft.structure.candidate_total}</span>
              <span>草案槽位 {contractDraft.proposal?.slot_contract.slot_count ?? 0}</span>
              {contractDraft.structure.candidate_collection_truncated && <span className="text-amber-700">模板候选超过收集上限，需分段复核</span>}
            </div>
            {contractDraft.validation.message && <p className="text-sm text-muted-foreground">{contractDraft.validation.message}</p>}
            {!!contractDraft.warnings.length && <Alert variant="destructive"><AlertTriangle aria-hidden="true" /><div><AlertTitle>草案提示</AlertTitle><AlertDescription>{contractDraft.warnings.join("；")}</AlertDescription></div></Alert>}
            {!!contractDraft.proposal?.slot_contract.slots.length && <div className="grid gap-2">
              {contractDraft.proposal.slot_contract.slots.map((slot) => <div key={slot.slot_id} className="grid gap-2 border-b pb-3 last:border-b-0 last:pb-0 md:grid-cols-[minmax(13rem,0.7fr)_minmax(0,1.8fr)] md:items-start">
                <div className="min-w-0"><code className="block truncate font-mono text-xs" title={slot.target}>{slot.target}</code><div className="mt-1 flex flex-wrap gap-1"><Badge variant="outline" className="text-[0.7rem]">{slot.mode}</Badge><Badge variant="outline" className="text-[0.7rem]">{slot.source_id || "删除说明"}</Badge></div></div>
                <div className="text-xs text-muted-foreground">{slot.replacements.length ? `仅替换：${slot.replacements.map((replacement) => replacement.expected_text).join("、")}` : "整段或单元格写入"}</div>
              </div>)}
            </div>}
            <div className="flex flex-wrap gap-2">
              {!!contractDraft.proposal?.slot_contract.slots.length && <Button type="button" onClick={loadContractDraftIntoFieldSchema} disabled={!canEdit}><ClipboardCheck data-icon="inline-start" />载入字段配置</Button>}
              {contractDraft.structure.page.has_more && contractDraftFile && <Button type="button" variant="outline" disabled={busyKey === `contract-draft:${contractDraftFile.id}`} onClick={() => void draftDocxSlotContract(contractDraftFile, contractDraft.structure.page.next_offset ?? 0)}><WandSparkles data-icon="inline-start" />生成下一批草案</Button>}
            </div>
            <div className="grid gap-2 text-xs text-muted-foreground">
              {contractDraft.candidates.filter((candidate) => candidate.reason).slice(0, 12).map((candidate) => <div key={candidate.candidate_id} className="flex flex-wrap gap-x-2"><code>{candidate.target}</code><span>{candidate.reason}</span></div>)}
            </div>
          </CardContent>
        </Card>}
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
            {canEdit && !!data.file_count && <Button type="button" variant="outline" title={readiness?.activationBlocked ? readiness.message : undefined} onClick={() => void activate()} disabled={Boolean(readiness?.activationBlocked) || busyKey === "activate"}><Zap data-icon="inline-start" />激活此版本</Button>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">版本文件</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2">
            {!data.files.length && <p className="text-sm text-muted-foreground">暂无模板文件。</p>}
            {data.files.map((file) => <div key={file.id} className="flex flex-wrap items-center justify-between gap-3 rounded border p-3">
              <div>
                <div className="flex flex-wrap items-center gap-2 font-medium"><span>{file.file_name}</span><Badge variant="outline">{file.file_ext.replace('.', '').toUpperCase() || "未知格式"}</Badge><span className="text-xs font-normal text-muted-foreground">{formatBytes(file.file_size)}</span></div>
                <div className="mt-1 text-xs text-muted-foreground">用途：{file.template_usage_label || file.template_usage || "未备注"} · {file.remark || "无备注"} · 交付保持 {file.file_ext.toLowerCase()} 格式</div>
                <div className="mt-1 text-xs text-foreground/70">结果落点：{PLACEMENT_LABELS[file.template_usage] || "模板显式字段或结构化表格位置"}；不会追加整段 AI 对话。</div>
              </div>
              <div className="flex items-center gap-1">
                {canEdit && file.file_ext.toLowerCase() === ".docx" && <Button type="button" size="sm" variant="ghost" title="生成可审阅的 DOCX 槽位合同草案" disabled={busyKey === `contract-draft:${file.id}`} onClick={() => void draftDocxSlotContract(file)}><WandSparkles data-icon="inline-start" />合同草案</Button>}
                {canEdit && file.file_ext.toLowerCase() === ".docx" && <Button type="button" size="sm" variant="ghost" title="读取 DOCX 槽位候选" disabled={busyKey === `slot-preview:${file.id}`} onClick={() => void previewDocxSlots(file)}><FileSearch data-icon="inline-start" />槽位候选</Button>}
                {canEdit && <Button type="button" size="sm" variant="ghost" disabled={busyKey === `delete:${file.id}`} onClick={() => void removeFile(file.id)}><Trash2 data-icon="inline-start" />删除</Button>}
              </div>
            </div>)}
          </CardContent>
        </Card>
      </>}
    </section>
  );
}

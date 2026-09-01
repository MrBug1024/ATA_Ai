"use client";

import { Fragment, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  Copy,
  Eye,
  FileSearch,
  FileUp,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  WandSparkles,
  X,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
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
import { Textarea } from "@/components/ui/textarea";
import { PdfViewer } from "@/components/shared/file-preview-panel";
import {
  ATTACHMENT_TEMPLATE_MISSING_POLICIES,
  ATTACHMENT_TEMPLATE_OVERFLOW_POLICIES,
  ATTACHMENT_TEMPLATE_STYLE_POLICIES,
  ATTACHMENT_TEMPLATE_VALUE_TYPES,
  SUPPORTED_ATTACHMENT_TEMPLATE_FORMATS,
  createDefaultAttachmentTemplateSlot,
  getAttachmentTemplateFilePreview,
  isAttachmentTemplateDocumentCode,
  isAttachmentTemplateFactKey,
  isAttachmentTemplateSlotId,
  isAttachmentTemplateSourcePath,
  normalizeAttachmentTemplateFormat,
  type AttachmentTemplateBindingManifest,
  type AttachmentTemplateCompositionMode,
  type AttachmentTemplateFile,
  type AttachmentTemplateFormat,
  type AttachmentTemplateMissingPolicy,
  type AttachmentTemplateOverflowPolicy,
  type AttachmentTemplateSlot,
  type AttachmentTemplateStylePolicy,
  type AttachmentTemplateValueType,
} from "@/lib/backend/attachment-templates";
import {
  useAttachmentTemplateBusinessTypes,
  useAttachmentTemplateVersion,
  useCloneAttachmentTemplateVersion,
  useCompileAttachmentTemplateFile,
  useDeleteAttachmentTemplateFile,
  useInspectAttachmentTemplateFile,
  useSetAttachmentTemplateVersionActivation,
  useUpdateAttachmentTemplateFile,
  useUploadAttachmentTemplateFile,
  useValidateAttachmentTemplateVersion,
} from "@/lib/hooks/use-attachment-templates";
import { AttachmentTemplateVersionDialog } from "./attachment-template-version-dialog";

const ACCEPTED_TEMPLATE_FORMATS = SUPPORTED_ATTACHMENT_TEMPLATE_FORMATS.join(",");

const FILE_STATUS_LABELS: Record<string, string> = {
  uploaded: "已上传",
  scanning: "扫描中",
  mapping: "待映射",
  ready: "已就绪",
  invalid: "校验失败",
  archived: "已归档",
};

const VERSION_STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  validating: "校验中",
  ready: "可激活",
  active: "已激活",
  retired: "已停用",
  archived: "已归档",
};

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function fileNameTemplateFormat(fileName: string): AttachmentTemplateFormat | null {
  return normalizeAttachmentTemplateFormat(fileName.split(".").pop() ?? "");
}

function inferDocumentMetadata(fileName: string): { code: string; name: string } {
  const baseName = fileName.replace(/\.[^.]+$/, "");
  if (fileName.includes("附注")) return { code: "financial_statement_notes", name: "财务报表附注" };
  if (fileName.includes("财务报表") || fileName.includes("一般企业报表")) return { code: "financial_statements", name: "财务报表" };
  if (fileName.includes("审计报告")) return { code: "audit_report", name: "审计报告" };
  if (fileName.includes("管理建议")) return { code: "management_letter", name: "管理建议书" };
  if (fileName.includes("函证") || fileName.includes("询证")) return { code: "confirmation", name: "函证" };
  return { code: "", name: baseName };
}

function recordString(value: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const candidate = value[key];
    if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
  }
  return "";
}

function canonicalValueType(value: string): AttachmentTemplateValueType {
  return ATTACHMENT_TEMPLATE_VALUE_TYPES.includes(value as AttachmentTemplateValueType)
    ? value as AttachmentTemplateValueType
    : "scalar";
}

function canonicalStylePolicy(
  value: string,
  valueType: AttachmentTemplateValueType
): AttachmentTemplateStylePolicy {
  return ATTACHMENT_TEMPLATE_STYLE_POLICIES.includes(value as AttachmentTemplateStylePolicy)
    ? value as AttachmentTemplateStylePolicy
    : valueType === "table_rows" ? "clone_prototype_row" : "inherit_template";
}

function canonicalMissingPolicy(value: string): AttachmentTemplateMissingPolicy {
  return ATTACHMENT_TEMPLATE_MISSING_POLICIES.includes(value as AttachmentTemplateMissingPolicy)
    ? value as AttachmentTemplateMissingPolicy
    : "block";
}

function canonicalOverflowPolicy(
  value: string,
  valueType: AttachmentTemplateValueType
): AttachmentTemplateOverflowPolicy {
  if (ATTACHMENT_TEMPLATE_OVERFLOW_POLICIES.includes(value as AttachmentTemplateOverflowPolicy)) {
    return value as AttachmentTemplateOverflowPolicy;
  }
  if (valueType === "table_rows") return "extend_rows";
  if (valueType === "narrative_blocks") return "continue_paragraphs";
  return "error";
}

type SlotOptions = Record<string, unknown>;

const SEMANTIC_OPTION_FIELDS = [
  "semantic_instruction",
  "allowed_fact_refs",
  "fact_ref_labels",
  "require_fact_refs",
] as const;

const CANDIDATE_OPTION_FIELDS = [
  "alignment",
  "allow_multiple",
  "allowed_fact_refs",
  "column_map",
  "columns",
  "composition_mode",
  "fact_ref_labels",
  "font_name",
  "font_size",
  "formula_columns",
  "height",
  "leading_factor",
  "max_lines",
  "minimum_font_size",
  "page",
  "prototype_row",
  "require_fact_refs",
  "semantic_instruction",
  "sheet",
  "width",
  "x",
  "y",
  "y_from_top",
] as const;

const NUMERIC_OPTION_FIELDS = [
  "font_size",
  "height",
  "leading_factor",
  "max_lines",
  "minimum_font_size",
  "page",
  "prototype_row",
  "width",
  "x",
  "y",
] as const;

const SEMANTIC_FACT_KEY_FRAGMENT_PATTERN =
  /(?:^|[^A-Za-z0-9_])(?:[a-z][a-z0-9_]*(?:\[\])?\.)+[a-z][a-z0-9_]*(?:\[\])?(?=$|[^A-Za-z0-9_])/;
const SEMANTIC_INTERNAL_IDENTIFIER_PATTERN =
  /(?:\b(?:case|report|evidence|storage|object|source_file|source_page|chunk|claim)_?(?:id|ref)\b|\b(?:minio|s3|file):\/\/|\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b)/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function cloneOptionValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(cloneOptionValue);
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, cloneOptionValue(item)])
    );
  }
  return value;
}

function cloneOptions(value: unknown): SlotOptions {
  if (!isRecord(value)) return {};
  return cloneOptionValue(value) as SlotOptions;
}

function slotCompositionMode(slot: AttachmentTemplateSlot): AttachmentTemplateCompositionMode {
  return slot.options?.composition_mode === "semantic" ? "semantic" : "deterministic";
}

function deterministicOptions(value: unknown): SlotOptions {
  const options = cloneOptions(value);
  delete options.composition_mode;
  for (const key of SEMANTIC_OPTION_FIELDS) delete options[key];
  return options;
}

function candidateOptions(candidate: Record<string, unknown>): SlotOptions {
  const options = cloneOptions(candidate.options);
  for (const key of CANDIDATE_OPTION_FIELDS) {
    if (!(key in options) && candidate[key] !== undefined) {
      options[key] = cloneOptionValue(candidate[key]);
    }
  }
  return options;
}

function inspectionCandidates(file: AttachmentTemplateFile): Array<Record<string, unknown>> {
  const direct = file.inspection_report?.slot_candidates;
  if (direct?.length) return direct;
  return file.inspection_report?.suggested_mapping?.slots ?? [];
}

function normalizeTemplateFormat(value: string): string {
  return value.trim().toLocaleLowerCase().replace(/^\./, "");
}

function targetKind(target: string): string {
  return target.split(":", 3)[1] ?? "";
}

function targetFormat(target: string): string {
  return normalizeTemplateFormat(target.split(":", 1)[0] ?? "");
}

function isExplicitTemplateTarget(target: string, format: string): boolean {
  const parts = target.trim().split(":", 3);
  return (
    Boolean(format) &&
    parts.length === 3 &&
    normalizeTemplateFormat(parts[0] ?? "") === format &&
    Boolean(parts[1]?.trim()) &&
    Boolean(parts[2]?.trim())
  );
}

function stringListOption(options: SlotOptions, key: string): string[] {
  const value = options[key];
  if (!Array.isArray(value)) return [];
  return value.map((item) => typeof item === "string" ? item : String(item ?? ""));
}

function stringMapOption(options: SlotOptions, key: string): Record<string, string> {
  const value = options[key];
  if (!isRecord(value)) return {};
  return Object.fromEntries(
    Object.entries(value).map(([itemKey, item]) => [
      itemKey,
      typeof item === "string" ? item : String(item ?? ""),
    ])
  );
}

function optionText(options: SlotOptions, key: string, fallback = ""): string {
  const value = options[key];
  if (typeof value === "string" || typeof value === "number") return String(value);
  return fallback;
}

function exposesInternalSemanticIdentifier(value: string): boolean {
  return (
    SEMANTIC_FACT_KEY_FRAGMENT_PATTERN.test(value)
    || SEMANTIC_INTERNAL_IDENTIFIER_PATTERN.test(value)
  );
}

function normalizeSlotOptions(slot: AttachmentTemplateSlot): SlotOptions {
  let options = cloneOptions(slot.options);
  const compositionMode = options.composition_mode;
  if (compositionMode === undefined || compositionMode === "deterministic") {
    options = deterministicOptions(options);
  } else if (compositionMode === "semantic") {
    if (typeof options.semantic_instruction === "string") {
      options.semantic_instruction = options.semantic_instruction.trim();
    }
    if (Array.isArray(options.allowed_fact_refs)) {
      options.allowed_fact_refs = options.allowed_fact_refs.map((item) =>
        String(item ?? "").trim()
      );
    }
    if (isRecord(options.fact_ref_labels)) {
      options.fact_ref_labels = Object.fromEntries(
        Object.entries(options.fact_ref_labels).map(([key, value]) => [
          key.trim(),
          typeof value === "string" ? value.trim() : value,
        ])
      );
    }
    if (options.require_fact_refs === undefined) options.require_fact_refs = true;
  }
  if (Array.isArray(options.columns)) {
    options.columns = options.columns.map((item) => String(item ?? "").trim());
  }
  if (Array.isArray(options.formula_columns)) {
    options.formula_columns = options.formula_columns.map((item) => String(item ?? "").trim());
  }
  if (isRecord(options.column_map)) {
    options.column_map = Object.fromEntries(
      Object.entries(options.column_map).map(([key, value]) => [
        key.trim(),
        String(value ?? "").trim(),
      ])
    );
  }
  for (const key of ["alignment", "font_name", "sheet"] as const) {
    if (typeof options[key] === "string") options[key] = options[key].trim();
  }
  for (const key of NUMERIC_OPTION_FIELDS) {
    const value = options[key];
    if (typeof value === "string" && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) options[key] = parsed;
    }
  }

  const format = targetFormat(slot.target);
  const kind = targetKind(slot.target);
  if (format === "pdf" && (kind === "overlay" || kind === "acroform")) {
    if (!options.font_name) options.font_name = "Helvetica";
    if (options.font_size === undefined) options.font_size = 10;
    if (options.minimum_font_size === undefined) options.minimum_font_size = 6;
    if (options.leading_factor === undefined) options.leading_factor = 1.2;
    if (options.max_lines === undefined) options.max_lines = 1;
    if (!options.alignment) options.alignment = "left";
    if (kind === "overlay" && options.y_from_top === undefined) options.y_from_top = false;
  }
  return options;
}

function hasValidTableColumns(options: SlotOptions): boolean {
  const columns = options.columns;
  const columnMap = options.column_map;
  return (
    Array.isArray(columns)
    && columns.length > 0
    && columns.every((item) => typeof item === "string" && item.trim())
  ) || (
    isRecord(columnMap)
    && Object.keys(columnMap).length > 0
    && Object.entries(columnMap).every(([key, value]) =>
      key.trim() && typeof value === "string" && value.trim()
    )
  );
}

function specializedOptionsError(slots: AttachmentTemplateSlot[]): string {
  for (const slot of slots) {
    const options = slot.options ?? {};
    const compositionMode = options.composition_mode ?? "deterministic";
    if (compositionMode !== "deterministic" && compositionMode !== "semantic") {
      return `槽位 ${slot.slot_id} 的编制模式无效`;
    }
    if (compositionMode === "semantic") {
      if (slot.value_type !== "narrative_blocks") {
        return `槽位 ${slot.slot_id} 仅叙述段落支持语义编制`;
      }
      const instruction = options.semantic_instruction;
      if (
        typeof instruction !== "string"
        || !instruction.trim()
        || instruction.trim().length > 4_000
      ) {
        return `槽位 ${slot.slot_id} 的语义指令必须为 1-4000 个字符`;
      }
      const factRefs = options.allowed_fact_refs;
      if (!Array.isArray(factRefs) || factRefs.length === 0) {
        return `槽位 ${slot.slot_id} 至少需要一个允许事实引用`;
      }
      const normalizedRefs = factRefs.map((value) => String(value ?? "").trim());
      if (
        normalizedRefs.some((value) => !value || !isAttachmentTemplateFactKey(value))
        || new Set(normalizedRefs).size !== normalizedRefs.length
      ) {
        return `槽位 ${slot.slot_id} 的允许事实引用必须是非空、唯一的规范 fact key`;
      }
      const labels = options.fact_ref_labels;
      if (
        !isRecord(labels)
        || Object.keys(labels).length !== normalizedRefs.length
        || normalizedRefs.some((factRef) => !Object.prototype.hasOwnProperty.call(labels, factRef))
      ) {
        return `槽位 ${slot.slot_id} 的外发标签必须与允许事实引用逐项对应`;
      }
      if (
        Object.values(labels).some((label) =>
          typeof label !== "string"
          || !label.trim()
          || label.trim().length > 200
        )
      ) {
        return `槽位 ${slot.slot_id} 的外发标签必须为 1-200 个字符`;
      }
      if (
        [instruction, ...Object.values(labels).map((label) => String(label))]
          .some((value) => exposesInternalSemanticIdentifier(value.trim()))
      ) {
        return `槽位 ${slot.slot_id} 的语义指令和外发标签不能包含内部标识符`;
      }
      if (options.require_fact_refs === false) {
        return `槽位 ${slot.slot_id} 不能关闭事实引用约束`;
      }
    }
    if (slot.value_type === "table_rows" && !hasValidTableColumns(options)) {
      return `槽位 ${slot.slot_id} 必须配置字段列表或模板列映射`;
    }

    const format = targetFormat(slot.target);
    const kind = targetKind(slot.target);
    if (format === "xlsx" && options.prototype_row !== undefined) {
      const row = Number(options.prototype_row);
      if (!Number.isInteger(row) || row < 1) return `槽位 ${slot.slot_id} 的原型行必须是正整数`;
    }
    if (format !== "pdf" || (kind !== "overlay" && kind !== "acroform")) continue;

    const fontSize = Number(options.font_size);
    const minimumFontSize = Number(options.minimum_font_size);
    const leadingFactor = Number(options.leading_factor);
    const maxLines = Number(options.max_lines);
    if (!String(options.font_name ?? "").trim()) return `槽位 ${slot.slot_id} 必须配置 PDF 字体`;
    if (!(fontSize > 0) || !(minimumFontSize > 0) || !(leadingFactor > 0) || !Number.isInteger(maxLines) || maxLines < 1) {
      return `槽位 ${slot.slot_id} 的 PDF 字号、最小字号、行距和最大行数必须大于 0`;
    }
    if (minimumFontSize > fontSize) return `槽位 ${slot.slot_id} 的最小字号不能大于字号`;
    if (!new Set(["left", "center", "right"]).has(String(options.alignment))) {
      return `槽位 ${slot.slot_id} 的 PDF 对齐方式无效`;
    }
    if (kind === "overlay") {
      const page = Number(options.page);
      const x = Number(options.x);
      const y = Number(options.y);
      const width = Number(options.width);
      const height = Number(options.height);
      if (!Number.isInteger(page) || page < 1 || x < 0 || y < 0 || !(width > 0) || !(height > 0)) {
        return `槽位 ${slot.slot_id} 必须配置有效的 PDF 页码和覆盖区域`;
      }
    }
  }
  return "";
}

export function initialSlots(file: AttachmentTemplateFile): AttachmentTemplateSlot[] {
  if (file.binding_manifest?.slots?.length) {
    return file.binding_manifest.slots.map((slot) => ({
      ...slot,
      options: cloneOptions(slot.options),
    }));
  }
  const candidates = inspectionCandidates(file);
  const mapped = candidates.slice(0, 100).map((candidate, index) => {
    const valueType = canonicalValueType(recordString(candidate, "value_type", "field_kind"));
    const options = candidateOptions(candidate);
    return {
      slot_id: recordString(candidate, "slot_id", "candidate_id", "suggested_slot_id") || `slot_${index + 1}`,
      target: recordString(candidate, "target", "address", "location"),
      value_type: valueType,
      source: recordString(candidate, "source", "suggested_source"),
      required: candidate.required === true,
      style_policy: canonicalStylePolicy(recordString(candidate, "style_policy"), valueType),
      overflow_policy: canonicalOverflowPolicy(recordString(candidate, "overflow_policy"), valueType),
      missing_policy: canonicalMissingPolicy(recordString(candidate, "missing_policy")),
      ...(Object.keys(options).length ? { options } : {}),
    };
  });
  return mapped.length
    ? mapped
    : [createDefaultAttachmentTemplateSlot()];
}

function updateOption(options: SlotOptions, key: string, value: unknown): SlotOptions {
  const next = cloneOptions(options);
  if (value === undefined) delete next[key];
  else next[key] = value;
  return next;
}

function StringListOptionEditor({
  index,
  label,
  optionKey,
  options,
  required = false,
  disabled,
  onChange,
}: {
  index: number;
  label: string;
  optionKey: string;
  options: SlotOptions;
  required?: boolean;
  disabled: boolean;
  onChange: (options: SlotOptions) => void;
}) {
  const stored = stringListOption(options, optionKey);
  const values = stored.length ? stored : required ? [""] : [];

  function change(nextValues: string[]) {
    onChange(updateOption(options, optionKey, nextValues.length ? nextValues : undefined));
  }

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium">{label}</span>
        <Button type="button" variant="outline" size="xs" onClick={() => change([...values, ""])} disabled={disabled}>
          <Plus data-icon="inline-start" />添加
        </Button>
      </div>
      {values.map((value, valueIndex) => (
        <div className="flex items-center gap-1.5" key={`${optionKey}-${valueIndex}`}>
          <Input
            aria-label={`槽位 ${index + 1} ${label} ${valueIndex + 1}`}
            className="h-7 min-w-32 font-mono text-xs"
            value={value}
            onChange={(event) => change(values.map((item, itemIndex) => itemIndex === valueIndex ? event.target.value : item))}
            disabled={disabled}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            title={`删除${label}`}
            onClick={() => change(values.filter((_, itemIndex) => itemIndex !== valueIndex))}
            disabled={disabled || (required && values.length === 1)}
          >
            <X /><span className="sr-only">删除{label} {valueIndex + 1}</span>
          </Button>
        </div>
      ))}
    </div>
  );
}

function SemanticOptionsEditor({
  index,
  options,
  disabled,
  onChange,
}: {
  index: number;
  options: SlotOptions;
  disabled: boolean;
  onChange: (options: SlotOptions) => void;
}) {
  const factRefs = stringListOption(options, "allowed_fact_refs");
  const labels = stringMapOption(options, "fact_ref_labels");
  const entries = (factRefs.length ? factRefs : [""]).map((factRef) => [
    factRef,
    labels[factRef] ?? "",
  ] as const);

  function changeEntries(nextEntries: ReadonlyArray<readonly [string, string]>) {
    const next = cloneOptions(options);
    next.composition_mode = "semantic";
    next.allowed_fact_refs = nextEntries.map(([factRef]) => factRef);
    next.fact_ref_labels = Object.fromEntries(nextEntries);
    next.require_fact_refs = true;
    onChange(next);
  }

  return (
    <div className="flex min-w-0 flex-col gap-3 lg:col-span-2">
      <Field className="gap-1.5">
        <FieldLabel className="text-xs" htmlFor={`slot-${index}-semantic-instruction`}>
          语义指令
        </FieldLabel>
        <Textarea
          id={`slot-${index}-semantic-instruction`}
          aria-label={`槽位 ${index + 1} 语义指令`}
          className="min-h-24 resize-y text-xs"
          maxLength={4_000}
          value={optionText(options, "semantic_instruction")}
          onChange={(event) => onChange(updateOption(options, "semantic_instruction", event.target.value))}
          disabled={disabled}
        />
      </Field>
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-medium">允许事实引用与外发标签</span>
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={() => changeEntries([...entries, ["", ""]])}
            disabled={disabled}
          >
            <Plus data-icon="inline-start" />添加
          </Button>
        </div>
        <div className="grid grid-cols-[minmax(14rem,1fr)_minmax(12rem,1fr)_1.75rem] gap-1.5 text-[11px] text-muted-foreground">
          <span>事实引用</span>
          <span>外发标签</span>
          <span />
        </div>
        {entries.map(([factRef, label], entryIndex) => (
          <div
            className="grid grid-cols-[minmax(14rem,1fr)_minmax(12rem,1fr)_1.75rem] items-center gap-1.5"
            key={`semantic-fact-${entryIndex}`}
          >
            <Input
              aria-label={`槽位 ${index + 1} 允许事实引用 ${entryIndex + 1}`}
              className="h-7 font-mono text-xs"
              maxLength={191}
              placeholder="entity.registered_address"
              value={factRef}
              onChange={(event) => changeEntries(entries.map((entry, itemIndex) =>
                itemIndex === entryIndex ? [event.target.value, entry[1]] : entry
              ))}
              disabled={disabled}
            />
            <Input
              aria-label={`槽位 ${index + 1} 外发标签 ${entryIndex + 1}`}
              className="h-7 text-xs"
              maxLength={200}
              value={label}
              onChange={(event) => changeEntries(entries.map((entry, itemIndex) =>
                itemIndex === entryIndex ? [entry[0], event.target.value] : entry
              ))}
              disabled={disabled}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              title="删除事实引用"
              onClick={() => changeEntries(entries.filter((_, itemIndex) => itemIndex !== entryIndex))}
              disabled={disabled || entries.length === 1}
            >
              <X /><span className="sr-only">删除事实引用 {entryIndex + 1}</span>
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}

function TableColumnOptionsEditor({
  index,
  options,
  disabled,
  onChange,
}: {
  index: number;
  options: SlotOptions;
  disabled: boolean;
  onChange: (options: SlotOptions) => void;
}) {
  const mapMode = Object.prototype.hasOwnProperty.call(options, "column_map");
  const columnMap = stringMapOption(options, "column_map");
  const mapEntries = Object.keys(columnMap).length ? Object.entries(columnMap) : [["", ""]];

  function selectMode(mode: "columns" | "column_map") {
    if ((mode === "column_map") === mapMode) return;
    const next = cloneOptions(options);
    if (mode === "column_map") {
      const columns = stringListOption(options, "columns");
      next.column_map = Object.fromEntries((columns.length ? columns : [""]).map((column) => [column, column]));
      delete next.columns;
    } else {
      const values = Object.values(columnMap);
      next.columns = values.length ? values : [""];
      delete next.column_map;
    }
    onChange(next);
  }

  function changeMap(entries: string[][]) {
    onChange(updateOption(options, "column_map", Object.fromEntries(entries.map(([key, value]) => [key, value]))));
  }

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-medium">列合同</span>
        <div className="inline-flex rounded-md border bg-background p-0.5" role="group" aria-label={`槽位 ${index + 1} 列合同模式`}>
          <Button type="button" variant={mapMode ? "ghost" : "secondary"} size="xs" aria-pressed={!mapMode} onClick={() => selectMode("columns")} disabled={disabled}>字段列表</Button>
          <Button type="button" variant={mapMode ? "secondary" : "ghost"} size="xs" aria-pressed={mapMode} onClick={() => selectMode("column_map")} disabled={disabled}>模板列映射</Button>
        </div>
      </div>
      {mapMode ? (
        <div className="flex flex-col gap-1.5">
          {mapEntries.map(([header, field], entryIndex) => (
            <div className="grid grid-cols-[minmax(8rem,1fr)_minmax(8rem,1fr)_1.75rem] items-center gap-1.5" key={`${header}-${entryIndex}`}>
              <Input aria-label={`槽位 ${index + 1} 模板列 ${entryIndex + 1}`} className="h-7 font-mono text-xs" value={header} placeholder="模板表头" onChange={(event) => changeMap(mapEntries.map((entry, itemIndex) => itemIndex === entryIndex ? [event.target.value, entry[1]] : entry))} disabled={disabled} />
              <Input aria-label={`槽位 ${index + 1} 数据字段 ${entryIndex + 1}`} className="h-7 font-mono text-xs" value={field} placeholder="数据字段" onChange={(event) => changeMap(mapEntries.map((entry, itemIndex) => itemIndex === entryIndex ? [entry[0], event.target.value] : entry))} disabled={disabled} />
              <Button type="button" variant="ghost" size="icon-xs" title="删除列映射" onClick={() => changeMap(mapEntries.filter((_, itemIndex) => itemIndex !== entryIndex))} disabled={disabled || mapEntries.length === 1}><X /><span className="sr-only">删除列映射 {entryIndex + 1}</span></Button>
            </div>
          ))}
          <Button type="button" variant="outline" size="xs" className="w-fit" onClick={() => changeMap([...mapEntries, ["", ""]])} disabled={disabled || mapEntries.some(([header]) => !header)}><Plus data-icon="inline-start" />添加映射</Button>
        </div>
      ) : (
        <StringListOptionEditor index={index} label="数据字段" optionKey="columns" options={options} required disabled={disabled} onChange={onChange} />
      )}
    </div>
  );
}

function OptionInput({
  index,
  label,
  optionKey,
  options,
  disabled,
  fallback,
  type = "text",
  min,
  step,
  integer = false,
  onChange,
}: {
  index: number;
  label: string;
  optionKey: string;
  options: SlotOptions;
  disabled: boolean;
  fallback?: string | number;
  type?: "text" | "number";
  min?: number;
  step?: number;
  integer?: boolean;
  onChange: (options: SlotOptions) => void;
}) {
  const id = `slot-${index}-${optionKey}`;
  return (
    <Field className="gap-1">
      <FieldLabel className="text-xs" htmlFor={id}>{label}</FieldLabel>
      <Input
        id={id}
        aria-label={`槽位 ${index + 1} ${label}`}
        className="h-7 min-w-24 font-mono text-xs"
        type={type}
        min={min}
        step={step}
        value={optionText(options, optionKey, fallback === undefined ? "" : String(fallback))}
        onChange={(event) => {
          const raw = event.target.value;
          if (type === "text") onChange(updateOption(options, optionKey, raw));
          else if (!raw) onChange(updateOption(options, optionKey, undefined));
          else {
            const parsed = integer ? Number.parseInt(raw, 10) : Number(raw);
            onChange(updateOption(options, optionKey, Number.isFinite(parsed) ? parsed : raw));
          }
        }}
        disabled={disabled}
      />
    </Field>
  );
}

function PdfOptionsEditor({
  index,
  kind,
  options,
  disabled,
  onChange,
}: {
  index: number;
  kind: string;
  options: SlotOptions;
  disabled: boolean;
  onChange: (options: SlotOptions) => void;
}) {
  const overlay = kind === "overlay";
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-3">
      <span className="text-xs font-medium">PDF {overlay ? "覆盖区域" : "表单字段"}</span>
      {overlay && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <OptionInput index={index} label="页码" optionKey="page" options={options} type="number" min={1} step={1} integer disabled={disabled} onChange={onChange} />
          <OptionInput index={index} label="X" optionKey="x" options={options} type="number" min={0} step={0.5} disabled={disabled} onChange={onChange} />
          <OptionInput index={index} label="Y" optionKey="y" options={options} type="number" min={0} step={0.5} disabled={disabled} onChange={onChange} />
          <OptionInput index={index} label="宽度" optionKey="width" options={options} type="number" min={0.5} step={0.5} disabled={disabled} onChange={onChange} />
          <OptionInput index={index} label="高度" optionKey="height" options={options} type="number" min={0.5} step={0.5} disabled={disabled} onChange={onChange} />
          <Field className="justify-end gap-1">
            <FieldLabel className="flex h-7 items-center gap-2 text-xs" htmlFor={`slot-${index}-y-from-top`}>
              <Checkbox id={`slot-${index}-y-from-top`} aria-label={`槽位 ${index + 1} Y 坐标从页顶计算`} checked={options.y_from_top === true} onCheckedChange={(checked) => onChange(updateOption(options, "y_from_top", checked === true))} disabled={disabled} />
              从页顶计算 Y
            </FieldLabel>
          </Field>
        </div>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <OptionInput index={index} label="字体" optionKey="font_name" options={options} fallback="Helvetica" disabled={disabled} onChange={onChange} />
        <OptionInput index={index} label="字号" optionKey="font_size" options={options} fallback={10} type="number" min={0.5} step={0.5} disabled={disabled} onChange={onChange} />
        <OptionInput index={index} label="最小字号" optionKey="minimum_font_size" options={options} fallback={6} type="number" min={0.5} step={0.5} disabled={disabled} onChange={onChange} />
        <OptionInput index={index} label="最大行数" optionKey="max_lines" options={options} fallback={1} type="number" min={1} step={1} integer disabled={disabled} onChange={onChange} />
        <OptionInput index={index} label="行距系数" optionKey="leading_factor" options={options} fallback={1.2} type="number" min={0.1} step={0.1} disabled={disabled} onChange={onChange} />
        <Field className="gap-1">
          <FieldLabel className="text-xs">对齐</FieldLabel>
          <Select value={optionText(options, "alignment", "left")} onValueChange={(value) => onChange(updateOption(options, "alignment", value))} disabled={disabled}>
            <SelectTrigger className="h-7 min-w-24" aria-label={`槽位 ${index + 1} 对齐`}><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="left">左对齐</SelectItem><SelectItem value="center">居中</SelectItem><SelectItem value="right">右对齐</SelectItem></SelectContent>
          </Select>
        </Field>
      </div>
    </div>
  );
}

function shouldShowBindingOptions(fileFormat: string, slot: AttachmentTemplateSlot): boolean {
  const format = normalizeTemplateFormat(fileFormat) || targetFormat(slot.target);
  const kind = targetKind(slot.target);
  return slotCompositionMode(slot) === "semantic"
    || slot.value_type === "table_rows"
    || (format === "pdf" && (kind === "overlay" || kind === "acroform"))
    || (format === "xlsx" && ["cell", "range", "named-range", "table"].includes(kind));
}

function BindingOptionsEditor({
  fileFormat,
  slot,
  index,
  disabled,
  onChange,
}: {
  fileFormat: string;
  slot: AttachmentTemplateSlot;
  index: number;
  disabled: boolean;
  onChange: (options: SlotOptions) => void;
}) {
  const format = normalizeTemplateFormat(fileFormat) || targetFormat(slot.target);
  const kind = targetKind(slot.target);
  const options = slot.options ?? {};
  const xlsxTable = format === "xlsx" && kind === "table" && slot.value_type === "table_rows";
  const xlsxSheet = format === "xlsx" && (kind === "cell" || kind === "range");
  const xlsxNamedRange = format === "xlsx" && kind === "named-range";
  const pdf = format === "pdf" && (kind === "overlay" || kind === "acroform");

  return (
    <div className="grid min-w-[min(52rem,calc(96vw-3rem))] gap-4 lg:grid-cols-2">
      {slotCompositionMode(slot) === "semantic" && (
        <SemanticOptionsEditor index={index} options={options} disabled={disabled} onChange={onChange} />
      )}
      {slot.value_type === "table_rows" && <TableColumnOptionsEditor index={index} options={options} disabled={disabled} onChange={onChange} />}
      {xlsxTable && (
        <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
          <OptionInput index={index} label="原型行" optionKey="prototype_row" options={options} type="number" min={1} step={1} integer disabled={disabled} onChange={onChange} />
          <StringListOptionEditor index={index} label="公式列" optionKey="formula_columns" options={options} disabled={disabled} onChange={onChange} />
        </div>
      )}
      {xlsxSheet && <OptionInput index={index} label="工作表" optionKey="sheet" options={options} disabled={disabled} onChange={onChange} />}
      {xlsxNamedRange && (
        <Field className="justify-end gap-1">
          <FieldLabel className="flex h-7 items-center gap-2 text-xs" htmlFor={`slot-${index}-allow-multiple`}>
            <Checkbox id={`slot-${index}-allow-multiple`} aria-label={`槽位 ${index + 1} 允许多个命名区域`} checked={options.allow_multiple === true} onCheckedChange={(checked) => onChange(updateOption(options, "allow_multiple", checked === true))} disabled={disabled} />
            允许多个命名区域
          </FieldLabel>
        </Field>
      )}
      {pdf && (
        <div className="lg:col-span-2">
          <PdfOptionsEditor index={index} kind={kind} options={options} disabled={disabled} onChange={onChange} />
        </div>
      )}
    </div>
  );
}

function FileMetadataDialog({
  versionId,
  file,
  open,
  onOpenChange,
}: {
  versionId: string;
  file: AttachmentTemplateFile;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [documentCode, setDocumentCode] = useState(file.document_code);
  const [displayName, setDisplayName] = useState(file.display_name);
  const [sortOrder, setSortOrder] = useState(String(file.sort_order));
  const [submitted, setSubmitted] = useState(false);
  const mutation = useUpdateAttachmentTemplateFile(versionId, file.id);

  useEffect(() => {
    if (!open) return;
    setDocumentCode(file.document_code);
    setDisplayName(file.display_name);
    setSortOrder(String(file.sort_order));
    setSubmitted(false);
    mutation.reset();
  }, [open, file, mutation.reset]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
    if (!isAttachmentTemplateDocumentCode(documentCode) || !displayName.trim()) return;
    try {
      await mutation.updateFile({
        document_code: documentCode.trim(),
        display_name: displayName.trim(),
        sort_order: Number.parseInt(sortOrder, 10) || 0,
        revision: file.revision,
      });
      toast.success("模板文件信息已更新");
      onOpenChange(false);
    } catch {
      // The mutation error is shown below.
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !mutation.isMutating && onOpenChange(next)}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>编辑模板文件</DialogTitle>
          <DialogDescription>文件名不是业务合同，请确认附件编码和最终显示名称。</DialogDescription>
        </DialogHeader>
        <form className="flex flex-col gap-5" onSubmit={submit}>
          <FieldGroup>
            <Field data-invalid={(submitted && !isAttachmentTemplateDocumentCode(documentCode)) || undefined}>
              <FieldLabel htmlFor={`document-code-${file.id}`}>附件业务编码</FieldLabel>
              <Input id={`document-code-${file.id}`} value={documentCode} onChange={(event) => setDocumentCode(event.target.value)} disabled={mutation.isMutating} />
              {submitted && !isAttachmentTemplateDocumentCode(documentCode) && (
                <FieldError>使用小写字母开头，且仅包含小写字母、数字和下划线（至少 2 个字符）</FieldError>
              )}
            </Field>
            <Field data-invalid={(submitted && !displayName.trim()) || undefined}>
              <FieldLabel htmlFor={`display-name-${file.id}`}>附件显示名称</FieldLabel>
              <Input id={`display-name-${file.id}`} value={displayName} onChange={(event) => setDisplayName(event.target.value)} disabled={mutation.isMutating} />
              {submitted && !displayName.trim() && <FieldError>请输入附件显示名称</FieldError>}
            </Field>
            <Field>
              <FieldLabel htmlFor={`sort-order-${file.id}`}>交付顺序</FieldLabel>
              <Input id={`sort-order-${file.id}`} type="number" min={0} value={sortOrder} onChange={(event) => setSortOrder(event.target.value)} disabled={mutation.isMutating} />
            </Field>
          </FieldGroup>
          {mutation.error && <Alert variant="destructive"><AlertDescription>{mutation.error}</AlertDescription></Alert>}
          <DialogFooter className="gap-2 sm:gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isMutating}>取消</Button>
            <Button type="submit" disabled={mutation.isMutating}>{mutation.isMutating && <Loader2 className="animate-spin" data-icon="inline-start" />}保存</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function SlotContractDialog({
  versionId,
  file,
  open,
  onOpenChange,
}: {
  versionId: string;
  file: AttachmentTemplateFile;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [slots, setSlots] = useState<AttachmentTemplateSlot[]>(() => initialSlots(file));
  const [error, setError] = useState("");
  const mutation = useCompileAttachmentTemplateFile(versionId, file.id);

  useEffect(() => {
    if (!open) return;
    setSlots(initialSlots(file));
    setError("");
    mutation.reset();
  }, [open, file, mutation.reset]);

  function updateSlot<K extends keyof AttachmentTemplateSlot>(
    index: number,
    key: K,
    value: AttachmentTemplateSlot[K]
  ) {
    setSlots((current) => current.map((slot, slotIndex) =>
      slotIndex === index ? { ...slot, [key]: value } : slot
    ));
  }

  function updateSlotValueType(index: number, valueType: AttachmentTemplateValueType) {
    setSlots((current) => current.map((slot, slotIndex) => {
      if (slotIndex !== index) return slot;
      const wasTable = slot.value_type === "table_rows";
      const isTable = valueType === "table_rows";
      return {
        ...slot,
        value_type: valueType,
        style_policy: isTable && !wasTable
          ? "clone_prototype_row"
          : !isTable && wasTable && slot.style_policy === "clone_prototype_row"
            ? "inherit_template"
            : slot.style_policy,
        overflow_policy: isTable && !wasTable
          ? "extend_rows"
          : !isTable && wasTable && slot.overflow_policy === "extend_rows"
            ? valueType === "narrative_blocks" ? "continue_paragraphs" : "error"
            : slot.overflow_policy,
        options: valueType !== "narrative_blocks" && slotCompositionMode(slot) === "semantic"
          ? deterministicOptions(slot.options)
          : slot.options,
      };
    }));
  }

  function updateSlotCompositionMode(
    index: number,
    compositionMode: AttachmentTemplateCompositionMode
  ) {
    setSlots((current) => current.map((slot, slotIndex) => {
      if (slotIndex !== index) return slot;
      if (compositionMode === "deterministic") {
        return { ...slot, options: deterministicOptions(slot.options) };
      }
      if (slot.value_type !== "narrative_blocks") return slot;
      const options = cloneOptions(slot.options);
      options.composition_mode = "semantic";
      if (typeof options.semantic_instruction !== "string") options.semantic_instruction = "";
      if (!Array.isArray(options.allowed_fact_refs) || !options.allowed_fact_refs.length) {
        options.allowed_fact_refs = [""];
      }
      if (!isRecord(options.fact_ref_labels)) options.fact_ref_labels = { "": "" };
      options.require_fact_refs = true;
      return { ...slot, options };
    }));
  }

  function updateSlotOptions(index: number, options: SlotOptions) {
    setSlots((current) => current.map((slot, slotIndex) =>
      slotIndex === index ? { ...slot, options } : slot
    ));
  }

  async function compile() {
    const normalized = slots.map((slot) => ({
      ...slot,
      slot_id: slot.slot_id.trim(),
      target: slot.target.trim(),
      source: slot.source.trim(),
      missing_policy: slot.required ? "block" as const : slot.missing_policy ?? "block",
      options: normalizeSlotOptions(slot),
    }));
    if (!normalized.length || normalized.some((slot) =>
      !slot.slot_id
      || !slot.target
      || (slotCompositionMode(slot) === "deterministic" && !slot.source)
    )) {
      setError("每个槽位都必须填写槽位 ID、模板目标；确定性编制还必须填写数据来源");
      return;
    }
    if (normalized.some((slot) => !isAttachmentTemplateSlotId(slot.slot_id))) {
      setError("槽位 ID 必须以小写字母开头，且仅包含小写字母、数字、点、下划线或连字符（至少 2 个字符）");
      return;
    }
    if (normalized.some((slot) =>
      slotCompositionMode(slot) === "deterministic"
      && !isAttachmentTemplateSourcePath(slot.source)
    )) {
      setError("数据来源必须是小写 document.* 形式的确定性路径");
      return;
    }
    if (new Set(normalized.map((slot) => slot.slot_id)).size !== normalized.length) {
      setError("槽位 ID 不能重复");
      return;
    }
    const fileFormat = normalizeTemplateFormat(file.extension);
    if (normalized.some((slot) => !isExplicitTemplateTarget(slot.target, fileFormat))) {
      setError(`模板目标必须是 ${fileFormat || "文件格式"}:<类型>:<定位符> 形式`);
      return;
    }
    if (new Set(normalized.map((slot) => slot.target)).size !== normalized.length) {
      setError("模板目标不能重复");
      return;
    }
    const optionsError = specializedOptionsError(normalized);
    if (optionsError) {
      setError(optionsError);
      return;
    }
    const manifest: AttachmentTemplateBindingManifest = {
      contract_version: file.binding_manifest?.contract_version ?? "1.0",
      document_code: file.document_code,
      source_template_sha256: file.source_sha256,
      slots: normalized,
      fixed_regions: file.binding_manifest?.fixed_regions ?? [],
      forbidden_output_patterns: ["[[cite:", "evidence_id", "chunk_id", "claim_id"],
    };
    try {
      await mutation.compileFile({
        binding_manifest: manifest,
        revision: file.revision,
      });
      toast.success("槽位合同已编译，仍需执行版本校验");
      onOpenChange(false);
    } catch {
      // The mutation error is shown below.
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !mutation.isMutating && onOpenChange(next)}>
      <DialogContent className="flex max-h-[92svh] max-w-[96vw] flex-col overflow-hidden sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>确认槽位合同：{file.display_name}</DialogTitle>
          <DialogDescription>逐项确认模板目标、编制模式与数据合同。</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>槽位 ID</TableHead>
                <TableHead>模板目标</TableHead>
                <TableHead>数据来源</TableHead>
                <TableHead>值类型</TableHead>
                <TableHead>编制模式</TableHead>
                <TableHead>样式策略</TableHead>
                <TableHead>溢出策略</TableHead>
                <TableHead>缺失策略</TableHead>
                <TableHead>必填</TableHead>
                <TableHead><span className="sr-only">删除</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {slots.map((slot, index) => (
                <Fragment key={`${slot.slot_id}-${index}`}>
                  <TableRow>
                  <TableCell><Input aria-label={`槽位 ${index + 1} ID`} className="min-w-36" value={slot.slot_id} onChange={(event) => updateSlot(index, "slot_id", event.target.value)} disabled={mutation.isMutating} /></TableCell>
                  <TableCell><Input aria-label={`槽位 ${index + 1} 模板目标`} className="min-w-64 font-mono text-xs" value={slot.target} onChange={(event) => updateSlot(index, "target", event.target.value)} disabled={mutation.isMutating} /></TableCell>
                  <TableCell><Input aria-label={`槽位 ${index + 1} 数据来源`} className="min-w-64 font-mono text-xs" value={slot.source} onChange={(event) => updateSlot(index, "source", event.target.value)} disabled={mutation.isMutating || slotCompositionMode(slot) === "semantic"} placeholder={slotCompositionMode(slot) === "semantic" ? "" : "document.company_profile.overview"} /></TableCell>
                  <TableCell>
                    <Select value={slot.value_type} onValueChange={(value) => updateSlotValueType(index, value as AttachmentTemplateValueType)} disabled={mutation.isMutating}>
                      <SelectTrigger className="min-w-36" aria-label={`槽位 ${index + 1} 值类型`}><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="scalar">标量</SelectItem><SelectItem value="narrative_blocks">叙述段落</SelectItem><SelectItem value="table_rows">表格行</SelectItem></SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>
                    <div className="inline-flex min-w-44 rounded-md border bg-background p-0.5" role="group" aria-label={`槽位 ${index + 1} 编制模式`}>
                      <Button
                        type="button"
                        variant={slotCompositionMode(slot) === "deterministic" ? "secondary" : "ghost"}
                        size="xs"
                        className="flex-1"
                        aria-label={`槽位 ${index + 1} 确定性编制`}
                        aria-pressed={slotCompositionMode(slot) === "deterministic"}
                        onClick={() => updateSlotCompositionMode(index, "deterministic")}
                        disabled={mutation.isMutating}
                      >
                        确定性
                      </Button>
                      <Button
                        type="button"
                        variant={slotCompositionMode(slot) === "semantic" ? "secondary" : "ghost"}
                        size="xs"
                        className="flex-1"
                        aria-label={`槽位 ${index + 1} 语义编制`}
                        aria-pressed={slotCompositionMode(slot) === "semantic"}
                        onClick={() => updateSlotCompositionMode(index, "semantic")}
                        disabled={mutation.isMutating || slot.value_type !== "narrative_blocks"}
                      >
                        语义
                      </Button>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Select value={slot.style_policy} onValueChange={(value) => updateSlot(index, "style_policy", value as AttachmentTemplateStylePolicy)} disabled={mutation.isMutating}>
                      <SelectTrigger className="min-w-44" aria-label={`槽位 ${index + 1} 样式策略`}><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="inherit_template">继承模板</SelectItem><SelectItem value="clone_prototype_row">复制原型行</SelectItem><SelectItem value="explicit">显式样式</SelectItem></SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>
                    <Select value={slot.overflow_policy} onValueChange={(value) => updateSlot(index, "overflow_policy", value as AttachmentTemplateOverflowPolicy)} disabled={mutation.isMutating}>
                      <SelectTrigger className="min-w-44" aria-label={`槽位 ${index + 1} 溢出策略`}><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="error">超限报错</SelectItem><SelectItem value="continue_paragraphs">延续段落</SelectItem><SelectItem value="extend_rows">扩展行</SelectItem><SelectItem value="truncate">截断</SelectItem><SelectItem value="shrink_font">缩小字体</SelectItem></SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>
                    <Select value={slot.required ? "block" : slot.missing_policy ?? "block"} onValueChange={(value) => updateSlot(index, "missing_policy", value as AttachmentTemplateMissingPolicy)} disabled={mutation.isMutating || slot.required}>
                      <SelectTrigger className="min-w-32" aria-label={`槽位 ${index + 1} 缺失策略`}><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="block">阻断</SelectItem><SelectItem value="omit_slot">省略槽位</SelectItem><SelectItem value="omit_sentence">省略句段</SelectItem><SelectItem value="empty">留空</SelectItem></SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell><Checkbox aria-label={`槽位 ${index + 1} 必填`} checked={slot.required} onCheckedChange={(checked) => setSlots((current) => current.map((item, slotIndex) => slotIndex === index ? { ...item, required: checked === true, missing_policy: checked === true ? "block" : item.missing_policy } : item))} disabled={mutation.isMutating} /></TableCell>
                  <TableCell><Button type="button" variant="ghost" size="icon-sm" title="删除槽位" disabled={mutation.isMutating || slots.length === 1} onClick={() => setSlots((current) => current.filter((_, slotIndex) => slotIndex !== index))}><X /><span className="sr-only">删除槽位 {index + 1}</span></Button></TableCell>
                  </TableRow>
                  {shouldShowBindingOptions(file.extension, slot) && (
                    <TableRow className="hover:bg-transparent">
                      <TableCell colSpan={10} className="bg-muted/30 px-3 py-3">
                        <BindingOptionsEditor fileFormat={file.extension} slot={slot} index={index} disabled={mutation.isMutating} onChange={(options) => updateSlotOptions(index, options)} />
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button type="button" variant="outline" onClick={() => setSlots((current) => [...current, createDefaultAttachmentTemplateSlot(`slot_${current.length + 1}`)])} disabled={mutation.isMutating}>
            <Plus data-icon="inline-start" />添加槽位
          </Button>
          <span className="text-xs text-muted-foreground">模板 SHA：{file.source_sha256.slice(0, 12)}…</span>
        </div>
        {(error || mutation.error) && <Alert variant="destructive"><AlertDescription>{error || mutation.error}</AlertDescription></Alert>}
        <DialogFooter className="gap-2 sm:gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isMutating}>取消</Button>
          <Button type="button" onClick={() => void compile()} disabled={mutation.isMutating}>{mutation.isMutating && <Loader2 className="animate-spin" data-icon="inline-start" />}确认并编译</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TemplateFileRow({
  versionId,
  file,
  canEdit,
  onPreview,
}: {
  versionId: string;
  file: AttachmentTemplateFile;
  canEdit: boolean;
  onPreview: (file: AttachmentTemplateFile) => void;
}) {
  const [metadataOpen, setMetadataOpen] = useState(false);
  const [contractOpen, setContractOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const inspectMutation = useInspectAttachmentTemplateFile(versionId, file.id);
  const deleteMutation = useDeleteAttachmentTemplateFile(versionId, file.id);
  const busy = inspectMutation.isMutating || deleteMutation.isMutating;

  async function inspect() {
    try {
      await inspectMutation.inspectFile();
      toast.success("模板分析已提交");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "模板分析失败");
    }
  }

  async function remove() {
    try {
      await deleteMutation.deleteFile(file.revision);
      toast.success("模板文件已删除");
      setDeleteOpen(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除模板文件失败");
    }
  }

  return (
    <>
      <TableRow>
        <TableCell>
          <div className="max-w-72">
            <div className="font-medium">{file.display_name}</div>
            <div className="truncate text-xs text-muted-foreground" title={file.source_file_name}>{file.source_file_name}</div>
          </div>
        </TableCell>
        <TableCell><code className="text-xs">{file.document_code}</code></TableCell>
        <TableCell><Badge variant="outline">{file.extension.replace(/^\./, "").toLocaleUpperCase()}</Badge></TableCell>
        <TableCell>{formatBytes(file.size_bytes)}</TableCell>
        <TableCell>
          <div className="flex flex-col gap-1">
            <Badge variant={file.status === "ready" ? "secondary" : file.status === "invalid" ? "destructive" : "outline"}>{FILE_STATUS_LABELS[file.status] ?? file.status}</Badge>
            <span className="text-[11px] text-muted-foreground">{file.binding_manifest?.slots?.length ?? 0} 个槽位</span>
          </div>
        </TableCell>
        <TableCell className="hidden 2xl:table-cell"><code className="text-xs" title={file.compiled_sha256 || file.source_sha256}>{(file.compiled_sha256 || file.source_sha256).slice(0, 12)}…</code></TableCell>
        <TableCell>
          <div className="flex justify-end gap-1">
            {file.preview_available && <Button type="button" size="icon-sm" variant="ghost" title="预览" onClick={() => onPreview(file)}><Eye /><span className="sr-only">预览 {file.display_name}</span></Button>}
            {canEdit && <Button type="button" size="icon-sm" variant="ghost" title="编辑文件信息" onClick={() => setMetadataOpen(true)}><Pencil /><span className="sr-only">编辑 {file.display_name}</span></Button>}
            {canEdit && <Button type="button" size="icon-sm" variant="ghost" title="分析模板" onClick={() => void inspect()} disabled={busy}><FileSearch /><span className="sr-only">分析 {file.display_name}</span></Button>}
            {canEdit && <Button type="button" size="icon-sm" variant="ghost" title="确认槽位合同" onClick={() => setContractOpen(true)}><WandSparkles /><span className="sr-only">编译 {file.display_name}</span></Button>}
            {canEdit && <Button type="button" size="icon-sm" variant="ghost" title="删除模板文件" onClick={() => setDeleteOpen(true)} disabled={busy}><Trash2 /><span className="sr-only">删除 {file.display_name}</span></Button>}
          </div>
        </TableCell>
      </TableRow>

      <FileMetadataDialog versionId={versionId} file={file} open={metadataOpen} onOpenChange={setMetadataOpen} />
      <SlotContractDialog versionId={versionId} file={file} open={contractOpen} onOpenChange={setContractOpen} />
      <Dialog open={deleteOpen} onOpenChange={(open) => !busy && setDeleteOpen(open)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>删除模板文件</DialogTitle><DialogDescription>确定删除“{file.display_name}”吗？草稿以外的文件不能物理删除。</DialogDescription></DialogHeader>
          <DialogFooter className="gap-2 sm:gap-2"><Button type="button" variant="outline" onClick={() => setDeleteOpen(false)} disabled={busy}>取消</Button><Button type="button" variant="destructive" onClick={() => void remove()} disabled={busy}>{deleteMutation.isMutating && <Loader2 className="animate-spin" data-icon="inline-start" />}删除</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export function AttachmentTemplateFiles({ versionId }: { versionId: string }) {
  const router = useRouter();
  const query = useAttachmentTemplateVersion(versionId);
  const businessTypesQuery = useAttachmentTemplateBusinessTypes();
  const uploadMutation = useUploadAttachmentTemplateFile(versionId);
  const validateMutation = useValidateAttachmentTemplateVersion(versionId);
  const activationMutation = useSetAttachmentTemplateVersionActivation(versionId);
  const cloneMutation = useCloneAttachmentTemplateVersion(versionId);
  const [editOpen, setEditOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [documentCode, setDocumentCode] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [preview, setPreview] = useState<{ url: string; name: string } | null>(null);
  const [previewBusyId, setPreviewBusyId] = useState("");
  const [activationOpen, setActivationOpen] = useState(false);
  const [confirmedPreviewIds, setConfirmedPreviewIds] = useState<Set<string>>(new Set());
  const inputRef = useRef<HTMLInputElement | null>(null);
  const version = query.version;
  const canEdit = version?.status === "draft";
  const businessType = businessTypesQuery.businessTypes.find((item) => item.code === version?.business_type);
  const supportedFormats = businessType?.supported_formats ?? [];
  const acceptedTemplateFormats = supportedFormats.length
    ? supportedFormats.join(",")
    : ACCEPTED_TEMPLATE_FORMATS;
  const selectedFormat = selectedFile ? fileNameTemplateFormat(selectedFile.name) : null;
  const selectedFormatAllowed = Boolean(
    selectedFormat && supportedFormats.includes(selectedFormat)
  );
  const canValidate = Boolean(
    version && ["draft", "retired"].includes(version.status) && version.file_count > 0
  );
  const retiredValidationIsCurrent = Boolean(
    version?.status === "retired" &&
    version.validation_report?.passed === true &&
    version.validation_report.content_sha256 &&
    version.content_sha256 &&
    version.validation_report.content_sha256 === version.content_sha256
  );
  const canActivate = version?.status === "ready" || retiredValidationIsCurrent;
  const activationFiles = [...(version?.files ?? [])].sort(
    (left, right) => left.sort_order - right.sort_order
  );
  const previewsReadyForConfirmation = Boolean(
    activationFiles.length > 0 &&
      activationFiles.every((file) => file.preview_available && file.preview_sha256)
  );
  const allPreviewsConfirmed = Boolean(
    previewsReadyForConfirmation &&
      activationFiles.every((file) => confirmedPreviewIds.has(file.id))
  );
  const busy = validateMutation.isMutating || activationMutation.isMutating || cloneMutation.isMutating;

  useEffect(() => () => {
    if (preview?.url) URL.revokeObjectURL(preview.url);
  }, [preview]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !selectedFile ||
      !isAttachmentTemplateDocumentCode(documentCode) ||
      !displayName.trim()
    ) return;
    const extension = fileNameTemplateFormat(selectedFile.name);
    if (!businessType || !extension || !supportedFormats.includes(extension)) {
      toast.error(
        businessType
          ? `当前业务类型仅支持 ${supportedFormats.join("、").toLocaleUpperCase()} 模板`
          : "业务类型格式目录尚未加载，请重试"
      );
      return;
    }
    try {
      await uploadMutation.uploadFile({
        file: selectedFile,
        document_code: documentCode.trim(),
        display_name: displayName.trim(),
        sort_order: version?.file_count ?? 0,
      });
      toast.success("模板文件已上传，系统将执行安全扫描和结构分析");
      setSelectedFile(null);
      setDocumentCode("");
      setDisplayName("");
      if (inputRef.current) inputRef.current.value = "";
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "模板文件上传失败");
    }
  }

  async function validate() {
    if (!version) return;
    try {
      await validateMutation.validateVersion(version.revision);
      toast.success("模板版本校验已执行");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "模板版本校验失败");
    }
  }

  async function setActive(active: boolean) {
    if (!version) return;
    const previewConfirmations = active
      ? activationFiles.map((file) => ({
          file_id: file.id,
          preview_sha256: file.preview_sha256 ?? "",
        }))
      : undefined;
    if (active && !allPreviewsConfirmed) return;
    try {
      await activationMutation.setActivation({
        active,
        revision: version.revision,
        ...(previewConfirmations ? { preview_confirmations: previewConfirmations } : {}),
      });
      toast.success(active ? "模板版本已激活" : "模板版本已停用");
      if (active) {
        setActivationOpen(false);
        setConfirmedPreviewIds(new Set());
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "更新激活状态失败");
    }
  }

  async function clone() {
    try {
      const created = await cloneMutation.cloneVersion({});
      toast.success(`${created.version_label} 草稿已创建`);
      router.push(`/admin/templates/${encodeURIComponent(created.id)}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "复制模板版本失败");
    }
  }

  async function openPreview(file: AttachmentTemplateFile) {
    try {
      setPreviewBusyId(file.id);
      const blob = await getAttachmentTemplateFilePreview(file.id);
      setPreview((current) => {
        if (current?.url) URL.revokeObjectURL(current.url);
        return { url: URL.createObjectURL(blob), name: `${file.display_name}预览.pdf` };
      });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载模板预览失败");
    } finally {
      setPreviewBusyId("");
    }
  }

  if (query.isLoading && !version) {
    return <div className="flex flex-col gap-4"><Skeleton className="h-8 w-64" /><Skeleton className="h-48 w-full" /></div>;
  }

  if (!version) {
    return (
      <Alert variant="destructive"><CircleAlert aria-hidden="true" /><div><AlertTitle>模板版本无法加载</AlertTitle><AlertDescription>{query.error ?? "该版本不存在或当前账号无权访问。"}</AlertDescription></div></Alert>
    );
  }

  const validationReport = version.validation_report;
  const legacyIssues = validationReport?.issues ?? [];
  const validationBlockers = validationReport?.blockers ?? legacyIssues.filter(
    (issue) => issue.severity !== "warning" && issue.severity !== "info"
  );
  const validationWarnings = validationReport?.warnings ?? legacyIssues.filter(
    (issue) => issue.severity === "warning"
  );
  const validatedAt = validationReport?.validated_at ?? validationReport?.checked_at;
  const hasValidationReport =
    typeof validationReport?.passed === "boolean" ||
    validationBlockers.length > 0 ||
    validationWarnings.length > 0;

  return (
    <section className="flex flex-col gap-6" aria-labelledby="attachment-template-detail-title">
      <div className="flex flex-col gap-4">
        <Link href="/admin/templates" className="inline-flex w-fit items-center gap-2 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />返回附件模板</Link>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 id="attachment-template-detail-title" className="text-xl font-semibold">{version.name}</h2>
              <Badge>{version.version_label}</Badge>
              <Badge variant="outline">{VERSION_STATUS_LABELS[version.status] ?? version.status}</Badge>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">{businessType?.label ?? version.business_type} · {version.ready_file_count}/{version.file_count} 个文件就绪 · revision {version.revision}</p>
            {version.description && <p className="mt-2 max-w-3xl text-sm">{version.description}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            {canEdit && <Button type="button" variant="outline" onClick={() => setEditOpen(true)}><Pencil data-icon="inline-start" />编辑信息</Button>}
            {version.status !== "draft" && <Button type="button" variant="outline" onClick={() => void clone()} disabled={busy}><Copy data-icon="inline-start" />复制新版本</Button>}
            {canValidate && <Button type="button" variant="outline" onClick={() => void validate()} disabled={busy}><ShieldCheck data-icon="inline-start" />{version.status === "retired" ? "重新校验" : "执行校验"}</Button>}
            {canActivate && <Button type="button" onClick={() => setActivationOpen(true)} disabled={busy || !previewsReadyForConfirmation} title={!previewsReadyForConfirmation ? "全部文件生成预览后才能激活" : undefined}><Zap data-icon="inline-start" />{version.status === "retired" ? "重新激活" : "激活版本"}</Button>}
            {version.status === "active" && <Button type="button" variant="outline" onClick={() => void setActive(false)} disabled={busy}>停用版本</Button>}
          </div>
        </div>
      </div>

      {query.error && <Alert variant="destructive"><RefreshCw aria-hidden="true" /><div><AlertTitle>版本刷新失败</AlertTitle><AlertDescription>{query.error}</AlertDescription></div></Alert>}

      {hasValidationReport && validationReport && (
        <Alert variant={validationReport.passed ? "default" : "destructive"}>
          {validationReport.passed ? <CheckCircle2 aria-hidden="true" /> : <CircleAlert aria-hidden="true" />}
          <div>
            <AlertTitle>{validationReport.passed ? "激活门禁已通过" : "激活门禁未通过"}</AlertTitle>
            <AlertDescription>
              <p>
                {validationReport.passed
                  ? "全部文件、槽位与预览检查已完成。"
                  : validationBlockers.length
                    ? validationBlockers.map((issue) => issue.message).join("；")
                    : "校验未通过，但服务端没有返回具体阻断原因，请重新执行校验或查看服务日志。"}
              </p>
              {validationWarnings.length > 0 && (
                <p className="mt-1">警告：{validationWarnings.map((issue) => issue.message).join("；")}</p>
              )}
              {validatedAt && (
                <p className="mt-1 text-xs opacity-80">校验时间：{formatDate(validatedAt)}</p>
              )}
            </AlertDescription>
          </div>
        </Alert>
      )}

      {canEdit && businessTypesQuery.error && (
        <Alert variant="destructive">
          <CircleAlert aria-hidden="true" />
          <div className="flex flex-1 items-center justify-between gap-3">
            <div>
              <AlertTitle>业务类型格式目录加载失败</AlertTitle>
              <AlertDescription>{businessTypesQuery.error}</AlertDescription>
            </div>
            <Button type="button" size="sm" variant="outline" onClick={() => void businessTypesQuery.refresh()}>
              <RefreshCw data-icon="inline-start" />重试
            </Button>
          </div>
        </Alert>
      )}

      {canEdit && (
        <Card>
          <CardHeader><CardTitle className="text-base">上传模板文件</CardTitle></CardHeader>
          <CardContent>
            <form onSubmit={upload} className="grid gap-4 lg:grid-cols-[minmax(16rem,1.2fr)_minmax(12rem,0.8fr)_minmax(12rem,0.8fr)_auto] lg:items-end">
              <Field data-invalid={(selectedFile && !selectedFormatAllowed) || undefined}>
                <FieldLabel htmlFor="attachment-template-file">模板文件</FieldLabel>
                <Input
                  ref={inputRef}
                  id="attachment-template-file"
                  type="file"
                  accept={acceptedTemplateFormats}
                  disabled={uploadMutation.isMutating || !businessType}
                  onChange={(event) => {
                    const file = event.target.files?.[0] ?? null;
                    setSelectedFile(file);
                    const inferred = file ? inferDocumentMetadata(file.name) : { code: "", name: "" };
                    setDocumentCode(inferred.code);
                    setDisplayName(inferred.name);
                  }}
                />
                <FieldDescription>
                  {businessType
                    ? `${businessType.label}支持 ${supportedFormats.join("、").toLocaleUpperCase()}；文件名只用于预填。`
                    : "正在加载该业务类型支持的模板格式。"}
                </FieldDescription>
                {selectedFile && !selectedFormatAllowed && (
                  <FieldError>所选文件格式不在当前业务类型的允许列表中</FieldError>
                )}
              </Field>
              <Field data-invalid={(documentCode.length > 0 && !isAttachmentTemplateDocumentCode(documentCode)) || undefined}>
                <FieldLabel htmlFor="attachment-document-code">附件业务编码</FieldLabel>
                <Input id="attachment-document-code" value={documentCode} onChange={(event) => setDocumentCode(event.target.value)} disabled={uploadMutation.isMutating} placeholder="audit_report" />
                {documentCode.length > 0 && !isAttachmentTemplateDocumentCode(documentCode) && (
                  <FieldError>使用小写字母开头，且仅包含小写字母、数字和下划线（至少 2 个字符）</FieldError>
                )}
              </Field>
              <Field>
                <FieldLabel htmlFor="attachment-display-name">附件显示名称</FieldLabel>
                <Input id="attachment-display-name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} disabled={uploadMutation.isMutating} placeholder="审计报告" />
              </Field>
              <Button type="submit" disabled={uploadMutation.isMutating || !selectedFile || !selectedFormatAllowed || !isAttachmentTemplateDocumentCode(documentCode) || !displayName.trim()}>{uploadMutation.isMutating ? <Loader2 className="animate-spin" data-icon="inline-start" /> : <FileUp data-icon="inline-start" />}上传</Button>
            </form>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><div className="flex items-center justify-between gap-3"><CardTitle className="text-base">版本文件</CardTitle><Badge variant="secondary">{version.file_count} 个</Badge></div></CardHeader>
        <CardContent className="p-0">
          {!version.files.length ? (
            <div className="p-8 text-center text-sm text-muted-foreground">该版本尚未上传模板文件。</div>
          ) : (
            <Table>
              <TableHeader><TableRow><TableHead>附件</TableHead><TableHead>业务编码</TableHead><TableHead>格式</TableHead><TableHead>大小</TableHead><TableHead>状态</TableHead><TableHead className="hidden 2xl:table-cell">模板 SHA</TableHead><TableHead className="text-right">操作</TableHead></TableRow></TableHeader>
              <TableBody>{[...version.files].sort((a, b) => a.sort_order - b.sort_order).map((file) => <TemplateFileRow key={file.id} versionId={versionId} file={file} canEdit={canEdit} onPreview={(item) => { if (previewBusyId !== item.id) void openPreview(item); }} />)}</TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <AttachmentTemplateVersionDialog open={editOpen} onOpenChange={setEditOpen} businessTypes={businessTypesQuery.businessTypes} version={version} />

      <Dialog
        open={activationOpen}
        onOpenChange={(open) => {
          if (busy) return;
          setActivationOpen(open);
          if (!open) setConfirmedPreviewIds(new Set());
        }}
      >
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{version.status === "retired" ? "重新激活模板版本" : "激活模板版本"}</DialogTitle>
            <DialogDescription>
              确认当前冻结预览的版式、字体、分页和内容槽位符合交付要求。
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[52svh] space-y-2 overflow-y-auto">
            {activationFiles.map((file) => {
              const checkboxId = `confirm-preview-${file.id}`;
              return (
                <div key={file.id} className="flex items-center gap-3 border-b py-3 last:border-b-0">
                  <Checkbox
                    id={checkboxId}
                    checked={confirmedPreviewIds.has(file.id)}
                    onCheckedChange={(checked) => {
                      setConfirmedPreviewIds((current) => {
                        const next = new Set(current);
                        if (checked === true) next.add(file.id);
                        else next.delete(file.id);
                        return next;
                      });
                    }}
                    disabled={busy}
                  />
                  <label htmlFor={checkboxId} className="min-w-0 flex-1 text-sm">
                    <span className="block font-medium">{file.display_name}</span>
                    <code className="block truncate text-xs text-muted-foreground" title={file.preview_sha256}>
                      预览 SHA {file.preview_sha256?.slice(0, 12)}…
                    </code>
                  </label>
                  <Button type="button" size="icon-sm" variant="ghost" title={`预览 ${file.display_name}`} onClick={() => void openPreview(file)} disabled={busy || previewBusyId === file.id}>
                    {previewBusyId === file.id ? <Loader2 className="animate-spin" /> : <Eye />}
                    <span className="sr-only">预览 {file.display_name}</span>
                  </Button>
                </div>
              );
            })}
          </div>
          <DialogFooter className="gap-2 sm:gap-2">
            <Button type="button" variant="outline" onClick={() => setActivationOpen(false)} disabled={busy}>取消</Button>
            <Button type="button" onClick={() => void setActive(true)} disabled={busy || !allPreviewsConfirmed}>
              {activationMutation.isMutating && <Loader2 className="animate-spin" data-icon="inline-start" />}
              确认并激活
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(preview)} onOpenChange={(open) => { if (!open) setPreview(null); }}>
        <DialogContent className="flex h-[92svh] w-[96vw] max-w-[96vw] flex-col gap-0 overflow-hidden p-0 sm:max-w-[92vw]">
          <DialogTitle className="shrink-0 border-b px-4 py-3 pr-12 text-sm">{preview?.name ?? "模板预览"}</DialogTitle>
          <div className="min-h-0 flex-1 overflow-hidden">
            {preview && <PdfViewer url={preview.url} fit="page" />}
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}

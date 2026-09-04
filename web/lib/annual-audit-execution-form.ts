import type {
  AnnualAuditEvidenceReference,
  AnnualAuditProgramItem,
} from "@/lib/backend/annual-audit";

export type AnnualAuditStructuredValue = Record<string, unknown> | unknown[];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function own(record: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(record, key);
}

function textValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "";
}

function positiveIntegerText(value: unknown): string {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? String(number) : "";
}

function setTrimmedText(record: Record<string, unknown>, key: string, value: string): void {
  const trimmed = value.trim();
  if (trimmed) record[key] = trimmed;
  else delete record[key];
}

function setPositiveInteger(record: Record<string, unknown>, key: string, value: string): void {
  const number = Number(value);
  if (Number.isInteger(number) && number > 0) record[key] = number;
  else delete record[key];
}

function nextRowKey(prefix: string): string {
  return `${prefix}-new-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export type EvidenceLocatorType = "worksheet" | "page" | "row" | "chunk";

export interface EvidenceAnchorDraft {
  rowKey: string;
  isNew: boolean;
  original: AnnualAuditEvidenceReference;
  sourceFileId: string;
  locatorType: EvidenceLocatorType;
  sourcePageId: string;
  sourceChunkId: string;
  sheetName: string;
  cellRange: string;
  pageNo: string;
  rowStart: string;
}

function evidenceLocator(reference: AnnualAuditEvidenceReference): Record<string, unknown> {
  return isRecord(reference.source_locator) ? reference.source_locator : {};
}

function inferLocatorType(
  reference: AnnualAuditEvidenceReference,
  locator: Record<string, unknown>
): EvidenceLocatorType {
  if (textValue(locator.sheet_name) || textValue(locator.cell_range)) return "worksheet";
  if (textValue(reference.source_chunk_id ?? locator.source_chunk_id)) return "chunk";
  if (
    positiveIntegerText(reference.source_page_id ?? locator.source_page_id) ||
    positiveIntegerText(locator.page_no)
  ) {
    return "page";
  }
  if (positiveIntegerText(locator.row_start ?? locator.row_number)) return "row";
  return "worksheet";
}

export function evidenceRefsToDrafts(
  references: AnnualAuditEvidenceReference[]
): EvidenceAnchorDraft[] {
  return references.map((reference, index) => {
    const locator = evidenceLocator(reference);
    return {
      rowKey: `evidence-${index}`,
      isNew: false,
      original: reference,
      sourceFileId: positiveIntegerText(reference.source_file_id ?? locator.source_file_id),
      locatorType: inferLocatorType(reference, locator),
      sourcePageId: positiveIntegerText(reference.source_page_id ?? locator.source_page_id),
      sourceChunkId: textValue(reference.source_chunk_id ?? locator.source_chunk_id),
      sheetName: textValue(locator.sheet_name),
      cellRange: textValue(locator.cell_range),
      pageNo: positiveIntegerText(locator.page_no),
      rowStart: positiveIntegerText(locator.row_start ?? locator.row_number),
    };
  });
}

export function createEvidenceAnchorDraft(): EvidenceAnchorDraft {
  return {
    rowKey: nextRowKey("evidence"),
    isNew: true,
    original: {},
    sourceFileId: "",
    locatorType: "worksheet",
    sourcePageId: "",
    sourceChunkId: "",
    sheetName: "",
    cellRange: "",
    pageNo: "",
    rowStart: "",
  };
}

export function evidenceAnchorIsBlank(row: EvidenceAnchorDraft): boolean {
  return ![
    row.sourceFileId,
    row.sourcePageId,
    row.sourceChunkId,
    row.sheetName,
    row.cellRange,
    row.pageNo,
    row.rowStart,
  ].some((value) => value.trim());
}

export function evidenceAnchorValidationError(row: EvidenceAnchorDraft): string | null {
  if (row.isNew && evidenceAnchorIsBlank(row)) return null;
  if (!positiveIntegerText(row.sourceFileId)) return "请选择有效的资料文件编号";
  if (row.locatorType === "worksheet" && !row.sheetName.trim() && !row.cellRange.trim()) {
    return "请填写工作表名称或单元格范围";
  }
  if (row.locatorType === "page" && !positiveIntegerText(row.sourcePageId) && !positiveIntegerText(row.pageNo)) {
    return "请填写页记录编号或文件页码";
  }
  if (row.locatorType === "row" && !positiveIntegerText(row.rowStart)) {
    return "请填写数据行号";
  }
  if (row.locatorType === "chunk" && !row.sourceChunkId.trim()) {
    return "请填写解析段落编号";
  }
  return null;
}

export function evidenceDraftsToRefs(
  rows: EvidenceAnchorDraft[]
): AnnualAuditEvidenceReference[] {
  return rows
    .filter((row) => !row.isNew || !evidenceAnchorIsBlank(row))
    .map((row) => {
      const reference: AnnualAuditEvidenceReference = { ...row.original };
      const locator: Record<string, unknown> = { ...evidenceLocator(row.original) };

      delete locator.source_file_id;
      delete locator.source_page_id;
      delete locator.source_chunk_id;
      delete locator.sheet_name;
      delete locator.cell_range;
      delete locator.page_no;
      delete locator.row_number;
      delete locator.row_start;
      delete reference.source_file_id;
      delete reference.source_page_id;
      delete reference.source_chunk_id;

      setPositiveInteger(reference, "source_file_id", row.sourceFileId);
      setPositiveInteger(reference, "source_page_id", row.sourcePageId);
      setTrimmedText(reference, "source_chunk_id", row.sourceChunkId);
      setTrimmedText(locator, "sheet_name", row.sheetName);
      setTrimmedText(locator, "cell_range", row.cellRange);
      setPositiveInteger(locator, "page_no", row.pageNo);
      setPositiveInteger(locator, "row_start", row.rowStart);

      if (Object.keys(locator).length) reference.source_locator = locator;
      else delete reference.source_locator;
      return reference;
    });
}

const SAMPLING_KEYS = [
  "population_description",
  "sampling_method",
  "sample_size",
  "selection_threshold",
  "rationale",
] as const;

export interface SamplingPlanDraft {
  original: AnnualAuditStructuredValue;
  targetIndex: number | null;
  populationDescription: string;
  samplingMethod: string;
  sampleSize: string;
  selectionThreshold: string;
  rationale: string;
}

function containsSamplingFields(record: Record<string, unknown>): boolean {
  return SAMPLING_KEYS.some((key) => own(record, key));
}

export function samplingPlanToDraft(value: AnnualAuditStructuredValue): SamplingPlanDraft {
  let target: Record<string, unknown> = {};
  let targetIndex: number | null = null;
  if (Array.isArray(value)) {
    targetIndex = value.findIndex((item) => isRecord(item) && containsSamplingFields(item));
    if (targetIndex >= 0 && isRecord(value[targetIndex])) target = value[targetIndex];
    else targetIndex = null;
  } else {
    target = value;
  }
  return {
    original: value,
    targetIndex,
    populationDescription: textValue(target.population_description),
    samplingMethod: textValue(target.sampling_method),
    sampleSize: positiveIntegerText(target.sample_size),
    selectionThreshold: textValue(target.selection_threshold),
    rationale: textValue(target.rationale),
  };
}

export function samplingPlanHasValues(draft: SamplingPlanDraft): boolean {
  return [
    draft.populationDescription,
    draft.samplingMethod,
    draft.sampleSize,
    draft.selectionThreshold,
    draft.rationale,
  ].some((value) => value.trim());
}

export function samplingPlanValidationError(draft: SamplingPlanDraft): string | null {
  if (draft.sampleSize.trim() && !positiveIntegerText(draft.sampleSize)) {
    return "样本量必须是大于 0 的整数";
  }
  return null;
}

function mergeSamplingFields(
  original: Record<string, unknown>,
  draft: SamplingPlanDraft
): Record<string, unknown> {
  const merged = { ...original };
  for (const key of SAMPLING_KEYS) delete merged[key];
  setTrimmedText(merged, "population_description", draft.populationDescription);
  setTrimmedText(merged, "sampling_method", draft.samplingMethod);
  setPositiveInteger(merged, "sample_size", draft.sampleSize);
  setTrimmedText(merged, "selection_threshold", draft.selectionThreshold);
  setTrimmedText(merged, "rationale", draft.rationale);
  return merged;
}

export function samplingDraftToPlan(draft: SamplingPlanDraft): AnnualAuditStructuredValue {
  if (!Array.isArray(draft.original)) return mergeSamplingFields(draft.original, draft);
  const result = [...draft.original];
  if (draft.targetIndex !== null && isRecord(result[draft.targetIndex])) {
    result[draft.targetIndex] = mergeSamplingFields(result[draft.targetIndex], draft);
  } else if (samplingPlanHasValues(draft)) {
    result.push(mergeSamplingFields({}, draft));
  }
  return result;
}

const ALTERNATIVE_DESCRIPTION_KEYS = [
  "procedure_description",
  "procedure",
  "description",
  "name",
] as const;
const ALTERNATIVE_RESULT_KEYS = ["execution_result", "result", "outcome", "conclusion"] as const;

export interface AlternativeProcedureRowDraft {
  rowKey: string;
  isNew: boolean;
  original: unknown;
  description: string;
  executionResult: string;
}

type AlternativeContainerMode = "array" | "object_list" | "object_row" | "object_unknown";

export interface AlternativeProceduresDraft {
  original: AnnualAuditStructuredValue;
  mode: AlternativeContainerMode;
  listKey: string | null;
  rows: AlternativeProcedureRowDraft[];
}

function firstText(record: Record<string, unknown>, keys: readonly string[]): string {
  for (const key of keys) {
    const value = textValue(record[key]);
    if (value) return value;
  }
  return "";
}

function alternativeRow(original: unknown, index: number): AlternativeProcedureRowDraft {
  const record = isRecord(original) ? original : {};
  return {
    rowKey: `alternative-${index}`,
    isNew: false,
    original,
    description: typeof original === "string" ? original : firstText(record, ALTERNATIVE_DESCRIPTION_KEYS),
    executionResult: firstText(record, ALTERNATIVE_RESULT_KEYS),
  };
}

function hasAlternativeRowFields(record: Record<string, unknown>): boolean {
  return [...ALTERNATIVE_DESCRIPTION_KEYS, ...ALTERNATIVE_RESULT_KEYS].some((key) => own(record, key));
}

export function alternativeProceduresToDraft(
  value: AnnualAuditStructuredValue
): AlternativeProceduresDraft {
  if (Array.isArray(value)) {
    return {
      original: value,
      mode: "array",
      listKey: null,
      rows: value.map(alternativeRow),
    };
  }
  for (const listKey of ["procedures", "items"]) {
    if (Array.isArray(value[listKey])) {
      return {
        original: value,
        mode: "object_list",
        listKey,
        rows: value[listKey].map(alternativeRow),
      };
    }
  }
  if (hasAlternativeRowFields(value)) {
    return {
      original: value,
      mode: "object_row",
      listKey: null,
      rows: [alternativeRow(value, 0)],
    };
  }
  return { original: value, mode: "object_unknown", listKey: null, rows: [] };
}

export function createAlternativeProcedureRow(): AlternativeProcedureRowDraft {
  return {
    rowKey: nextRowKey("alternative"),
    isNew: true,
    original: undefined,
    description: "",
    executionResult: "",
  };
}

function mergeAlternativeRow(row: AlternativeProcedureRowDraft): unknown {
  const description = row.description.trim();
  const executionResult = row.executionResult.trim();
  if (typeof row.original === "string" && !executionResult) return description;
  if (!isRecord(row.original)) {
    return {
      ...(description ? { procedure_description: description } : {}),
      ...(executionResult ? { execution_result: executionResult } : {}),
    };
  }
  const merged = { ...row.original };
  const descriptionKey =
    ALTERNATIVE_DESCRIPTION_KEYS.find((key) => own(merged, key)) ?? "procedure_description";
  const resultKey = ALTERNATIVE_RESULT_KEYS.find((key) => own(merged, key)) ?? "execution_result";
  for (const key of ALTERNATIVE_DESCRIPTION_KEYS) delete merged[key];
  for (const key of ALTERNATIVE_RESULT_KEYS) delete merged[key];
  setTrimmedText(merged, descriptionKey, description);
  setTrimmedText(merged, resultKey, executionResult);
  return merged;
}

function retainedAlternativeRows(rows: AlternativeProcedureRowDraft[]): unknown[] {
  return rows
    .filter((row) => !row.isNew || row.description.trim() || row.executionResult.trim())
    .map(mergeAlternativeRow);
}

export function alternativeDraftToProcedures(
  draft: AlternativeProceduresDraft
): AnnualAuditStructuredValue {
  const rows = retainedAlternativeRows(draft.rows);
  if (draft.mode === "array") return rows;
  if (draft.mode === "object_list" && draft.listKey) {
    return { ...(draft.original as Record<string, unknown>), [draft.listKey]: rows };
  }
  if (draft.mode === "object_row") {
    if (rows.length && isRecord(rows[0])) return rows[0];
    const original = { ...(draft.original as Record<string, unknown>) };
    for (const key of ALTERNATIVE_DESCRIPTION_KEYS) delete original[key];
    for (const key of ALTERNATIVE_RESULT_KEYS) delete original[key];
    return original;
  }
  if (!rows.length) return draft.original;
  return { ...(draft.original as Record<string, unknown>), procedures: rows };
}

export type ReviewScopeType = "engagement" | "phase" | "cycle" | "procedure";

const REVIEW_SCOPE_TYPES: ReviewScopeType[] = ["engagement", "phase", "cycle", "procedure"];
const REVIEW_SCOPE_TYPE_KEYS = ["scope_type", "scope", "type"] as const;
const REVIEW_SCOPE_OBJECT_KEYS = ["scope_objects", "objects", "object_ids"] as const;

export interface ReviewScopeDraft {
  original: AnnualAuditStructuredValue;
  targetIndex: number | null;
  scopeType: ReviewScopeType;
  objectIds: string[];
}

function normalizeScopeType(value: unknown): ReviewScopeType {
  const text = textValue(value) as ReviewScopeType;
  return REVIEW_SCOPE_TYPES.includes(text) ? text : "engagement";
}

function scopeRecord(value: AnnualAuditStructuredValue): {
  record: Record<string, unknown>;
  targetIndex: number | null;
} {
  if (!Array.isArray(value)) return { record: value, targetIndex: null };
  for (let index = value.length - 1; index >= 0; index -= 1) {
    const item = value[index];
    if (isRecord(item) && REVIEW_SCOPE_TYPE_KEYS.some((key) => own(item, key))) {
      return { record: item, targetIndex: index };
    }
  }
  return { record: {}, targetIndex: null };
}

export function reviewScopeToDraft(value: AnnualAuditStructuredValue): ReviewScopeDraft {
  const { record, targetIndex } = scopeRecord(value);
  const typeKey = REVIEW_SCOPE_TYPE_KEYS.find((key) => own(record, key));
  const objectKey = REVIEW_SCOPE_OBJECT_KEYS.find((key) => own(record, key));
  const objects = objectKey && Array.isArray(record[objectKey]) ? record[objectKey] : [];
  return {
    original: value,
    targetIndex,
    scopeType: normalizeScopeType(typeKey ? record[typeKey] : undefined),
    objectIds: objects.map(textValue).filter(Boolean),
  };
}

function mergeReviewScope(
  original: Record<string, unknown>,
  draft: ReviewScopeDraft
): Record<string, unknown> {
  const merged = { ...original };
  const typeKey = REVIEW_SCOPE_TYPE_KEYS.find((key) => own(merged, key)) ?? "scope";
  const objectKey = REVIEW_SCOPE_OBJECT_KEYS.find((key) => own(merged, key)) ?? "objects";
  for (const key of REVIEW_SCOPE_TYPE_KEYS) delete merged[key];
  for (const key of REVIEW_SCOPE_OBJECT_KEYS) delete merged[key];
  merged[typeKey] = draft.scopeType;
  if (draft.scopeType !== "engagement") merged[objectKey] = [...draft.objectIds];
  return merged;
}

export function reviewDraftToScope(draft: ReviewScopeDraft): AnnualAuditStructuredValue {
  if (!Array.isArray(draft.original)) return mergeReviewScope(draft.original, draft);
  const result = [...draft.original];
  if (draft.targetIndex !== null && isRecord(result[draft.targetIndex])) {
    result[draft.targetIndex] = mergeReviewScope(result[draft.targetIndex], draft);
  } else {
    result.push(mergeReviewScope({}, draft));
  }
  return result;
}

export interface ReviewScopeOption {
  value: string;
  label: string;
}

function uniqueOptions(options: ReviewScopeOption[]): ReviewScopeOption[] {
  return Array.from(new Map(options.map((option) => [option.value, option])).values());
}

export function reviewScopeOptions(
  type: ReviewScopeType,
  program: AnnualAuditProgramItem[]
): ReviewScopeOption[] {
  if (type === "phase") {
    return uniqueOptions(program.map((item) => ({ value: item.phase, label: item.phase })));
  }
  if (type === "cycle") {
    return uniqueOptions(program.map((item) => ({ value: item.cycle, label: item.cycle })));
  }
  if (type === "procedure") {
    return program.map((item) => ({
      value: item.procedure_code,
      label: `${item.procedure_code} ${item.procedure_name}`,
    }));
  }
  return [];
}

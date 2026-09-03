import { apiFetch, casesUrl } from "@/lib/api/client";
import {
  BackendError,
  deleteJson,
  extractErrorMessage,
  getJson,
  patchJson,
  postForm,
  postJson,
  postWithoutBody,
  putJson,
} from "./http";

export const SUPPORTED_ATTACHMENT_TEMPLATE_FORMATS = [
  ".docx",
  ".xlsx",
  ".md",
  ".pdf",
] as const;

export type AttachmentTemplateFormat =
  (typeof SUPPORTED_ATTACHMENT_TEMPLATE_FORMATS)[number];

export const ATTACHMENT_TEMPLATE_VALUE_TYPES = [
  "scalar",
  "narrative_blocks",
  "table_rows",
] as const;
export const ATTACHMENT_TEMPLATE_STYLE_POLICIES = [
  "inherit_template",
  "clone_prototype_row",
  "explicit",
] as const;
export const ATTACHMENT_TEMPLATE_MISSING_POLICIES = [
  "block",
  "omit_slot",
  "omit_sentence",
  "empty",
] as const;
export const ATTACHMENT_TEMPLATE_OVERFLOW_POLICIES = [
  "error",
  "continue_paragraphs",
  "extend_rows",
  "truncate",
  "shrink_font",
] as const;
export const ATTACHMENT_TEMPLATE_COMPOSITION_MODES = [
  "deterministic",
  "semantic",
] as const;

export type AttachmentTemplateValueType =
  (typeof ATTACHMENT_TEMPLATE_VALUE_TYPES)[number];
export type AttachmentTemplateStylePolicy =
  (typeof ATTACHMENT_TEMPLATE_STYLE_POLICIES)[number];
export type AttachmentTemplateMissingPolicy =
  (typeof ATTACHMENT_TEMPLATE_MISSING_POLICIES)[number];
export type AttachmentTemplateOverflowPolicy =
  (typeof ATTACHMENT_TEMPLATE_OVERFLOW_POLICIES)[number];
export type AttachmentTemplateCompositionMode =
  (typeof ATTACHMENT_TEMPLATE_COMPOSITION_MODES)[number];

const ATTACHMENT_TEMPLATE_DOCUMENT_CODE_PATTERN = /^[a-z][a-z0-9_]{1,127}$/;
const ATTACHMENT_TEMPLATE_SLOT_ID_PATTERN = /^[a-z][a-z0-9_.-]{1,127}$/;
const ATTACHMENT_TEMPLATE_SOURCE_PATH_PATTERN =
  /^document\.[a-z][a-z0-9_]*(?:\[\])?(?:\.[a-z][a-z0-9_]*(?:\[\])?)*$/;
const ATTACHMENT_TEMPLATE_FACT_KEY_PATTERN =
  /^[a-z][a-z0-9_]*(?:\[\])?(?:\.[a-z][a-z0-9_]*(?:\[\])?)*$/;

export function normalizeAttachmentTemplateFormat(
  value: string
): AttachmentTemplateFormat | null {
  const normalized = `.${value.trim().toLocaleLowerCase().replace(/^\./, "")}`;
  return SUPPORTED_ATTACHMENT_TEMPLATE_FORMATS.includes(
    normalized as AttachmentTemplateFormat
  )
    ? (normalized as AttachmentTemplateFormat)
    : null;
}

export function isAttachmentTemplateDocumentCode(value: string): boolean {
  return ATTACHMENT_TEMPLATE_DOCUMENT_CODE_PATTERN.test(value.trim());
}

export function isAttachmentTemplateSlotId(value: string): boolean {
  return ATTACHMENT_TEMPLATE_SLOT_ID_PATTERN.test(value.trim());
}

export function isAttachmentTemplateSourcePath(value: string): boolean {
  return ATTACHMENT_TEMPLATE_SOURCE_PATH_PATTERN.test(value.trim());
}

export function isAttachmentTemplateFactKey(value: string): boolean {
  return ATTACHMENT_TEMPLATE_FACT_KEY_PATTERN.test(value.trim());
}

export type AttachmentTemplateVersionStatus =
  | "draft"
  | "validating"
  | "ready"
  | "active"
  | "retired"
  | "archived";

export type AttachmentTemplateFileStatus =
  | "uploaded"
  | "scanning"
  | "mapping"
  | "ready"
  | "invalid"
  | "archived";

export interface AttachmentTemplateBusinessType {
  code: string;
  label: string;
  generator_enabled: boolean;
  supported_formats: AttachmentTemplateFormat[];
  required_profile: string[];
  description?: string;
}

export interface AttachmentTemplateSlot {
  slot_id: string;
  target: string;
  value_type: AttachmentTemplateValueType;
  source: string;
  required: boolean;
  style_policy: AttachmentTemplateStylePolicy;
  overflow_policy: AttachmentTemplateOverflowPolicy;
  missing_policy?: AttachmentTemplateMissingPolicy;
  options?: Record<string, unknown>;
}

export function createDefaultAttachmentTemplateSlot(slotId = "slot_1"): AttachmentTemplateSlot {
  return {
    slot_id: slotId,
    target: "",
    value_type: "scalar",
    source: "",
    required: true,
    style_policy: "inherit_template",
    overflow_policy: "error",
    missing_policy: "block",
  };
}

export interface AttachmentTemplateBindingManifest {
  contract_version?: string;
  document_code?: string;
  source_template_sha256?: string;
  slots?: AttachmentTemplateSlot[];
  fixed_regions?: string[];
  forbidden_output_patterns?: string[];
  [key: string]: unknown;
}

export interface AttachmentTemplateValidationIssue {
  code: string;
  message: string;
  severity?: "error" | "warning" | "info" | string;
  file_id?: string | null;
  slot_id?: string | null;
}

export interface AttachmentTemplateValidationReport {
  passed?: boolean;
  validated_at?: string | null;
  checked_at?: string | null;
  blockers?: AttachmentTemplateValidationIssue[];
  warnings?: AttachmentTemplateValidationIssue[];
  issues?: AttachmentTemplateValidationIssue[];
  files?: Array<{
    file_id?: string;
    document_code?: string;
    passed?: boolean;
    blockers?: AttachmentTemplateValidationIssue[];
    warnings?: AttachmentTemplateValidationIssue[];
  }>;
  content_sha256?: string;
  unresolved_placeholder_count?: number;
  preview_confirmed?: boolean;
  [key: string]: unknown;
}

export interface AttachmentTemplateInspectionReport {
  safe?: boolean;
  ok?: boolean;
  mime_matches?: boolean;
  signature_matches?: boolean;
  encrypted?: boolean;
  macros_detected?: boolean;
  external_links?: string[];
  fonts?: string[];
  slot_candidates?: Array<Record<string, unknown>>;
  suggested_mapping?: {
    slots?: Array<Record<string, unknown>>;
    [key: string]: unknown;
  };
  format_details?: Record<string, unknown>;
  issues?: AttachmentTemplateValidationIssue[];
  [key: string]: unknown;
}

export interface AttachmentTemplateFile {
  id: string;
  template_version_id: string;
  document_code: string;
  display_name: string;
  source_file_name: string;
  extension: AttachmentTemplateFormat;
  content_type: string;
  size_bytes: number;
  source_sha256: string;
  compiled_sha256?: string | null;
  renderer_profile?: string | null;
  binding_manifest?: AttachmentTemplateBindingManifest | null;
  inspection_report?: AttachmentTemplateInspectionReport | null;
  preview_available?: boolean;
  status: AttachmentTemplateFileStatus;
  sort_order: number;
  revision: number;
  preview_sha256?: string;
  created_by?: string;
  updated_by?: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AttachmentTemplateVersionSummary {
  id: string;
  family_id: string;
  business_type: string;
  business_type_label?: string;
  scope_type: string;
  scope_key: string;
  version_no: number;
  version_label: string;
  name: string;
  description: string;
  status: AttachmentTemplateVersionStatus;
  contract_version?: string;
  content_sha256?: string | null;
  file_count: number;
  ready_file_count: number;
  revision: number;
  family_revision?: number;
  active: boolean;
  generator_enabled?: boolean;
  validation_report?: AttachmentTemplateValidationReport | null;
  created_by?: string;
  created_at?: string | null;
  updated_by?: string;
  updated_at?: string | null;
  activated_by?: string | null;
  activated_at?: string | null;
  archived_at?: string | null;
}

export interface AttachmentTemplateVersionDetail
  extends AttachmentTemplateVersionSummary {
  files: AttachmentTemplateFile[];
  manifest?: Record<string, unknown> | null;
}

export interface AttachmentTemplateVersionListResponse {
  items: AttachmentTemplateVersionSummary[];
  total: number;
  page: number;
  page_size: number;
}

interface AttachmentTemplateVersionListWireResponse {
  items?: AttachmentTemplateVersionSummary[];
  versions?: AttachmentTemplateVersionSummary[];
  total?: number;
  page?: number;
  page_size?: number;
}

export interface AttachmentTemplateVersionListParams {
  businessType?: string;
  status?: AttachmentTemplateVersionStatus | "";
  page?: number;
  pageSize?: number;
}

export interface CreateAttachmentTemplateVersionRequest {
  name: string;
  business_type: string;
  description?: string;
  scope_type?: string;
  scope_key?: string;
}

export interface UpdateAttachmentTemplateVersionRequest {
  name?: string;
  description?: string;
  manifest?: Record<string, unknown>;
  revision: number;
}

export interface UpdateAttachmentTemplateFileRequest {
  document_code?: string;
  display_name?: string;
  sort_order?: number;
  binding_manifest?: AttachmentTemplateBindingManifest;
  revision: number;
}

export interface CompileAttachmentTemplateFileRequest {
  binding_manifest: AttachmentTemplateBindingManifest;
  revision: number;
}

const TEMPLATE_VERSIONS_PATH = "/api/admin/template-versions";

export function attachmentTemplateBusinessTypesKey(): string {
  return casesUrl("/api/admin/template-business-types");
}

export function attachmentTemplateVersionsKey(
  params: AttachmentTemplateVersionListParams = {}
): string {
  const query = new URLSearchParams();
  if (params.businessType) query.set("business_type", params.businessType);
  if (params.status) query.set("status", params.status);
  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.pageSize ?? 50));
  return casesUrl(`${TEMPLATE_VERSIONS_PATH}?${query}`);
}

export function attachmentTemplateVersionKey(versionId: string): string {
  return casesUrl(`${TEMPLATE_VERSIONS_PATH}/${encodeURIComponent(versionId)}`);
}

export function isAttachmentTemplateVersionsKey(key: unknown): key is string {
  return typeof key === "string" && key.startsWith(casesUrl(`${TEMPLATE_VERSIONS_PATH}?`));
}

export async function listAttachmentTemplateBusinessTypes(): Promise<AttachmentTemplateBusinessType[]> {
  const response = await getJson<
    AttachmentTemplateBusinessType[] | { items?: AttachmentTemplateBusinessType[] }
  >(attachmentTemplateBusinessTypesKey(), "获取模板业务类型失败");
  const items = Array.isArray(response) ? response : response.items ?? [];
  return items.map((item) => ({
    ...item,
    supported_formats: (item.supported_formats ?? [])
      .map((format) => normalizeAttachmentTemplateFormat(format))
      .filter((format): format is AttachmentTemplateFormat => format !== null),
  }));
}

export async function listAttachmentTemplateVersions(
  params: AttachmentTemplateVersionListParams = {}
): Promise<AttachmentTemplateVersionListResponse> {
  const response = await getJson<AttachmentTemplateVersionListWireResponse>(
    attachmentTemplateVersionsKey(params),
    "获取附件模板版本失败"
  );
  const items = response.items ?? response.versions ?? [];
  return {
    items,
    total: response.total ?? items.length,
    page: response.page ?? params.page ?? 1,
    page_size: response.page_size ?? params.pageSize ?? 50,
  };
}

export function createAttachmentTemplateVersion(
  request: CreateAttachmentTemplateVersionRequest
): Promise<AttachmentTemplateVersionDetail> {
  return postJson<AttachmentTemplateVersionDetail>(
    casesUrl(TEMPLATE_VERSIONS_PATH),
    request,
    "创建附件模板版本失败"
  );
}

export function getAttachmentTemplateVersion(
  versionId: string
): Promise<AttachmentTemplateVersionDetail> {
  return getJson<AttachmentTemplateVersionDetail>(
    attachmentTemplateVersionKey(versionId),
    "获取附件模板版本详情失败"
  );
}

export function updateAttachmentTemplateVersion(
  versionId: string,
  request: UpdateAttachmentTemplateVersionRequest
): Promise<AttachmentTemplateVersionDetail> {
  return patchJson<AttachmentTemplateVersionDetail>(
    attachmentTemplateVersionKey(versionId),
    request,
    "更新附件模板版本失败"
  );
}

export function cloneAttachmentTemplateVersion(
  versionId: string,
  request: { name?: string; description?: string } = {}
): Promise<AttachmentTemplateVersionDetail> {
  return postJson<AttachmentTemplateVersionDetail>(
    `${attachmentTemplateVersionKey(versionId)}/clone`,
    request,
    "复制附件模板版本失败"
  );
}

export function deleteAttachmentTemplateVersion(
  versionId: string,
  revision: number
): Promise<void> {
  const query = new URLSearchParams({ revision: String(revision) });
  return deleteJson(
    `${attachmentTemplateVersionKey(versionId)}?${query}`,
    "删除附件模板版本失败"
  );
}

export function uploadAttachmentTemplateFile(
  versionId: string,
  input: {
    file: File;
    document_code: string;
    display_name: string;
    sort_order?: number;
  }
): Promise<AttachmentTemplateFile> {
  const form = new FormData();
  form.append("file", input.file);
  form.append("document_code", input.document_code);
  form.append("display_name", input.display_name);
  if (input.sort_order !== undefined) form.append("sort_order", String(input.sort_order));
  return postForm<AttachmentTemplateFile>(
    `${attachmentTemplateVersionKey(versionId)}/files`,
    form,
    "上传附件模板文件失败"
  );
}

export function updateAttachmentTemplateFile(
  fileId: string,
  request: UpdateAttachmentTemplateFileRequest
): Promise<AttachmentTemplateFile> {
  return patchJson<AttachmentTemplateFile>(
    casesUrl(`/api/admin/template-files/${encodeURIComponent(fileId)}`),
    request,
    "更新附件模板文件失败"
  );
}

export function deleteAttachmentTemplateFile(fileId: string, revision: number): Promise<void> {
  const query = new URLSearchParams({ revision: String(revision) });
  return deleteJson(
    casesUrl(`/api/admin/template-files/${encodeURIComponent(fileId)}?${query}`),
    "删除附件模板文件失败"
  );
}

export function inspectAttachmentTemplateFile(
  fileId: string
): Promise<AttachmentTemplateFile> {
  return postWithoutBody<AttachmentTemplateFile>(
    casesUrl(`/api/admin/template-files/${encodeURIComponent(fileId)}/inspect`),
    "分析附件模板失败"
  );
}

export function compileAttachmentTemplateFile(
  fileId: string,
  request: CompileAttachmentTemplateFileRequest
): Promise<AttachmentTemplateFile> {
  return postJson<AttachmentTemplateFile>(
    casesUrl(`/api/admin/template-files/${encodeURIComponent(fileId)}/compile`),
    request,
    "编译附件模板失败"
  );
}

export async function getAttachmentTemplateFilePreview(
  fileId: string
): Promise<Blob> {
  const response = await apiFetch(
    casesUrl(`/api/admin/template-files/${encodeURIComponent(fileId)}/preview`)
  );
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // The fallback below is safe for non-JSON proxy errors.
    }
    throw new BackendError(
      extractErrorMessage(body, `获取附件模板预览失败 (${response.status})`),
      response.status
    );
  }
  return response.blob();
}

export function validateAttachmentTemplateVersion(
  versionId: string,
  revision: number
): Promise<AttachmentTemplateVersionDetail> {
  return postJson<AttachmentTemplateVersionDetail>(
    `${attachmentTemplateVersionKey(versionId)}/validate`,
    { revision },
    "校验附件模板版本失败"
  );
}

export function setAttachmentTemplateVersionActivation(
  versionId: string,
  request: {
    active: boolean;
    revision: number;
  }
): Promise<AttachmentTemplateVersionDetail> {
  return putJson<AttachmentTemplateVersionDetail>(
    `${attachmentTemplateVersionKey(versionId)}/activation`,
    request,
    request.active ? "激活附件模板版本失败" : "停用附件模板版本失败"
  );
}

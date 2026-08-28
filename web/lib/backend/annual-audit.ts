import { casesUrl } from "@/lib/api/client";
import { deleteJson, getJson, postForm, postJson, postWithoutBody, putJson } from "./http";

export type AnnualAuditProgramStatus =
  | "not_started"
  | "blocked"
  | "in_progress"
  | "evidence_ready"
  | "completed"
  | "not_applicable"
  | "returned";

export type AnnualAuditReviewLevel =
  | "project_manager"
  | "department_manager"
  | "engagement_partner";

export type AnnualAuditReviewDecision = "pending" | "approved" | "returned";

export interface AnnualAuditProfile {
  acceptance_status: string;
  independence_status: string;
  entity_type?: string;
  audit_purpose?: string;
  accounting_framework?: string;
  industry_code?: string;
  regulatory_profile?: string;
  firm_name?: string;
  engagement_partner?: string;
  signing_cpa_primary?: string;
  signing_cpa_secondary?: string;
  signing_cpa_primary_user_id?: string;
  signing_cpa_secondary_user_id?: string;
  data_classification?: string;
  data_residency?: string;
  model_data_policy?: string;
  profile_version?: number;
  updated_at?: string | null;
}

export interface AnnualAuditDocumentCategory {
  code: string;
  name: string;
  uploaded: boolean;
  raw_uploaded?: boolean;
  covered_by_case_workpaper?: boolean;
  coverage_basis?: "uploaded" | "case_workpaper" | "missing" | string;
  file_count: number;
  record_count: number;
  last_uploaded_at?: string | null;
}

export interface AnnualAuditEvidenceLocator {
  source_file_id?: number;
  source_page_id?: number;
  source_chunk_id?: string;
  sheet_name?: string;
  cell_range?: string;
  page_no?: number;
  row_number?: number;
  row_start?: number;
}

export interface AnnualAuditEvidenceReference {
  source_file_id?: number;
  source_page_id?: number;
  source_chunk_id?: string;
  source_locator?: AnnualAuditEvidenceLocator;
  [key: string]: unknown;
}

export interface AnnualAuditProgramItem {
  id: number;
  procedure_code: string;
  program_version: string;
  phase: string;
  cycle: string;
  procedure_name: string;
  assertions: string[];
  risk_area: string;
  required_material_categories: string[];
  missing_material_categories: string[];
  requires_evidence: boolean;
  status: AnnualAuditProgramStatus;
  sample_plan: Record<string, unknown> | unknown[];
  evidence_refs: AnnualAuditEvidenceReference[];
  exception_count: number;
  alternative_procedures: Record<string, unknown> | unknown[];
  conclusion_text: string;
  not_applicable_reason: string;
  prepared_by: string;
  prepared_at?: string | null;
  reviewed_by: string;
  reviewed_at?: string | null;
  policy_binding_id?: number | null;
  revision: number;
  updated_at?: string | null;
}

export interface AnnualAuditReview {
  review_level: AnnualAuditReviewLevel;
  decision: AnnualAuditReviewDecision;
  decision_note: string;
  scope: Record<string, unknown> | unknown[];
  reviewer_user_id: string;
  created_at?: string | null;
}

export interface AnnualKnowledgeReleaseSummary {
  release_code: string;
  release_version: string;
  status: string;
  effective_from?: string | null;
  effective_to?: string | null;
}

export interface AnnualRulesetSummary {
  ruleset_code: string;
  version: string;
  status: string;
  effective_from?: string | null;
  effective_to?: string | null;
}

export interface AnnualAuditPolicyBinding {
  binding_id: number;
  binding_status: string;
  reporting_period_date?: string | null;
  knowledge_release: AnnualKnowledgeReleaseSummary;
  ruleset: AnnualRulesetSummary;
  bound_by: string;
  bound_at?: string | null;
  snapshot: Record<string, unknown>;
}

export interface AnnualAuditBlocker {
  code: string;
  message: string;
  missing_categories?: string[];
  finding_ids?: number[];
}

export interface AnnualAuditFindingSummary {
  count: number;
  findings: Array<{
    finding_id: number;
    risk_level: string;
    title: string;
    status: string;
  }>;
}

export interface AnnualAuditProgramSummary {
  total: number;
  completed: number;
  not_applicable: number;
  open: number;
}

export interface AnnualAuditReleaseGate {
  case_id: number;
  engagement_status: string;
  gate_status: "blocked" | "ready_for_signature";
  blockers: AnnualAuditBlocker[];
  profile: AnnualAuditProfile;
  program_summary: AnnualAuditProgramSummary;
  open_findings: AnnualAuditFindingSummary;
  reviews: AnnualAuditReview[];
  policy_binding: AnnualAuditPolicyBinding | null;
  evaluated_at?: string | null;
  gate_id?: number;
}

export interface AnnualAuditExecutionSnapshot {
  case_id: number;
  program_version: string;
  profile: AnnualAuditProfile;
  document_categories: AnnualAuditDocumentCategory[];
  program: AnnualAuditProgramItem[];
  reviews: AnnualAuditReview[];
  policy_binding: AnnualAuditPolicyBinding | null;
  release_gate: AnnualAuditReleaseGate;
}

export interface AnnualEngagementProfileUpdate {
  profile?: Record<string, unknown>;
  acceptance_status?: "pending" | "accepted" | "rejected" | "withdrawn";
  independence_status?: "pending" | "cleared" | "blocked" | "not_applicable";
  entity_type?: string;
  audit_purpose?: string;
  accounting_framework?: string;
  firm_name?: string;
  engagement_partner?: string;
  signing_cpa_primary?: string;
  signing_cpa_secondary?: string;
  signing_cpa_primary_user_id?: string;
  signing_cpa_secondary_user_id?: string;
  data_classification?: string;
  data_residency?: string;
  model_data_policy?: string;
}

export interface AnnualAuditProgramItemUpdate {
  status?: AnnualAuditProgramStatus;
  sample_plan?: Record<string, unknown> | unknown[];
  evidence_refs?: AnnualAuditEvidenceReference[];
  exception_count?: number;
  alternative_procedures?: Record<string, unknown> | unknown[];
  conclusion_text?: string;
  not_applicable_reason?: string;
}

export interface AnnualAuditReviewDecisionRequest {
  review_level: AnnualAuditReviewLevel;
  decision: Exclude<AnnualAuditReviewDecision, "pending">;
  decision_note?: string;
  scope?: Record<string, unknown> | unknown[];
}

export interface AnnualAuditPolicyBindingRequest {
  knowledge_release_id: number;
  ruleset_id: number;
  reporting_period_date?: string;
}

export interface AnnualAuditPolicyBindingResponse {
  case_id: number;
  binding_id: number;
  binding_status: string;
  snapshot: Record<string, unknown>;
}

export interface AnnualAuditPolicyCatalogItem {
  id: number;
  status: string;
  effective_from?: string | null;
  effective_to?: string | null;
}

export interface AnnualAuditKnowledgeReleaseCatalogItem extends AnnualAuditPolicyCatalogItem {
  release_code: string;
  release_version: string;
}

export interface AnnualAuditRulesetCatalogItem extends AnnualAuditPolicyCatalogItem {
  ruleset_code: string;
  version: string;
  name: string;
}

export interface AnnualAuditPolicyCatalog {
  knowledge_releases: AnnualAuditKnowledgeReleaseCatalogItem[];
  rulesets: AnnualAuditRulesetCatalogItem[];
}

export interface AnnualAuditTemplateVersion {
  id: number;
  template_id: number;
  template_code: string;
  template_type: string;
  version_no: number;
  version_label: string;
  status: string;
  content: Record<string, unknown>;
  field_schema: Record<string, unknown> | unknown[];
  content_hash: string;
  file_count: number;
  files: AnnualAuditTemplateFile[];
  created_by: string;
  published_by: string;
  published_at?: string | null;
  created_at?: string | null;
}

export interface AnnualAuditTemplateFile {
  id: number;
  template_version_id: number;
  file_name: string;
  file_ext: string;
  content_type: string;
  storage_ref?: string;
  storage_sha256: string;
  file_size: number;
  status: string;
  created_by?: string;
  created_at?: string | null;
}

export interface AnnualAuditTemplate {
  id: number;
  template_code: string;
  template_type: string;
  template_type_label: string;
  name: string;
  description: string;
  status: string;
  active_version_no: number;
  active_version?: AnnualAuditTemplateVersion;
  versions?: AnnualAuditTemplateVersion[];
}

export interface AnnualAuditTemplateCatalog {
  templates: AnnualAuditTemplate[];
  template_types: Record<string, string>;
}

export interface AnnualAuditTemplateCreateRequest {
  template_code: string;
  template_type: string;
  name: string;
  description?: string;
  content?: Record<string, unknown>;
  field_schema?: Record<string, unknown> | unknown[];
  version_label?: string;
}

export interface AnnualAuditTemplateVersionRequest {
  content?: Record<string, unknown>;
  field_schema?: Record<string, unknown> | unknown[];
  version_label?: string;
}

export interface GenericTemplateFile {
  id: number;
  template_version_id: number;
  file_name: string;
  file_ext: string;
  content_type: string;
  storage_ref?: string;
  storage_sha256: string;
  file_size: number;
  template_usage: string;
  template_usage_label: string;
  remark: string;
  status: string;
  created_at?: string | null;
}

export interface GenericTemplateContract {
  required_usages: string[];
  present_usages: string[];
  usage_counts: Record<string, number>;
  missing_usages: string[];
  ready_for_core_delivery: boolean;
}

export interface GenericTemplateVersion {
  id: number;
  template_id: number;
  template_code: string;
  template_name: string;
  business_line: string;
  description: string;
  template_status: string;
  active_version_no: number;
  version_no: number;
  version_label: string;
  status: string;
  content_hash: string;
  file_count: number;
  files: GenericTemplateFile[];
  template_contract?: GenericTemplateContract;
  created_by: string;
  published_by: string;
  published_at?: string | null;
  created_at?: string | null;
}

export interface GenericTemplateVersionCatalog {
  versions: GenericTemplateVersion[];
  business_lines: string[];
  template_types?: Record<string, string>;
  template_usage_labels: Record<string, string>;
}

export function annualAuditExecutionKey(caseId: number): string {
  return casesUrl(`/api/annual-audit/${caseId}/execution`);
}

export function getTemplateVersions(): Promise<GenericTemplateVersionCatalog> {
  return getJson<GenericTemplateVersionCatalog>(
    casesUrl("/api/templates"),
    "获取模板版本失败"
  );
}

export interface CreateGenericTemplateVersionRequest {
  template_name: string;
  business_line: string;
  version_label?: string;
  description?: string;
  template_code?: string;
  template_usage?: string;
  remark?: string;
  template_usages?: string[];
  remarks?: string[];
  files: File[];
}

export function createTemplateVersion(
  payload: CreateGenericTemplateVersionRequest
): Promise<GenericTemplateVersion> {
  const form = new FormData();
  form.set("template_name", payload.template_name);
  form.set("business_line", payload.business_line);
  form.set("version_label", payload.version_label ?? "");
  form.set("description", payload.description ?? "");
  form.set("template_code", payload.template_code ?? "");
  form.set("template_usage", payload.template_usage ?? "");
  form.set("remark", payload.remark ?? "");
  payload.files.forEach((file, index) => {
    form.append("files", file, file.name);
    form.append("template_usages", payload.template_usages?.[index] ?? payload.template_usage ?? "");
    form.append("remarks", payload.remarks?.[index] ?? payload.remark ?? "");
  });
  return postForm<GenericTemplateVersion>(
    casesUrl("/api/templates/versions"),
    form,
    "创建模板版本失败"
  );
}

export function getTemplateVersion(
  templateCode: string,
  versionNo: number
): Promise<GenericTemplateVersion> {
  return getJson<GenericTemplateVersion>(
    casesUrl(`/api/templates/${encodeURIComponent(templateCode)}/versions/${versionNo}`),
    "获取模板文件失败"
  );
}

export function uploadTemplateVersionFiles(
  templateCode: string,
  versionNo: number,
  files: File[],
  templateUsages: string[] = [],
  remarks: string[] = []
): Promise<GenericTemplateVersion> {
  const form = new FormData();
  files.forEach((file, index) => {
    form.append("files", file, file.name);
    form.append("template_usages", templateUsages[index] ?? "");
    form.append("remarks", remarks[index] ?? "");
  });
  return postForm<GenericTemplateVersion>(
    casesUrl(`/api/templates/${encodeURIComponent(templateCode)}/versions/${versionNo}/files`),
    form,
    "上传模板文件失败"
  );
}

export function deleteTemplateVersion(templateCode: string, versionNo: number): Promise<void> {
  return deleteJson(
    casesUrl(`/api/templates/${encodeURIComponent(templateCode)}/versions/${versionNo}`),
    "删除模板版本失败"
  );
}

export function deleteGenericTemplateFile(fileId: number): Promise<void> {
  return deleteJson(casesUrl(`/api/templates/files/${fileId}`), "删除模板文件失败");
}

export function activateTemplateVersion(templateCode: string, versionNo: number): Promise<GenericTemplateVersion> {
  return postWithoutBody<GenericTemplateVersion>(
    casesUrl(`/api/templates/${encodeURIComponent(templateCode)}/versions/${versionNo}/activate`),
    "激活模板版本失败"
  );
}

export function annualAuditReleaseGateKey(caseId: number): string {
  return casesUrl(`/api/annual-audit/${caseId}/release-gate`);
}

export function annualAuditPolicyCatalogKey(): string {
  return casesUrl("/api/annual-audit/knowledge/policy-catalog");
}

export function getAnnualAuditExecution(caseId: number): Promise<AnnualAuditExecutionSnapshot> {
  return getJson<AnnualAuditExecutionSnapshot>(
    annualAuditExecutionKey(caseId),
    "获取年审执行工作台失败"
  );
}

export function updateAnnualAuditProfile(
  caseId: number,
  payload: AnnualEngagementProfileUpdate
): Promise<AnnualAuditExecutionSnapshot> {
  return putJson<AnnualAuditExecutionSnapshot>(
    casesUrl(`/api/annual-audit/${caseId}/profile`),
    payload,
    "保存项目画像失败"
  );
}

export function updateAnnualAuditProgramItem(
  caseId: number,
  procedureCode: string,
  payload: AnnualAuditProgramItemUpdate
): Promise<AnnualAuditProgramItem> {
  return putJson<AnnualAuditProgramItem>(
    casesUrl(`/api/annual-audit/${caseId}/program/${encodeURIComponent(procedureCode)}`),
    payload,
    "保存审计程序失败"
  );
}

export function recordAnnualAuditReview(
  caseId: number,
  payload: AnnualAuditReviewDecisionRequest
): Promise<AnnualAuditExecutionSnapshot> {
  return postJson<AnnualAuditExecutionSnapshot>(
    casesUrl(`/api/annual-audit/${caseId}/reviews`),
    payload,
    "记录复核决定失败"
  );
}

export function getAnnualAuditReleaseGate(caseId: number): Promise<AnnualAuditReleaseGate> {
  return getJson<AnnualAuditReleaseGate>(
    annualAuditReleaseGateKey(caseId),
    "获取签发门禁失败"
  );
}

export function evaluateAnnualAuditReleaseGate(
  caseId: number
): Promise<AnnualAuditReleaseGate> {
  return postWithoutBody<AnnualAuditReleaseGate>(
    annualAuditReleaseGateKey(caseId),
    "评估签发门禁失败"
  );
}

export function getAnnualAuditPolicyCatalog(): Promise<AnnualAuditPolicyCatalog> {
  return getJson<AnnualAuditPolicyCatalog>(
    annualAuditPolicyCatalogKey(),
    "获取可冻结的规则与知识版本失败"
  );
}

export function annualAuditTemplatesKey(): string {
  return casesUrl("/api/annual-audit/templates");
}

export function getAnnualAuditTemplates(): Promise<AnnualAuditTemplateCatalog> {
  return getJson<AnnualAuditTemplateCatalog>(
    annualAuditTemplatesKey(),
    "获取年审模板版本失败"
  );
}

export function createAnnualAuditTemplate(
  payload: AnnualAuditTemplateCreateRequest
): Promise<Record<string, unknown>> {
  return postJson<Record<string, unknown>>(
    annualAuditTemplatesKey(),
    payload,
    "创建年审模板失败"
  );
}

export function createAnnualAuditTemplateVersion(
  templateCode: string,
  payload: AnnualAuditTemplateVersionRequest
): Promise<Record<string, unknown>> {
  return postJson<Record<string, unknown>>(
    casesUrl(`/api/annual-audit/templates/${encodeURIComponent(templateCode)}/versions`),
    payload,
    "创建模板版本失败"
  );
}

export function activateAnnualAuditTemplateVersion(
  templateCode: string,
  versionNo: number
): Promise<Record<string, unknown>> {
  return postWithoutBody<Record<string, unknown>>(
    casesUrl(
      `/api/annual-audit/templates/${encodeURIComponent(templateCode)}/versions/${versionNo}/activate`
    ),
    "激活模板版本失败"
  );
}

export function uploadAnnualAuditTemplateFiles(
  templateCode: string,
  versionNo: number,
  files: File[]
): Promise<{ template_code: string; version_no: number; files: AnnualAuditTemplateFile[] }> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file, file.name));
  return postForm<{ template_code: string; version_no: number; files: AnnualAuditTemplateFile[] }>(
    casesUrl(`/api/annual-audit/templates/${encodeURIComponent(templateCode)}/versions/${versionNo}/files`),
    form,
    "上传年审模板文件失败"
  );
}

export function deleteAnnualAuditTemplateFile(fileId: number): Promise<void> {
  return deleteJson(
    casesUrl(`/api/annual-audit/templates/files/${fileId}`),
    "删除年审模板文件失败"
  );
}

export function freezeAnnualAuditPolicyBinding(
  caseId: number,
  payload: AnnualAuditPolicyBindingRequest
): Promise<AnnualAuditPolicyBindingResponse> {
  return postJson<AnnualAuditPolicyBindingResponse>(
    casesUrl(`/api/annual-audit/${caseId}/policy-binding`),
    payload,
    "冻结规则与知识版本失败"
  );
}

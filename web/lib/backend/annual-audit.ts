import { casesUrl } from "@/lib/api/client";
import { getJson, postJson, postWithoutBody, putJson } from "./http";

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

export function annualAuditExecutionKey(caseId: number): string {
  return casesUrl(`/api/annual-audit/${caseId}/execution`);
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

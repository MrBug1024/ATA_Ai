import { casesUrl } from "@/lib/api/client";
import { deleteJson, getJson, postJson } from "./http";
import type {
  CaseDocCategoriesResp,
  DocCategoriesResp,
  ValidateDocCategoryReq,
  ValidateDocCategoryResp,
} from "@/lib/types/doc-categories";

// ── Cases ────────────────────────────────────────────────────────────────────

export interface Case {
  case_id: number;
  case_name: string;
  case_type: string;
  entity_name: string;
  status: string;
  task_count?: number;
  pending_task_count?: number;
  engagement_code?: string;
  fiscal_year?: number;
  period_start?: string;
  period_end?: string;
  created_at?: string;
  updated_at?: string;
}

export interface CasesPage {
  cases: Case[];
  total: number;
  page: number;
  page_size: number;
}

export const CASES_PAGE_SIZE = 20;

export function casesKey(page: number, keyword: string): string {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(CASES_PAGE_SIZE),
  });
  if (keyword) params.set("keyword", keyword);
  return casesUrl(`/api/cases?${params.toString()}`);
}

export async function listCases(page: number, keyword: string): Promise<CasesPage> {
  return getJson<CasesPage>(casesKey(page, keyword), "获取年审项目列表失败");
}

export interface CreateCasePayload {
  case_name: string;
  case_type: string;
  entity_name: string;
  company_id?: string;
  entity_uscc?: string;
  fiscal_year?: number;
}

export async function createCase(
  payload: CreateCasePayload
): Promise<{ case_id: number; message?: string }> {
  return postJson(casesUrl("/api/ingest/case"), payload, "创建失败");
}

export async function deleteCase(caseId: number): Promise<void> {
  return deleteJson(casesUrl(`/api/cases/${caseId}`), "移除年审项目失败");
}

// ── Doc categories ───────────────────────────────────────────────────────────

export function docCategoriesKey(): string {
  return casesUrl("/api/ingest/doc-categories");
}

export async function getDocCategories(): Promise<DocCategoriesResp["categories"]> {
  const data = await getJson<DocCategoriesResp>(docCategoriesKey(), "获取年审资料类别失败");
  return data.categories ?? [];
}

export function caseDocCategoriesKey(caseId: number): string {
  return casesUrl(`/api/case/${caseId}/doc-categories`);
}

export async function getCaseDocCategories(caseId: number): Promise<CaseDocCategoriesResp> {
  return getJson<CaseDocCategoriesResp>(caseDocCategoriesKey(caseId), "获取年审项目资料类别失败");
}

export async function validateDocCategory(
  req: ValidateDocCategoryReq
): Promise<ValidateDocCategoryResp> {
  return postJson<ValidateDocCategoryResp>(
    casesUrl("/api/ingest/validate-doc-category"),
    req,
    "校验失败"
  );
}

import { casesUrl } from "@/lib/api/client";
import { getJson, postJson } from "./http";
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
  debtor_names?: string;
  debtor_count?: number;
  status: string;
  composite_score?: number;
  delta_score?: number;
  valuation_score?: number;
  deadline_score?: number;
  behavioral_score?: number;
  task_count?: number;
  pending_task_count?: number;
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
  return getJson<CasesPage>(casesKey(page, keyword), "获取案件列表失败");
}

export interface CreateCasePayload {
  case_name: string;
  case_type: string;
  debtor_name?: string;
  debtor_uscc?: string;
}

export async function createCase(
  payload: CreateCasePayload
): Promise<{ case_id: number; message?: string }> {
  return postJson(casesUrl("/api/ingest/case"), payload, "创建失败");
}

// ── Doc categories ───────────────────────────────────────────────────────────

export function docCategoriesKey(): string {
  return casesUrl("/api/ingest/doc-categories");
}

export async function getDocCategories(): Promise<DocCategoriesResp["categories"]> {
  const data = await getJson<DocCategoriesResp>(docCategoriesKey(), "获取卷宗类别失败");
  return data.categories ?? [];
}

export function caseDocCategoriesKey(caseId: number): string {
  return casesUrl(`/api/case/${caseId}/doc-categories`);
}

export async function getCaseDocCategories(caseId: number): Promise<CaseDocCategoriesResp> {
  return getJson<CaseDocCategoriesResp>(caseDocCategoriesKey(caseId), "获取案件卷宗类别失败");
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

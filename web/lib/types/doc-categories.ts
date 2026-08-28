// GET /api/ingest/doc-categories
export interface DocCategory {
  code: string;
  name: string;
  description: string;
  sort_order: number;
  enabled: boolean;
  fields: string[];
}

export interface DocCategoriesResp {
  categories: DocCategory[];
}

// GET /api/case/{case_id}/doc-categories
export interface CaseDocCategoryItem {
  code: string;
  name: string;
  uploaded: boolean;
  raw_uploaded?: boolean;
  covered_by_case_workpaper?: boolean;
  coverage_basis?: "uploaded" | "case_workpaper" | "missing" | string;
  file_count: number;
  record_count: number;
  last_uploaded_at: string | null;
}

export interface CaseDocCategoriesResp {
  case_id: number;
  categories: CaseDocCategoryItem[];
  missing_categories: string[];
}

// POST /api/ingest/validate-doc-category
export interface ValidateDocCategoryReq {
  case_id: number;
  doc_category: string;
  file_names?: string[];
  /** Legacy single-file callers are still accepted by the client contract. */
  filename?: string;
  preview_text?: string;
}

export interface ValidateDocCategoryResp {
  ok: boolean;
  suspected_mismatch: boolean;
  suspected_duplicate: boolean;
  message: string;
}

// POST /files/upload-and-ingest
export interface UploadBatchSummary {
  material_event_id: string;
  material_event_type: string;
  material_event_status: string;
  upload_batch_id: string;
  batch_name: string;
  doc_category: string;
  operator_id: string;
  operator_name: string;
  file_count: number;
  new_file_count: number;
  duplicate_file_count: number;
  suspected_mismatch_file_count: number;
  status: string;
  stage: string;
  has_conclusion_changes: boolean;
  reconciliation_item_count: number;
  add_item_count: number;
  override_item_count: number;
  change_summary: string;
}

export interface DocCategoryValidation {
  ok: boolean;
  suspected_mismatch: boolean;
  suspected_duplicate: boolean;
  duplicate_files: string[];
  suspected_mismatch_files: string[];
  message: string;
}

export interface CaseDocCategoryStatus {
  case_id: number;
  categories: CaseDocCategoryItem[];
  missing_categories: string[];
}

export interface UploadAndIngestResponse {
  accepted?: boolean;
  upload_batch_id?: string;
  material_event_id?: string;
  status?: string;
  stage?: string;
  upload_batch_detail_path?: string;
  material_event_detail_path?: string;
  case_upload_batches_path?: string;
  doc_category?: string;
  batch_name?: string;
  operator_id?: string;
  operator_name?: string;
  uploaded_file_count?: number;
  upload_batch_summary?: UploadBatchSummary;
  doc_category_validation?: DocCategoryValidation;
  case_doc_category_status?: CaseDocCategoryStatus;
  duplicate_files?: string[];
  suspected_mismatch_files?: string[];
  new_files?: string[];
  /** Compatibility with pre-async servers; absent from the current OpenAPI response. */
  parse_summary?: string;
  /** Compatibility with pre-async servers; non-2xx errors now throw BackendError. */
  error?: string | null;
}

export type UploadRetryStage = "auto" | "parse" | "graph";

export interface UploadRetryResponse {
  accepted?: boolean;
  upload_batch_id?: string;
  material_event_id?: string;
  status?: string;
  retry_stage?: string;
  stage?: string;
  upload_batch_detail_path?: string;
  material_event_detail_path?: string;
}

// GET /files/upload-batches/{id}
export interface UploadBatchFile {
  upload_batch_link_id: number;
  file_id: number;
  file_name: string;
  file_sha256: string;
  duplicate_of: string;
  file_type: string;
  content_type: string;
  storage_provider: string;
  storage_bucket: string;
  storage_key: string;
  storage_ref: string;
  created_at: string;
  page_count: number;
  chunk_count: number;
  doc_categories: string[];
}

export interface UploadBatchPersistenceChecks {
  source_upload_batch_exists: boolean;
  source_file_upload_batch_count: number;
  source_file_count_matches: boolean;
  source_page_file_count: number;
  source_chunk_file_count: number;
  source_file_doc_category_count: number;
  all_files_have_chunks: boolean;
  all_files_have_doc_category: boolean;
}

export interface UploadBatchDetail {
  upload_batch_id: string;
  case_id: number;
  entity_id: number;
  batch_name: string;
  doc_category: string;
  operator_id: string;
  operator_name: string;
  status: string;
  stage: string;
  file_count: number;
  new_file_count: number;
  duplicate_file_count: number;
  suspected_mismatch_file_count: number;
  records_inserted: number;
  metadata: Record<string, unknown>;
  has_conclusion_changes: boolean;
  reconciliation_item_count: number;
  add_item_count: number;
  override_item_count: number;
  change_summary: string;
  created_at: string;
  updated_at: string;
  files: UploadBatchFile[];
  persistence_checks: UploadBatchPersistenceChecks;
}

// GET /files/cases/{id}/upload-batches
export interface CaseUploadBatchItem {
  upload_batch_id: string;
  batch_name: string;
  doc_category: string;
  status: string;
  file_count: number;
  new_file_count: number;
  duplicate_file_count: number;
  created_at: string;
  updated_at: string;
}

export interface CaseUploadBatchesResp {
  case_id: number;
  upload_batches: CaseUploadBatchItem[];
}

// GET /files/material-events/{id}
export interface MaterialEventPayload {
  stage: string;
  new_files: string[];
  parse_summary: string;
  add_item_count: number;
  change_summary: string;
  chunk_batch_ref: string;
  duplicate_files: string[];
  categories_found: string[];
  ingest_payload_ref: string;
  aggregated_text_ref: string;
  override_item_count: number;
  recognized_categories: string[];
  has_conclusion_changes: boolean;
  suspected_mismatch_files: string[];
  parse_document_result_ref: string;
  reconciliation_item_count: number;
}

export interface MaterialEventDetail {
  material_event_id: string;
  case_id: number;
  entity_id: number;
  upload_batch_id: string;
  event_type: string;
  status: string;
  batch_name: string;
  doc_category: string;
  operator_id: string;
  operator_name: string;
  file_count: number;
  records_inserted: number;
  event_payload: MaterialEventPayload;
  stage: string;
  has_conclusion_changes: boolean;
  reconciliation_item_count: number;
  add_item_count: number;
  override_item_count: number;
  change_summary: string;
  error_message: string;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  created_at: string;
  updated_at: string;
}

// GET /files/cases/{case_id}/material-events
export interface CaseMaterialEventItem {
  material_event_id: string;
  case_id?: number;
  entity_id?: number;
  event_type: string;
  status: string;
  upload_batch_id: string;
  doc_category: string;
  batch_name: string;
  operator_id?: string;
  operator_name?: string;
  file_count: number;
  records_inserted?: number;
  event_payload?: Record<string, unknown>;
  stage: string;
  has_conclusion_changes?: boolean;
  reconciliation_item_count?: number;
  add_item_count?: number;
  override_item_count?: number;
  change_summary?: string;
  error_message?: string;
  started_at?: string | null;
  completed_at?: string | null;
  failed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CaseMaterialEventsResp {
  case_id: number;
  material_events: CaseMaterialEventItem[];
}

export interface FileItem {
  name: string;
  url: string;
  type: string;
  extension: string;
  content_type: string;
  content: string;
  doc_category: string;
  upload_batch_id: string;
  file_hash: string;
  file_size: number;
  content_ref: string;
  duplicate_of: string;
  storage_ref: string;
  storage_provider: string;
  storage_bucket: string;
  storage_key: string;
  storage_etag: string;
  storage_version: string;
}

export interface ChatUploadResponse {
  upload_batch_id: string;
  case_id: number;
  entity_id: number;
  entity_name: string;
  effective_entity_name: string;
  file_count: number;
  duplicate_files: string[];
  files: FileItem[];
}

export interface ChatUploadRequest {
  caseId: number;
  entityId?: number;
  entityName?: string;
  docCategory?: string;
  batchName?: string;
  uploadBatchId?: string;
  operatorId?: string;
  operatorName?: string;
}

export interface BBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface EvidenceItem {
  chunk_id: string;
  file_id: number;
  file_name: string;
  page_no: number;
  quote_text: string;
  bbox_list: BBox[];
  page_image_ref: string;
  source_page_id: number;
  // 后端新契约：原始文件公网 URL（PDF/图片用它渲染，page_image_ref 对 PDF 恒空）
  source_file_url?: string;
  // 源文件 MIME，前端据此切换渲染模式（text/* 纯文本，application/pdf、image/* 页面模式）
  content_type?: string;
  locator_kind?: string;
  sheet_name?: string;
  row_start?: number;
  row_end?: number;
  cell_range?: string;
  preview_ref?: string;
  preview_available?: boolean;
  page_width?: number;
  page_height?: number;
  // 该证据关联的实体（用于「在图谱中查看」），无关联时为 0
  entity_id?: number;
}

export interface PageAnchorsResponse {
  file_id: number;
  page_no: number;
  page_width: number;
  page_height: number;
  page_image_ref: string;
  anchors: EvidenceItem[];
  // 顶层便捷字段（后端新契约）
  file_name?: string;
  source_file_url?: string;
  content_type?: string;
  locator_kind?: string;
  sheet_name?: string;
}

export interface EvidenceResolveRequest {
  case_id: number;
  report_ref: string;
  citation_id: string;
  claim_id?: number;
}

export interface EvidenceResolveResponse {
  case_id: number;
  report_ref: string;
  citation_id: string;
  claim_id: number;
  claim_text: string;
  evidences: EvidenceItem[];
  primary_evidence: EvidenceItem | null;
  primary_page: PageAnchorsResponse | null;
  // 后端新契约：区分四态 ok / no_evidence / citation_not_found / ref_not_found
  resolution_status?: "ok" | "no_evidence" | "citation_not_found" | "ref_not_found";
}

export interface GraphNode {
  id: string;
  entity_id: number;
  label: string;
  entity_type: string;
  /** OpenAPI 中可缺省且未限定枚举；画布统一将缺省值视为 unknown。 */
  risk_level?: string | null;
}

export interface GraphEdge {
  id: string;
  relation_id: number;
  source: string;
  target: string;
  label: string;
  relation_type: string;
  /** OpenAPI 默认 0，但响应字段本身不是 required。 */
  confidence?: number;
}

export interface SubgraphRequest {
  case_id: number;
  center_entity_id: number;
  depth?: number;
  relation_types?: string[];
}

export interface SubgraphResponse {
  case_id: number;
  nodes?: GraphNode[];
  edges?: GraphEdge[];
}

// GET /graph/cases/{id}/entities — 列实体（供 GraphModal 选中心点）
export interface GraphEntityItem {
  entity_id: number;
  label: string;
  entity_type: string;
  degree: number;
  /** 实体列表 schema 当前不返回该字段，保留可选项兼容旧响应。 */
  risk_level?: string | null;
}

export interface GraphEntitiesResponse {
  case_id: number;
  entities?: GraphEntityItem[];
}

export interface TraceItem {
  citation_id: string;
  claim_id: number;
  claim_type: string;
  claim_text: string;
  confidence: number;
  evidences: EvidenceItem[];
  // 该 claim 关联实体（后端新契约），无关联为 0
  entity_id?: number;
}

export interface RelationEvidenceRequest {
  case_id: number;
  relation_id: number;
}

export interface RelationEvidenceResponse {
  case_id: number;
  relation_id: number;
  trace_items: TraceItem[];
}

export interface EvolutionItem {
  id: number | null;
  case_id: number;
  action: "ADD" | "OVERRIDE";
  new_claim_id: number | null;
  new_claim_type: string;
  new_claim_text: string;
  superseded_claim_id: number | null;
  superseded_claim_type: string;
  superseded_claim_text: string;
  new_relation_id: number | null;
  superseded_relation_id: number | null;
  rationale: string;
  evidence_chunk_ids: string[];
  upload_batch_id: string;
  batch_name: string;
  doc_category: string;
  material_event_id: string;
  material_event_status: string;
  material_event_type: string;
  evidences: EvidenceItem[];
  created_at: string | null;
}

export interface EvolutionItemsResponse {
  case_id: number;
  action: string;
  evolution_items: EvolutionItem[];
}

export interface UnresolvedRelation {
  id: number | null;
  case_id: number;
  extraction_run_id: number;
  upload_batch_id: string;
  material_event_id: string;
  item_type: "relation";
  relation_key: string;
  relation_type: string;
  relation_label: string;
  entity_temp_id: string;
  relation_temp_id: string;
  missing_dependencies: string[];
  reason: string;
  status: string;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface UnresolvedClaim {
  id: number | null;
  case_id: number;
  extraction_run_id: number;
  upload_batch_id: string;
  material_event_id: string;
  item_type: "claim";
  entity_name: string;
  entity_key: string;
  relation_key: string;
  claim_type: string;
  claim_text: string;
  missing_dependencies: string[];
  reason: string;
  status: string;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface UnresolvedItemsResponse {
  case_id: number;
  upload_batch_id: string;
  status: string;
  unresolved_relation_count: number;
  unresolved_claim_count: number;
  unresolved_relations: UnresolvedRelation[];
  unresolved_claims: UnresolvedClaim[];
}

export interface ValidationCheck {
  citation_id: string;
  claim_id: number;
  claim_text: string;
  ok: boolean;
  evidence_count: number;
  anchor_count: number;
  file_id: number;
  page_no: number;
  issues: string[];
}

export interface ValidationRequest {
  case_id: number;
  report_ref: string;
  citation_ids?: string[];
}

export interface ValidationResponse {
  case_id: number;
  report_ref: string;
  ready: boolean;
  total_citations: number;
  passed_citations: number;
  failed_citations: number;
  checks: ValidationCheck[];
  issues: string[];
}

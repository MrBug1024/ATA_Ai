import type { FileItem } from "@/lib/types/chat-upload";
import type { TraceItem } from "@/lib/types/knowledge-graph";

export interface LangGraphThread {
  thread_id: string;
  title: string;
  checkpoint_id: string;
  case_id: number;
  debtor_id: number;
  debtor_name: string;
  last_query: string;
  last_intent: string;
  updated_at: string | null;
}

export interface ThreadListResponse {
  threads: LangGraphThread[];
  total: number;
  limit: number;
  offset: number;
}

export interface ThreadDetailResponse {
  thread_id: string;
  title: string;
  checkpoint_id: string;
  case_id: number;
  debtor_id: number;
  debtor_name: string;
  last_query: string;
  last_intent: string;
  final_report_ref: string;
  memory_context: string;
  step: number;
  upload_batch_id: string;
  doc_category: string;
  batch_name: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface CitationCoverageMissingItem {
  citation_id: string;
  claim_id: number;
  claim_type: string;
  claim_text: string;
}

export interface CitationCoverage {
  total_claims: number;
  cited_claims: number;
  uncited_claims: number;
  coverage_ratio: number;
  missing_items: CitationCoverageMissingItem[];
}

export interface ReplayUnresolvedRelation {
  relation_temp_id: string;
  relation_key: string;
  relation_type: string;
  relation_label: string;
  from_entity_temp_id: string;
  to_entity_temp_id: string;
  missing_dependencies: string[];
  reason: string;
  evidence_chunk_ids: string[];
}

export interface ReplayUnresolvedClaim {
  claim_type: string;
  claim_text: string;
  entity_name: string;
  entity_key: string;
  entity_temp_id: string;
  relation_key: string;
  relation_temp_id: string;
  missing_dependencies: string[];
  reason: string;
  evidence_chunk_ids: string[];
}

export interface ThreadMessage {
  id: string;
  role: string;
  content: string;
  type: string;
  name: string;
  final_report_ref: string;
  intent: string;
  uploaded_files: FileItem[];
  trace_items: TraceItem[];
  citation_coverage: CitationCoverage;
  unresolved_relations: ReplayUnresolvedRelation[];
  unresolved_claims: ReplayUnresolvedClaim[];
}

export interface ThreadMessagesResponse {
  thread_id: string;
  messages: ThreadMessage[];
  message_count: number;
}

export interface UserTurnItem {
  turn_id: string;
  role: string;
  content: string;
  created_at: string;
  uploaded_files: FileItem[];
}

export interface AssistantTurnItem {
  turn_id: string;
  role: string;
  content: string;
  final_report_ref: string;
  intent: string;
  case_id: number;
  version: number;
  created_at: string;
}

export interface TurnGroup {
  turn_id: string;
  user: UserTurnItem;
  assistants: AssistantTurnItem[];
}

export interface ThreadTurnsResponse {
  thread_id: string;
  turns: TurnGroup[];
  turn_count: number;
}

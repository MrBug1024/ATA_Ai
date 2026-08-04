export interface CorrectionCreateRequest {
  target: string;
  instruction: string;
  source_query?: string;
  operator_id?: string;
  operator_name?: string;
  scope?: string;
}

export type CorrectionStatus = "active" | "superseded" | "revoked";

export interface CorrectionModel {
  id: number;
  case_id: number;
  target: string;
  instruction: string;
  source_query: string;
  operator_id: string;
  operator_name: string;
  operator_meta: Record<string, unknown>;
  scope: string;
  origin: string;
  status: CorrectionStatus;
  superseded_by: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CorrectionListResponse {
  case_id: number;
  corrections: CorrectionModel[];
}

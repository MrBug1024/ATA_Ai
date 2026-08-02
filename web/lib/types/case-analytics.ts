// 案件分析(LangGraph 8081 的 /cases/{id}/* 端点)类型契约。
// 注意:后端部分字段类型宽松(progress.forecasts/records/risk_alerts 为 object),
// 此处按语义补全为具体类型,渲染时按可选字段防御性处理。

// ── 预期回款 ──────────────────────────────────────────────────────────────────

export interface ForecastItem {
  tranche: string;
  expected_amount: number;
  expected_date: string | null;
  basis: string;
}

export interface ForecastSeedRequest {
  report_ref: string;
  tranches: ForecastItem[];
}

export interface ForecastListResponse {
  case_id: number;
  forecasts: ForecastItem[];
}

// ── 实际回款 ──────────────────────────────────────────────────────────────────

export interface RecoveryRecord {
  id: number;
  case_id: number;
  amount: number;
  recovered_at: string | null;
  disposal_path: string;
  related_task_id: string;
  source_desc: string;
  operator: string;
  note: string;
  // 待确认 pending / 已确认 confirmed 等;origin 区分 auto(自动抽取)/ manual(手记)
  status: string;
  origin: string;
}

export interface CreateRecoveryRequest {
  amount: number;
  recovered_at: string;
  disposal_path?: string;
  related_task_id?: string;
  source_desc?: string;
  operator?: string;
  note?: string;
}

export interface RecoveryListResponse {
  case_id: number;
  records: RecoveryRecord[];
}

// ── 进度看板 ──────────────────────────────────────────────────────────────────

export interface ReminderModel {
  type: string;
  level: string;
  message: string;
}

// 后端 risk_alerts 为 object[],形状不固定;保留原始键值并补常见字段。
export interface RiskAlert {
  level?: string;
  message?: string;
  [key: string]: unknown;
}

export interface ProgressBoard {
  case_id: number;
  stage: string | null;
  status: string | null;
  risk_alerts: RiskAlert[];
  expected_recovery_total: number;
  expected_recovery_total_wan: string;
  actual_recovery_total: number;
  actual_recovery_total_wan: string;
  recovery_ratio_pct: number;
  profit_distributable: number;
  profit_distributable_wan: string;
  profit_distributed: number;
  profit_distributed_wan: string;
  report_ref: string;
  forecasts: ForecastItem[];
  records: RecoveryRecord[];
  reminders: ReminderModel[];
  params: Record<string, unknown>;
}

export interface UpdateProgressRequest {
  stage?: string | null;
  status?: string | null;
  risk_alerts?: RiskAlert[] | null;
  expected_recovery_total?: number | null;
  profit_distributable?: number | null;
  profit_distributed?: number | null;
  report_ref?: string | null;
}

// ── AI 复盘 ───────────────────────────────────────────────────────────────────

export interface ReviewRequest {
  thread_id?: string;
  query?: string;
}

export interface ReviewResponse {
  thread_id: string;
  case_id: number;
  intent: string;
  final_report: string;
  review_metrics: Record<string, unknown>;
}

// ── 权威订正 ──────────────────────────────────────────────────────────────────

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

// ── 司法时效看板 ──────────────────────────────────────────────────────────────

export interface DeadlineThresholds extends Record<string, unknown> {
  red_days: number;
  yellow_days: number;
}

export interface DeadlineCounts extends Record<string, unknown> {
  expired: number;
  red: number;
  yellow: number;
  safe: number;
  unknown: number;
  total: number;
}

export interface DeadlineBoardItem extends Record<string, unknown> {
  type: string;
  due_date: string;
  remaining_days: number;
  related_asset: string;
  action: string;
  level: string;
}

export interface DeadlineGroups extends Record<string, unknown> {
  expired: DeadlineBoardItem[];
  red: DeadlineBoardItem[];
  yellow: DeadlineBoardItem[];
  safe: DeadlineBoardItem[];
  unknown: DeadlineBoardItem[];
}

export interface DeadlineBoardResponse {
  case_id?: number;
  available?: boolean;
  today?: string;
  thresholds?: Partial<DeadlineThresholds>;
  counts?: Partial<DeadlineCounts>;
  groups?: Partial<DeadlineGroups>;
}

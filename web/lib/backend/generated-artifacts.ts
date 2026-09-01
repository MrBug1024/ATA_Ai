import { casesUrl } from "@/lib/api/client";
import { getJson, postJson, postWithoutBody } from "./http";

export type AttachmentDeliveryLevel =
  | "review_draft"
  | "final_candidate"
  | "issued";

export type AttachmentJobStatus =
  | "queued"
  | "running"
  | "freezing_context"
  | "loading_template"
  | "composing"
  | "composing_payload"
  | "rendering"
  | "validating"
  | "previewing"
  | "publishing"
  | "succeeded"
  | "failed"
  | "cancelled";

export const TERMINAL_ATTACHMENT_JOB_STATUSES = new Set<AttachmentJobStatus>([
  "succeeded",
  "failed",
  "cancelled",
]);

export interface AttachmentJobRef {
  job_id: string;
  case_id: number;
  assistant_turn_id: string;
  report_id: number;
  report_version: number;
  template_version_id: string;
  template_version_label: string;
  delivery_level: AttachmentDeliveryLevel;
}

export function isAttachmentJobRef(value: unknown): value is AttachmentJobRef {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.job_id === "string" && record.job_id.trim().length > 0 &&
    typeof record.case_id === "number" && Number.isInteger(record.case_id) && record.case_id > 0 &&
    typeof record.assistant_turn_id === "string" &&
    typeof record.report_id === "number" && Number.isInteger(record.report_id) &&
    typeof record.report_version === "number" && Number.isInteger(record.report_version) &&
    typeof record.template_version_id === "string" &&
    typeof record.template_version_label === "string" &&
    ["review_draft", "final_candidate", "issued"].includes(String(record.delivery_level))
  );
}

export interface AttachmentGenerationItem {
  id: string;
  template_file_id: string;
  document_code: string;
  display_name: string;
  source_file_name?: string;
  output_file_name?: string;
  status: AttachmentJobStatus | string;
  stage: string;
  attempt_count: number;
  error_code?: string | null;
  error_summary?: string | null;
}

export interface GeneratedArtifact {
  id: string;
  document_code: string;
  display_name: string;
  file_name: string;
  extension: string;
  content_type: string;
  file_size: number;
  sha256: string;
  status: "internal" | "validated" | "published" | "rejected" | string;
  delivery_approved: boolean;
  preview_available: boolean;
  quality_status?: "passed" | "failed" | "pending" | string;
  quality_summary?: string | null;
  created_at?: string | null;
}

export interface AttachmentJobProgress {
  percent: number;
  completed: number;
  total: number;
  failed: number;
}

export interface AttachmentJobDetail extends AttachmentJobRef {
  status: AttachmentJobStatus;
  stage: string;
  progress: AttachmentJobProgress;
  expected_item_count: number;
  succeeded_item_count: number;
  items: AttachmentGenerationItem[];
  artifacts: GeneratedArtifact[];
  retryable: boolean;
  error_code?: string | null;
  error_summary?: string | null;
  successor_job_id?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface AttachmentJobListResponse {
  items: AttachmentJobDetail[];
  total: number;
  limit: number;
}

export interface CreateAttachmentJobRequest {
  report_id: number;
  generation_scope: "all_active_template_files";
  delivery_level: AttachmentDeliveryLevel;
  idempotency_key: string;
}

export interface ArtifactAccessTicket {
  url: string;
  expires_at: string;
  content_type: string;
  file_name: string;
}

type AttachmentJobWire = Record<string, unknown>;

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function normalizeJobRef(wire: AttachmentJobWire, fallbackCaseId: number): AttachmentJobRef {
  const embedded = wire.attachment_job;
  if (isAttachmentJobRef(embedded)) return embedded;
  return {
    job_id: stringValue(wire.job_id || wire.id),
    case_id: numberValue(wire.case_id ?? wire.engagement_id, fallbackCaseId),
    assistant_turn_id: stringValue(wire.assistant_turn_id),
    report_id: numberValue(wire.report_id),
    report_version: numberValue(wire.report_version),
    template_version_id: stringValue(wire.template_version_id),
    template_version_label: stringValue(wire.template_version_label),
    delivery_level: stringValue(wire.delivery_level, "review_draft") as AttachmentDeliveryLevel,
  };
}

function normalizeItem(value: unknown): AttachmentGenerationItem {
  const item = (value && typeof value === "object" ? value : {}) as AttachmentJobWire;
  return {
    id: stringValue(item.id),
    template_file_id: stringValue(item.template_file_id),
    document_code: stringValue(item.document_code),
    display_name: stringValue(item.display_name, stringValue(item.document_code)),
    source_file_name: stringValue(item.source_file_name) || undefined,
    output_file_name: stringValue(item.output_file_name) || undefined,
    status: stringValue(item.status, "queued"),
    stage: stringValue(item.stage, stringValue(item.status, "queued")),
    attempt_count: numberValue(item.attempt_count),
    error_code: stringValue(item.error_code) || null,
    error_summary: stringValue(item.error_summary) || null,
  };
}

function normalizeArtifact(value: unknown): GeneratedArtifact {
  const artifact = (value && typeof value === "object" ? value : {}) as AttachmentJobWire;
  const status = stringValue(artifact.status, "internal");
  const approved = artifact.delivery_approved === true;
  return {
    id: stringValue(artifact.id),
    document_code: stringValue(artifact.document_code),
    display_name: stringValue(artifact.display_name, stringValue(artifact.document_code)),
    file_name: stringValue(artifact.file_name),
    extension: stringValue(artifact.extension),
    content_type: stringValue(artifact.content_type, "application/octet-stream"),
    file_size: numberValue(artifact.file_size),
    sha256: stringValue(artifact.sha256),
    status,
    delivery_approved: approved,
    preview_available:
      typeof artifact.preview_available === "boolean"
        ? artifact.preview_available
        : stringValue(artifact.preview_sha256).length > 0,
    quality_status:
      stringValue(artifact.quality_status) ||
      (approved ? "passed" : status === "rejected" ? "failed" : "pending"),
    quality_summary: stringValue(artifact.quality_summary) || null,
    created_at: stringValue(artifact.created_at) || null,
  };
}

export function normalizeAttachmentJob(
  value: unknown,
  fallbackCaseId: number
): AttachmentJobDetail {
  const wire = (value && typeof value === "object" ? value : {}) as AttachmentJobWire;
  const items = Array.isArray(wire.items) ? wire.items.map(normalizeItem) : [];
  const artifacts = Array.isArray(wire.artifacts) ? wire.artifacts.map(normalizeArtifact) : [];
  const expected = numberValue(wire.expected_item_count, items.length);
  const failed = items.filter((item) => item.status === "failed").length;
  const completed = items.filter((item) =>
    ["succeeded", "completed", "failed", "cancelled"].includes(item.status)
  ).length;
  const rawProgress = wire.progress;
  const progressRecord =
    rawProgress && typeof rawProgress === "object"
      ? (rawProgress as AttachmentJobWire)
      : null;
  const progress: AttachmentJobProgress = {
    percent: progressRecord
      ? numberValue(progressRecord.percent)
      : numberValue(rawProgress),
    completed: progressRecord
      ? numberValue(progressRecord.completed, completed)
      : completed,
    total: progressRecord ? numberValue(progressRecord.total, expected) : expected,
    failed: progressRecord ? numberValue(progressRecord.failed, failed) : failed,
  };
  return {
    ...normalizeJobRef(wire, fallbackCaseId),
    status: stringValue(wire.status, "queued") as AttachmentJobStatus,
    stage: stringValue(wire.stage, stringValue(wire.status, "queued")),
    progress,
    expected_item_count: expected,
    succeeded_item_count: numberValue(wire.succeeded_item_count),
    items,
    artifacts,
    retryable: wire.retryable === true,
    error_code: stringValue(wire.error_code) || null,
    error_summary: stringValue(wire.error_summary) || null,
    successor_job_id: stringValue(wire.successor_job_id) || null,
    created_at: stringValue(wire.created_at ?? wire.queued_at) || null,
    started_at: stringValue(wire.started_at) || null,
    completed_at: stringValue(wire.completed_at) || null,
  };
}

export function resolveArtifactTicketUrl(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  return casesUrl(url.startsWith("/") ? url : `/${url}`);
}

function attachmentJobsBase(caseId: number): string {
  return casesUrl(`/api/annual-audit/${caseId}/attachment-jobs`);
}

export function attachmentJobKey(caseId: number, jobId: string): string {
  return `${attachmentJobsBase(caseId)}/${encodeURIComponent(jobId)}`;
}

export function isTerminalAttachmentJobStatus(status?: string): boolean {
  return TERMINAL_ATTACHMENT_JOB_STATUSES.has(status as AttachmentJobStatus);
}

export async function createAttachmentJob(
  caseId: number,
  request: CreateAttachmentJobRequest
): Promise<AttachmentJobDetail> {
  const response = await postJson<unknown>(
    attachmentJobsBase(caseId),
    request,
    "创建附件生成任务失败"
  );
  return normalizeAttachmentJob(response, caseId);
}

export async function getAttachmentJob(
  caseId: number,
  jobId: string
): Promise<AttachmentJobDetail> {
  const response = await getJson<unknown>(
    attachmentJobKey(caseId, jobId),
    "获取附件生成任务失败"
  );
  return normalizeAttachmentJob(response, caseId);
}

export async function listAttachmentJobs(
  caseId: number,
  params: { limit?: number } = {}
): Promise<AttachmentJobListResponse> {
  const limit = params.limit ?? 50;
  const query = new URLSearchParams({
    limit: String(limit),
  });
  const response = await getJson<{ jobs?: unknown[] }>(
    `${attachmentJobsBase(caseId)}?${query}`,
    "获取项目附件历史失败"
  );
  const items = (response.jobs ?? []).map((job) => normalizeAttachmentJob(job, caseId));
  return { items, total: items.length, limit };
}

export async function retryAttachmentJob(
  caseId: number,
  jobId: string
): Promise<AttachmentJobDetail> {
  const response = await postWithoutBody<unknown>(
    `${attachmentJobKey(caseId, jobId)}/retry`,
    "重试附件生成任务失败"
  );
  return normalizeAttachmentJob(response, caseId);
}

export async function cancelAttachmentJob(
  caseId: number,
  jobId: string
): Promise<AttachmentJobDetail> {
  const response = await postWithoutBody<unknown>(
    `${attachmentJobKey(caseId, jobId)}/cancel`,
    "取消附件生成任务失败"
  );
  return normalizeAttachmentJob(response, caseId);
}

function artifactBase(caseId: number, artifactId: string): string {
  return casesUrl(
    `/api/annual-audit/${caseId}/artifacts/${encodeURIComponent(artifactId)}`
  );
}

export async function getArtifactDownloadTicket(
  caseId: number,
  artifactId: string
): Promise<ArtifactAccessTicket> {
  const ticket = await getJson<ArtifactAccessTicket>(
    `${artifactBase(caseId, artifactId)}/download-ticket`,
    "获取附件下载票据失败"
  );
  return { ...ticket, url: resolveArtifactTicketUrl(ticket.url) };
}

export async function getArtifactPreviewTicket(
  caseId: number,
  artifactId: string
): Promise<ArtifactAccessTicket> {
  const ticket = await getJson<ArtifactAccessTicket>(
    `${artifactBase(caseId, artifactId)}/preview-ticket`,
    "获取附件预览票据失败"
  );
  return { ...ticket, url: resolveArtifactTicketUrl(ticket.url) };
}

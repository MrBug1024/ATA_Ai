import { apiFetch, langgraphUrl } from "@/lib/api/client";
import {
  BackendError,
  getJson,
  postJson,
  postWithoutBody,
  putJson,
  postForm,
  deleteJson,
} from "./http";
import type {
  ProgressBoard,
  UpdateProgressRequest,
  ForecastListResponse,
  ForecastItem,
  ForecastSeedRequest,
  RecoveryListResponse,
  RecoveryRecord,
  CreateRecoveryRequest,
  ReviewRequest,
  ReviewResponse,
  CorrectionCreateRequest,
  CorrectionListResponse,
  CorrectionModel,
  DeadlineBoardResponse,
} from "@/lib/types/case-analytics";
import type {
  FileItem,
  ChatUploadRequest,
  ChatUploadResponse,
} from "@/lib/types/chat-upload";
import type {
  CaseMaterialEventsResp,
  CaseMaterialEventItem,
  CaseUploadBatchesResp,
  CaseUploadBatchItem,
  MaterialEventDetail,
  UploadBatchDetail,
  UploadAndIngestResponse,
  UploadRetryResponse,
  UploadRetryStage,
} from "@/lib/types/doc-categories";
import type {
  EvolutionItem,
  EvolutionItemsResponse,
  GraphEntityItem,
  GraphEntitiesResponse,
  SubgraphRequest,
  SubgraphResponse,
  RelationEvidenceRequest,
  RelationEvidenceResponse,
  ValidationRequest,
  ValidationResponse,
  EvidenceResolveRequest,
  EvidenceResolveResponse,
  PageAnchorsResponse,
  UnresolvedItemsResponse,
} from "@/lib/types/knowledge-graph";
import type {
  LangGraphThread,
  ThreadDetailResponse,
  ThreadListResponse,
  ThreadMessagesResponse,
  ThreadTurnsResponse,
} from "@/lib/types/langgraph-chat";

export type {
  LangGraphThread,
  ThreadDetailResponse,
  ThreadListResponse,
  ThreadMessage,
  ThreadMessagesResponse,
  UserTurnItem,
  AssistantTurnItem,
  TurnGroup,
  ThreadTurnsResponse,
} from "@/lib/types/langgraph-chat";

// ── Threads ──────────────────────────────────────────────────────────────────

export interface ThreadListParams {
  caseId?: number;
  limit?: number;
  offset?: number;
}

export function threadsKey(params: ThreadListParams = {}): string {
  const query = new URLSearchParams();
  if (params.caseId !== undefined) query.set("case_id", String(params.caseId));
  query.set("limit", String(params.limit ?? 50));
  query.set("offset", String(params.offset ?? 0));
  return langgraphUrl(`/chat/threads?${query}`);
}

/** Match every paginated/filtered thread-list SWR key, but not thread detail URLs. */
export function isThreadsListKey(key: unknown): key is string {
  return typeof key === "string" && key.startsWith(langgraphUrl("/chat/threads?"));
}

export async function listThreads(params: ThreadListParams = {}): Promise<ThreadListResponse> {
  return getJson<ThreadListResponse>(threadsKey(params), "获取会话列表失败");
}

export function threadDetailKey(threadId: string): string {
  return langgraphUrl(`/chat/threads/${encodeURIComponent(threadId)}`);
}

export async function getThreadDetail(threadId: string): Promise<ThreadDetailResponse> {
  return getJson<ThreadDetailResponse>(threadDetailKey(threadId), "获取会话详情失败");
}

export function threadMessagesKey(threadId: string): string {
  return langgraphUrl(`/chat/threads/${encodeURIComponent(threadId)}/messages`);
}

export async function getThreadMessages(threadId: string): Promise<ThreadMessagesResponse> {
  return getJson<ThreadMessagesResponse>(
    threadMessagesKey(threadId),
    "获取会话消息失败"
  );
}

export function threadTurnsKey(threadId: string): string {
  return langgraphUrl(`/chat/threads/${encodeURIComponent(threadId)}/turns`);
}

export async function getThreadTurns(threadId: string): Promise<ThreadTurnsResponse> {
  return getJson<ThreadTurnsResponse>(threadTurnsKey(threadId), "获取会话轮次失败");
}

export async function deleteThread(threadId: string): Promise<void> {
  await deleteJson(threadDetailKey(threadId), "删除对话失败");
}

// ── Chat invoke (streaming) ──────────────────────────────────────────────────

export interface ChatInvokeRequest {
  threadId: string;
  query: string;
  caseId?: number;
  uploadedFiles?: FileItem[];
  clientTurnId?: string;
  regenerate?: boolean;
  selectedAssistantTurnId?: string;
}

/** 发起流式对话,返回原始 Response 供 SSE 解析;非 2xx 抛 BackendError。 */
export async function chatInvoke(req: ChatInvokeRequest, signal?: AbortSignal): Promise<Response> {
  const res = await apiFetch(langgraphUrl("/chat/invoke"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({
      thread_id: req.threadId,
      query: req.query,
      current_case_id: req.caseId ?? 0,
      current_debtor_id: 0,
      current_debtor_name: "",
      stream: true,
      uploaded_files: req.uploadedFiles ?? [],
      client_turn_id: req.clientTurnId ?? "",
      regenerate: req.regenerate ?? false,
      selected_assistant_turn_id: req.selectedAssistantTurnId ?? "",
    }),
    signal,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new BackendError(text || `LangGraph API error (${res.status})`, res.status);
  }
  return res;
}

// ── File uploads ─────────────────────────────────────────────────────────────

export async function uploadChatFiles(
  req: ChatUploadRequest,
  files: File[]
): Promise<ChatUploadResponse> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  form.append("current_case_id", String(req.caseId));
  form.append("current_debtor_id", String(req.debtorId ?? 0));
  form.append("current_debtor_name", req.debtorName ?? "");
  if (req.docCategory) form.append("doc_category", req.docCategory);
  if (req.batchName) form.append("batch_name", req.batchName);
  if (req.uploadBatchId) form.append("upload_batch_id", req.uploadBatchId);
  if (req.operatorId) form.append("operator_id", req.operatorId);
  if (req.operatorName) form.append("operator_name", req.operatorName);
  return postForm<ChatUploadResponse>(langgraphUrl("/chat/upload-files"), form, "文件上传失败");
}

export interface UploadIngestRequest {
  files: File[];
  current_case_id: number;
  doc_category: string;
  batch_name?: string;
  current_debtor_id?: number;
  current_debtor_name?: string;
  upload_batch_id?: string;
  operator_id?: string;
  operator_name?: string;
}

export async function uploadAndIngest(req: UploadIngestRequest): Promise<UploadAndIngestResponse> {
  const form = new FormData();
  for (const f of req.files) form.append("files", f);
  form.append("current_case_id", String(req.current_case_id));
  form.append("current_debtor_id", String(req.current_debtor_id ?? 0));
  form.append("current_debtor_name", req.current_debtor_name ?? "");
  form.append("doc_category", req.doc_category);
  if (req.batch_name) form.append("batch_name", req.batch_name);
  if (req.upload_batch_id) form.append("upload_batch_id", req.upload_batch_id);
  if (req.operator_id) form.append("operator_id", req.operator_id);
  if (req.operator_name) form.append("operator_name", req.operator_name);
  return postForm<UploadAndIngestResponse>(
    langgraphUrl("/files/upload-and-ingest"),
    form,
    "上传失败"
  );
}

// ── Case files ───────────────────────────────────────────────────────────────

export function caseMaterialEventsKey(caseId: number): string {
  return langgraphUrl(`/files/cases/${caseId}/material-events`);
}

export async function listCaseMaterialEvents(caseId: number): Promise<CaseMaterialEventItem[]> {
  const data = await getJson<CaseMaterialEventsResp>(
    caseMaterialEventsKey(caseId),
    "获取材料事件失败"
  );
  return data.material_events ?? [];
}

export function caseUploadBatchesKey(caseId: number): string {
  return langgraphUrl(`/files/cases/${caseId}/upload-batches`);
}

export async function listCaseUploadBatches(caseId: number): Promise<CaseUploadBatchItem[]> {
  const data = await getJson<CaseUploadBatchesResp>(
    caseUploadBatchesKey(caseId),
    "获取上传批次失败"
  );
  return data.upload_batches ?? [];
}

export function evolutionItemsKey(
  caseId: number,
  action?: "ADD" | "OVERRIDE",
  limit = 50
): string {
  const params = new URLSearchParams({ limit: String(limit) });
  if (action) params.set("action", action);
  return langgraphUrl(`/files/cases/${caseId}/evolution-items?${params}`);
}

export async function listEvolutionItems(
  caseId: number,
  action?: "ADD" | "OVERRIDE",
  limit = 50
): Promise<EvolutionItem[]> {
  const data = await getJson<EvolutionItemsResponse>(
    evolutionItemsKey(caseId, action, limit),
    "获取演化记录失败"
  );
  return data.evolution_items ?? [];
}

export function unresolvedItemsKey(
  caseId: number,
  status: "pending" | "resolved" | "" = "pending",
  limit = 50
): string {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status) params.set("status", status);
  return langgraphUrl(`/files/cases/${caseId}/unresolved-items?${params}`);
}

export async function getUnresolvedItems(
  caseId: number,
  status: "pending" | "resolved" | "" = "pending",
  limit = 50
): Promise<UnresolvedItemsResponse> {
  return getJson<UnresolvedItemsResponse>(
    unresolvedItemsKey(caseId, status, limit),
    "获取待定项失败"
  );
}

export function materialEventKey(eventId: string): string {
  return langgraphUrl(`/files/material-events/${encodeURIComponent(eventId)}`);
}

export async function getMaterialEvent(eventId: string): Promise<MaterialEventDetail> {
  return getJson<MaterialEventDetail>(materialEventKey(eventId), "获取材料事件失败");
}

export function uploadBatchKey(batchId: string): string {
  return langgraphUrl(`/files/upload-batches/${encodeURIComponent(batchId)}`);
}

export async function getUploadBatch(batchId: string): Promise<UploadBatchDetail> {
  return getJson<UploadBatchDetail>(uploadBatchKey(batchId), "获取上传批次失败");
}

export function uploadBatchRetryUrl(
  batchId: string,
  stage: UploadRetryStage = "auto"
): string {
  const query = new URLSearchParams({ stage });
  return langgraphUrl(
    `/files/upload-batches/${encodeURIComponent(batchId)}/retry?${query}`
  );
}

export async function retryUploadBatch(
  batchId: string,
  stage: UploadRetryStage = "auto"
): Promise<UploadRetryResponse> {
  return postWithoutBody<UploadRetryResponse>(
    uploadBatchRetryUrl(batchId, stage),
    "重试上传任务失败"
  );
}

export function pageAnchorsKey(fileId: number, pageNo: number, chunkId?: string): string {
  const params = new URLSearchParams();
  params.set("file_id", String(fileId));
  params.set("page_no", String(pageNo));
  if (chunkId) params.set("chunk_id", chunkId);
  return langgraphUrl(`/files/page-anchors?${params}`);
}

export async function getPageAnchors(
  fileId: number,
  pageNo: number,
  chunkId?: string
): Promise<PageAnchorsResponse> {
  return getJson<PageAnchorsResponse>(pageAnchorsKey(fileId, pageNo, chunkId), "获取页锚点失败");
}

// ── Knowledge graph / evidence ───────────────────────────────────────────────

export function graphEntitiesKey(caseId: number): string {
  return langgraphUrl(`/graph/cases/${caseId}/entities`);
}

export async function listGraphEntities(caseId: number): Promise<GraphEntityItem[]> {
  const data = await getJson<GraphEntitiesResponse>(graphEntitiesKey(caseId), "获取图谱实体失败");
  return data.entities ?? [];
}

export async function fetchSubgraph(req: SubgraphRequest): Promise<SubgraphResponse> {
  return postJson<SubgraphResponse>(langgraphUrl("/graph/subgraph"), req, "获取子图失败");
}

export async function fetchRelationEvidence(
  req: RelationEvidenceRequest
): Promise<RelationEvidenceResponse> {
  return postJson<RelationEvidenceResponse>(
    langgraphUrl("/graph/relation-evidence"),
    req,
    "获取关系证据失败"
  );
}

export async function validateDemoCaseTrace(req: ValidationRequest): Promise<ValidationResponse> {
  return postJson<ValidationResponse>(
    langgraphUrl("/graph/demo-case-trace/validate"),
    req,
    "校验失败"
  );
}

export async function resolveEvidence(req: EvidenceResolveRequest): Promise<EvidenceResolveResponse> {
  return postJson<EvidenceResolveResponse>(langgraphUrl("/evidence/resolve"), req, "解析证据失败");
}

// ── Case analytics(进度 / 预测 / 回款 / 复盘,均在 LangGraph 8081) ──────────────
// 注意:路径以 /cases 开头但属于 LangGraph 后端,故用 langgraphUrl(),勿放进 cases.ts(8080)。

export function caseProgressKey(caseId: number): string {
  return langgraphUrl(`/cases/${caseId}/progress`);
}

export async function getCaseProgress(caseId: number): Promise<ProgressBoard> {
  return getJson<ProgressBoard>(caseProgressKey(caseId), "获取案件进度失败");
}

export async function updateCaseProgress(
  caseId: number,
  req: UpdateProgressRequest
): Promise<void> {
  await putJson<unknown>(caseProgressKey(caseId), req, "更新案件进度失败");
}

export function caseForecastKey(caseId: number): string {
  return langgraphUrl(`/cases/${caseId}/forecast`);
}

export async function listCaseForecasts(caseId: number): Promise<ForecastItem[]> {
  const data = await getJson<ForecastListResponse>(caseForecastKey(caseId), "获取预期回款失败");
  return data.forecasts ?? [];
}

export async function seedCaseForecast(
  caseId: number,
  req: ForecastSeedRequest
): Promise<void> {
  await postJson<unknown>(caseForecastKey(caseId), req, "写入预期回款失败");
}

export function caseRecoveryKey(caseId: number): string {
  return langgraphUrl(`/cases/${caseId}/recovery`);
}

export async function listCaseRecovery(caseId: number): Promise<RecoveryRecord[]> {
  const data = await getJson<RecoveryListResponse>(caseRecoveryKey(caseId), "获取回款明细失败");
  return data.records ?? [];
}

export async function createRecovery(
  caseId: number,
  req: CreateRecoveryRequest
): Promise<RecoveryRecord> {
  return postJson<RecoveryRecord>(caseRecoveryKey(caseId), req, "记录回款失败");
}

export async function confirmRecovery(
  caseId: number,
  recordId: number
): Promise<RecoveryRecord> {
  return postWithoutBody<RecoveryRecord>(
    langgraphUrl(`/cases/${caseId}/recovery/${recordId}/confirm`),
    "确认回款失败"
  );
}

export async function reviewCase(caseId: number, req: ReviewRequest = {}): Promise<ReviewResponse> {
  return postJson<ReviewResponse>(
    langgraphUrl(`/cases/${caseId}/review`),
    req,
    "AI 复盘失败"
  );
}

// ── Case corrections / deadline board ────────────────────────────────────────

export function caseCorrectionsKey(caseId: number, includeHistory = false): string {
  const suffix = includeHistory ? "?include_history=true" : "";
  return langgraphUrl(`/cases/${caseId}/corrections${suffix}`);
}

export async function listCaseCorrections(
  caseId: number,
  includeHistory = false
): Promise<CorrectionModel[]> {
  const data = await getJson<CorrectionListResponse>(
    caseCorrectionsKey(caseId, includeHistory),
    "获取案件订正失败"
  );
  return data.corrections ?? [];
}

export async function createCorrection(
  caseId: number,
  req: CorrectionCreateRequest
): Promise<CorrectionModel> {
  return postJson<CorrectionModel>(
    caseCorrectionsKey(caseId),
    req,
    "新增案件订正失败"
  );
}

export async function revokeCorrection(
  caseId: number,
  correctionId: number
): Promise<CorrectionModel> {
  return postWithoutBody<CorrectionModel>(
    langgraphUrl(`/cases/${caseId}/corrections/${correctionId}/revoke`),
    "撤销案件订正失败"
  );
}

export function caseDeadlineBoardKey(caseId: number): string {
  return langgraphUrl(`/cases/${caseId}/deadline-board`);
}

export async function getCaseDeadlineBoard(caseId: number): Promise<DeadlineBoardResponse> {
  return getJson<DeadlineBoardResponse>(caseDeadlineBoardKey(caseId), "获取司法时效看板失败");
}

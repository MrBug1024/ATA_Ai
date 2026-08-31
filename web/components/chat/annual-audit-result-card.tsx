"use client";

import { useEffect, useRef, useState } from "react";
import { useAui } from "@assistant-ui/react";
import {
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  Download,
  Eye,
  FileArchive,
  LoaderCircle,
  MessageCircleQuestion,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiFetch, casesUrl } from "@/lib/api/client";
import {
  annualAttachmentJobStatusPath,
  annualAttachmentStatus,
  getAnnualAttachmentJob,
  isAnnualAttachmentTerminalStatus,
  mergeAnnualAttachmentJobResponse,
  retryAnnualAttachmentJob,
  type AnnualAttachmentArtifact,
  type AnnualAttachmentJobItem,
  type AnnualAttachmentPackage,
} from "@/lib/backend/annual-audit-attachments";
import { BackendError } from "@/lib/backend/http";

export type { AnnualAttachmentPackage } from "@/lib/backend/annual-audit-attachments";

interface AttachmentPreview {
  kind: "document" | "workbook" | "text" | "pdf" | "unsupported";
  file_name?: string;
  message?: string;
  paragraphs?: string[];
  tables?: string[][][];
  sheets?: Array<{ name: string; rows: string[][] }>;
  text?: string;
  page_count?: number;
  truncated?: boolean;
}

const POLL_INTERVAL_MS = 2_000;
const MAX_TRANSIENT_POLL_RETRIES = 3;

interface StageAction {
  label: string;
  composerText: string;
  behavior: "send" | "draft";
}

const REVIEW_ISSUE_DRAFT = "我认为上述审计结果可能有问题。请先只读复核当前审计结果、证据引用和附件状态，不要重新执行审计。具体问题：";

const stageActions: Record<string, StageAction[]> = {
  awaiting_result_review: [
    { label: "没有问题", composerText: "没有问题", behavior: "send" },
    { label: "有问题", composerText: REVIEW_ISSUE_DRAFT, behavior: "draft" },
  ],
  awaiting_artifact_confirmation: [
    { label: "确认生成附件", composerText: "确认生成附件", behavior: "send" },
    { label: "暂不生成", composerText: "暂不生成", behavior: "send" },
  ],
  awaiting_attachment_generation_confirmation: [
    { label: "确认生成附件", composerText: "确认生成附件", behavior: "send" },
    { label: "暂不生成", composerText: "暂不生成", behavior: "send" },
  ],
  attachments_generating: [],
  attachments_generated: [
    { label: "生成工作底稿", composerText: "生成工作底稿", behavior: "send" },
    { label: "生成函证", composerText: "生成函证", behavior: "send" },
  ],
};

function stageLabel(stage: string): string {
  if (stage === "awaiting_result_review") return "请确认审计结果";
  if (stage === "awaiting_artifact_confirmation") return "是否生成附件";
  if (stage === "awaiting_attachment_generation_confirmation") {
    return "附件生成检查已通过，是否开始生成";
  }
  if (stage === "attachments_generating") return "附件正在后台生成";
  if (stage === "attachments_generated") {
    return "附件已生成，可重新生成或补充过程资料";
  }
  return "";
}

function attachmentStatusLabel(status?: string): string {
  switch (String(status || "").trim().toLowerCase()) {
    case "queued":
      return "等待生成";
    case "planning":
      return "准备生成";
    case "running":
    case "generating":
      return "正在生成";
    case "succeeded":
    case "completed":
    case "draft_saved":
      return "已生成，等待复核";
    case "partial":
      return "部分完成";
    case "failed":
      return "生成失败";
    case "cancelled":
      return "已取消";
    default:
      return "状态更新中";
  }
}

function itemStatusLabel(status?: string): string {
  switch (String(status || "").trim().toLowerCase()) {
    case "queued":
      return "等待生成";
    case "planning":
      return "准备材料";
    case "running":
    case "generating":
      return "正在编制";
    case "succeeded":
    case "completed":
    case "draft_saved":
      return "已完成";
    case "failed":
      return "失败";
    case "cancelled":
      return "已取消";
    default:
      return "等待更新";
  }
}

function readableMessage(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const message = value.trim();
  if (
    !message
    || /^[\[{]/.test(message)
    || /^<!doctype\s/i.test(message)
    || /traceback|stack trace/i.test(message)
  ) {
    return undefined;
  }
  return message.slice(0, 300);
}

function readableErrors(value: unknown): string[] {
  const values = Array.isArray(value) ? value : [value];
  return values
    .map(readableMessage)
    .filter((message): message is string => Boolean(message));
}

function artifactQualityIssues(artifact: AnnualAttachmentArtifact): string[] {
  const quality = artifact.quality_validation;
  if (!quality || typeof quality !== "object" || Array.isArray(quality)) return [];
  const blockers = (quality as { blockers?: unknown }).blockers;
  if (!Array.isArray(blockers)) return [];
  return blockers
    .filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
    .map((item) => item.trim());
}

function deliveryRejectionReason(artifact: AnnualAttachmentArtifact): string | undefined {
  if (artifact.delivery_approved === true) return undefined;
  const serverReason = readableMessage(artifact.delivery_rejection_reason);
  if (serverReason) return serverReason;
  if (String(artifact.delivery_readiness || "").toLowerCase() !== "ready") {
    return "附件未达到交付就绪状态";
  }
  const quality = artifact.quality_validation;
  if (!quality || typeof quality !== "object" || Array.isArray(quality)) {
    return "缺少质量校验记录";
  }
  if ((quality as { passed?: unknown }).passed !== true) {
    const blockers = artifactQualityIssues(artifact);
    return blockers.length ? `质量校验未通过：${blockers[0]}` : "质量校验未通过";
  }
  return "缺少经验证的冻结生成计划或模板交付合同";
}

function nonNegativeInteger(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, Math.trunc(value))
    : fallback;
}

function isCompletedItem(status?: string): boolean {
  return ["succeeded", "completed", "draft_saved", "failed", "cancelled"].includes(
    String(status || "").trim().toLowerCase(),
  );
}

function isSuccessfulStatus(status?: string): boolean {
  return ["succeeded", "completed", "draft_saved"].includes(
    String(status || "").trim().toLowerCase(),
  );
}

function isAbortError(error: unknown): boolean {
  return Boolean(
    error
    && typeof error === "object"
    && "name" in error
    && (error as { name?: unknown }).name === "AbortError",
  );
}

function isPermanentPollError(error: unknown): boolean {
  if (
    error
    && typeof error === "object"
    && "name" in error
    && (error as { name?: unknown }).name === "UnauthorizedError"
  ) {
    return true;
  }
  if (!(error instanceof BackendError)) return false;
  return error.status >= 400
    && error.status < 500
    && ![408, 425, 429].includes(error.status);
}

function attachmentRetryIdempotencyKey(caseId: number, jobId: number): string {
  const randomPart = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `attachment-retry:${caseId}:${jobId}:${randomPart}`.slice(0, 128);
}

function itemStatusIcon(status?: string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (["running", "generating", "planning"].includes(normalized)) {
    return <LoaderCircle className="size-3.5 animate-spin text-primary" aria-hidden="true" />;
  }
  if (["succeeded", "completed", "draft_saved"].includes(normalized)) {
    return <CheckCircle2 className="size-3.5 text-emerald-600" aria-hidden="true" />;
  }
  if (normalized === "failed") {
    return <XCircle className="size-3.5 text-destructive" aria-hidden="true" />;
  }
  if (normalized === "cancelled") {
    return <CircleAlert className="size-3.5 text-muted-foreground" aria-hidden="true" />;
  }
  return <CircleDashed className="size-3.5 text-muted-foreground" aria-hidden="true" />;
}

function AttachmentJobItemRow({ item, index }: { item: AnnualAttachmentJobItem; index: number }) {
  const fileName = item.output_file_name || item.source_file_name || `附件 ${index + 1}`;
  const status = String(item.status || "queued").toLowerCase();
  const itemError = readableMessage(item.error_message);
  const attemptCount = nonNegativeInteger(item.attempt_count);
  const maxAttempts = nonNegativeInteger(item.max_attempts);

  return (
    <li className="flex min-w-0 items-start justify-between gap-3 border-t py-2 first:border-t-0">
      <div className="flex min-w-0 items-start gap-2">
        <span className="mt-0.5 shrink-0">{itemStatusIcon(status)}</span>
        <div className="min-w-0">
          <p className="truncate text-xs font-medium" title={fileName}>{fileName}</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {item.attachment_type || "年审附件"}
            {attemptCount > 0 && maxAttempts > 0 ? ` · 尝试 ${attemptCount}/${maxAttempts}` : ""}
          </p>
          {status === "failed" && (
            <p className="mt-1 text-[11px] text-destructive">
              {itemError || "该附件未通过生成或交付校验。"}
            </p>
          )}
        </div>
      </div>
      <span className="shrink-0 text-[11px] text-muted-foreground">
        {itemStatusLabel(status)}
      </span>
    </li>
  );
}

export function AnnualAuditResultCard({
  stage,
  attachmentPackage,
  caseId,
  messageContent,
}: {
  stage?: string;
  attachmentPackage?: AnnualAttachmentPackage;
  caseId?: number | null;
  messageContent?: string;
}) {
  const aui = useAui();
  const [downloading, setDownloading] = useState<string>("");
  const [previewing, setPreviewing] = useState<string>("");
  const [preview, setPreview] = useState<AttachmentPreview | null>(null);
  const [recoveredPackage, setRecoveredPackage] = useState<AnnualAttachmentPackage>();
  const [livePackageState, setLivePackageState] = useState<{
    originKey: string;
    value: AnnualAttachmentPackage;
  }>();
  const [pollErrorState, setPollErrorState] = useState<{
    key: string;
    message: string;
    stopped: boolean;
  }>();
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState("");
  const attachmentPackageRef = useRef(attachmentPackage);
  const livePackageRef = useRef(livePackageState);
  const deliveryProjectionKeyRef = useRef("");
  attachmentPackageRef.current = attachmentPackage;
  livePackageRef.current = livePackageState;

  const initialStatusUrl = attachmentPackage?.status_url
    || (
      caseId
      && attachmentPackage?.job_id
      ? annualAttachmentJobStatusPath(caseId, attachmentPackage.job_id)
      : ""
    );
  const initialJobKey = `${caseId ?? ""}:${attachmentPackage?.job_id ?? ""}:${initialStatusUrl}`;
  const livePackage = livePackageState?.originKey === initialJobKey
    ? livePackageState.value
    : undefined;
  const hasInitialJobMetadata = Boolean(attachmentPackage?.job_id || initialStatusUrl);
  const effectivePackage = livePackage
    ?? (hasInitialJobMetadata
      ? attachmentPackage
      : recoveredPackage ?? attachmentPackage);
  const activeStatusUrl = effectivePackage?.status_url
    || (
      caseId
      && effectivePackage?.job_id
      ? annualAttachmentJobStatusPath(caseId, effectivePackage.job_id)
      : ""
    );
  const activeJobKey = `${caseId ?? ""}:${effectivePackage?.job_id ?? ""}:${activeStatusUrl}`;
  const artifacts = effectivePackage?.artifacts ?? [];
  const items = effectivePackage?.items ?? [];
  const hasPackage = Boolean(
    effectivePackage
    && (
      effectivePackage.package_id
      || effectivePackage.package_version !== undefined
      || effectivePackage.job_id
      || effectivePackage.status_url
      || effectivePackage.status
      || effectivePackage.job_status
      || effectivePackage.progress
      || items.length
      || artifacts.length
      || effectivePackage.errors?.length
    ),
  );
  const jobStatus = annualAttachmentStatus(effectivePackage);
  const jobTracked = Boolean(
    effectivePackage?.job_id
    || effectivePackage?.status_url
    || effectivePackage?.job_status
    || effectivePackage?.progress
    || items.length,
  );
  const generationActive = jobTracked && !isAnnualAttachmentTerminalStatus(jobStatus);
  const completedFromGenerating = stage === "attachments_generating"
    && isAnnualAttachmentTerminalStatus(jobStatus);
  const displayStage = completedFromGenerating ? "attachments_generated" : (stage ?? "");
  const actions = completedFromGenerating ? [] : (stageActions[displayStage] ?? []);
  const currentPollErrorState = pollErrorState?.key === activeJobKey
    ? pollErrorState
    : undefined;
  const pollingStopped = Boolean(currentPollErrorState?.stopped);
  const showGeneratingStage = !pollingStopped && (generationActive || (
    stage === "attachments_generating" && !isAnnualAttachmentTerminalStatus(jobStatus)
  ));
  const progressTotal = nonNegativeInteger(
    effectivePackage?.progress?.total,
    items.length || artifacts.length,
  );
  const itemCompletedCount = items.filter((item) => isCompletedItem(item.status)).length;
  const progressCompleted = Math.min(
    progressTotal,
    nonNegativeInteger(
      effectivePackage?.progress?.completed,
      itemCompletedCount || (!generationActive ? artifacts.length : 0),
    ),
  );
  const explicitPercent = nonNegativeInteger(effectivePackage?.progress?.percent, -1);
  const progressPercent = explicitPercent >= 0
    ? Math.min(100, explicitPercent)
    : (progressTotal ? Math.min(100, Math.round(progressCompleted * 100 / progressTotal)) : 0);
  const failedCount = Math.max(
    nonNegativeInteger(effectivePackage?.progress?.failed),
    items.filter((item) => String(item.status || "").toLowerCase() === "failed").length,
    readableErrors(effectivePackage?.errors).length,
  );
  const currentPollError = currentPollErrorState?.message ?? "";
  const canRetry = Boolean(
    caseId
    && effectivePackage?.job_id
    && isAnnualAttachmentTerminalStatus(jobStatus),
  );
  const shouldPoll = Boolean(activeStatusUrl && !isAnnualAttachmentTerminalStatus(jobStatus));
  const hasVerifiedLegacyArtifacts = Boolean(
    attachmentPackage?.artifacts?.length
    && attachmentPackage.artifacts.every(
      (artifact) => typeof artifact.delivery_approved === "boolean",
    ),
  );
  const needsDeliveryProjection = Boolean(
    caseId
    && !livePackage
    && effectivePackage?.job_id
    && activeStatusUrl
    && isAnnualAttachmentTerminalStatus(jobStatus)
    && artifacts.some((artifact) => typeof artifact.delivery_approved !== "boolean"),
  );

  useEffect(() => {
    if (!shouldPoll) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let requestController: AbortController | undefined;
    let transientFailures = 0;

    const scheduleNext = (delay = POLL_INTERVAL_MS) => {
      if (!cancelled) {
        timer = setTimeout(() => {
          timer = undefined;
          void poll();
        }, delay);
      }
    };

    const poll = async () => {
      requestController = new AbortController();
      try {
        const payload = await getAnnualAttachmentJob(activeStatusUrl, requestController.signal);
        if (cancelled) return;
        const current = livePackageRef.current?.originKey === initialJobKey
          ? livePackageRef.current.value
          : undefined;
        const merged = mergeAnnualAttachmentJobResponse(
          payload,
          current,
          current ? undefined : attachmentPackageRef.current,
        );
        const nextState = { originKey: initialJobKey, value: merged };
        livePackageRef.current = nextState;
        setLivePackageState(nextState);
        setPollErrorState((existing) => existing?.key === activeJobKey ? undefined : existing);
        transientFailures = 0;

        if (!isAnnualAttachmentTerminalStatus(annualAttachmentStatus(merged))) {
          scheduleNext();
        }
      } catch (error) {
        if (cancelled || isAbortError(error)) return;
        const statusText = error instanceof BackendError ? `（${error.status}）` : "";
        if (isPermanentPollError(error)) {
          setPollErrorState({
            key: activeJobKey,
            message: `无法继续获取附件生成进度${statusText}，请确认您仍有该项目的访问权限。`,
            stopped: true,
          });
          return;
        }

        transientFailures += 1;
        if (transientFailures > MAX_TRANSIENT_POLL_RETRIES) {
          setPollErrorState({
            key: activeJobKey,
            message: `多次获取附件生成进度失败${statusText}，已停止自动重试，请刷新页面后重试。`,
            stopped: true,
          });
          return;
        }
        setPollErrorState({
          key: activeJobKey,
          message: `暂时无法获取附件生成进度${statusText}，将自动重试。`,
          stopped: false,
        });
        scheduleNext(POLL_INTERVAL_MS * 2 ** (transientFailures - 1));
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      requestController?.abort();
    };
  }, [
    activeJobKey,
    activeStatusUrl,
    initialJobKey,
    shouldPoll,
  ]);

  useEffect(() => {
    if (!needsDeliveryProjection || deliveryProjectionKeyRef.current === activeJobKey) {
      return;
    }
    deliveryProjectionKeyRef.current = activeJobKey;
    let cancelled = false;
    void getAnnualAttachmentJob(activeStatusUrl)
      .then((payload) => {
        if (cancelled) return;
        const current = livePackageRef.current?.originKey === initialJobKey
          ? livePackageRef.current.value
          : undefined;
        const merged = mergeAnnualAttachmentJobResponse(
          payload,
          current,
          current ? undefined : attachmentPackageRef.current,
        );
        const nextState = { originKey: initialJobKey, value: merged };
        livePackageRef.current = nextState;
        setLivePackageState(nextState);
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [
    activeJobKey,
    activeStatusUrl,
    initialJobKey,
    needsDeliveryProjection,
  ]);

  useEffect(() => {
    if (
      hasInitialJobMetadata
      || hasVerifiedLegacyArtifacts
      || !caseId
      || !messageContent
    ) {
      return;
    }
    const version = /附件包\s*v(\d+)/.exec(messageContent)?.[1];
    if (!version) return;
    let cancelled = false;
    void apiFetch(casesUrl(`/api/annual-audit/${caseId}/artifacts`))
      .then(async (response) => {
        if (!response.ok) return;
        const payload = await response.json() as {
          attachment_packages?: Array<{
            id?: number;
            package_version?: number;
            status?: string;
            artifact_refs?: AnnualAttachmentArtifact[];
            errors?: unknown[];
          }>;
        };
        const packageItem = (payload.attachment_packages ?? []).find(
          (item) => item.package_version === Number(version),
        );
        if (!cancelled && packageItem?.artifact_refs?.length) {
          setRecoveredPackage({
            package_id: packageItem.id,
            package_version: packageItem.package_version,
            status: packageItem.status,
            artifacts: packageItem.artifact_refs,
            errors: packageItem.errors,
          });
        }
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [
    caseId,
    hasVerifiedLegacyArtifacts,
    hasInitialJobMetadata,
    messageContent,
  ]);

  useEffect(() => {
    setRetryError("");
    setRetrying(false);
  }, [initialJobKey]);

  async function retryAttachments() {
    if (!caseId || !effectivePackage?.job_id || retrying) return;
    const sourceJobId = effectivePackage.job_id;
    try {
      setRetrying(true);
      setRetryError("");
      const payload = await retryAnnualAttachmentJob(
        caseId,
        sourceJobId,
        attachmentRetryIdempotencyKey(caseId, sourceJobId),
      );
      const successor = mergeAnnualAttachmentJobResponse(payload);
      if (!successor.job_id) {
        throw new Error("服务器未返回新的附件任务");
      }
      const nextState = { originKey: initialJobKey, value: successor };
      livePackageRef.current = nextState;
      setLivePackageState(nextState);
      setPollErrorState(undefined);
    } catch (error) {
      const message = error instanceof Error
        ? readableMessage(error.message)
        : undefined;
      setRetryError(message ?? "重新生成附件失败，请稍后重试。");
    } finally {
      setRetrying(false);
    }
  }

  async function download(artifact: AnnualAttachmentArtifact, actionKey: string) {
    if (artifact.delivery_approved !== true) return;
    const url = artifact.download_url;
    if (!url) return;
    const fileName = artifact.file_name || "annual-audit-attachment";
    try {
      setDownloading(actionKey);
      const response = await apiFetch(casesUrl(url));
      if (!response.ok) throw new Error(`下载失败（${response.status}）`);
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = fileName;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "附件下载失败");
    } finally {
      setDownloading("");
    }
  }

  async function previewArtifact(artifact: AnnualAttachmentArtifact, actionKey: string) {
    if (artifact.delivery_approved !== true) return;
    const url = artifact.preview_url;
    if (!url) return;
    try {
      setPreviewing(actionKey);
      const response = await apiFetch(casesUrl(url));
      if (!response.ok) throw new Error(`预览失败（${response.status}）`);
      setPreview((await response.json()) as AttachmentPreview);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "附件预览失败");
    } finally {
      setPreviewing("");
    }
  }

  const stageText = pollingStopped
    ? "附件进度暂不可用"
    : (jobStatus === "partial"
      ? "附件部分生成完成"
      : (["failed", "cancelled"].includes(jobStatus)
        ? "附件生成未完成"
        : stageLabel(showGeneratingStage ? "attachments_generating" : displayStage)));
  const showStageRow = Boolean(
    stageText || actions.length || showGeneratingStage || canRetry || retryError,
  );

  if (!showStageRow && !hasPackage) return null;

  return (
    <div className="mt-3 rounded-lg border border-primary/20 bg-primary/5 p-3" data-testid="annual-audit-result-card">
      {showStageRow && (
        <div className="flex flex-wrap items-center gap-2">
          {showGeneratingStage
            ? <LoaderCircle className="size-4 animate-spin text-primary" aria-hidden="true" />
            : (["failed", "cancelled", "partial"].includes(jobStatus)
              ? <CircleAlert className="size-4 text-amber-600" aria-hidden="true" />
              : <MessageCircleQuestion className="size-4 text-primary" aria-hidden="true" />)}
          <span className="mr-1 text-sm font-medium">{stageText}</span>
          {canRetry && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-label="重新生成附件"
              disabled={retrying}
              onClick={() => void retryAttachments()}
            >
              {retrying ? "正在重新生成" : "重新生成附件"}
            </Button>
          )}
          {actions.map((action) => (
            <Button
              key={action.label}
              type="button"
              size="sm"
              variant="outline"
              aria-label={action.behavior === "draft" ? `${action.label}，填写反馈` : action.label}
              onClick={() => {
                try {
                  const threadComposer = aui.threads().thread("main").composer();
                  threadComposer.setText(action.composerText);
                  if (action.behavior === "send") {
                    void threadComposer.send();
                  }
                } catch {
                  try {
                    aui.composer().setText(action.composerText);
                  } catch {
                    // The composer can be unavailable while viewing a historical branch.
                  }
                }
                if (action.behavior === "draft") {
                  document.querySelector<HTMLTextAreaElement>('textarea[aria-label="消息输入"]')?.focus();
                }
              }}
            >
              {action.label}
            </Button>
          ))}
        </div>
      )}

      {hasPackage && (
        <div className={`${showStageRow ? "mt-3 " : ""}space-y-3`} data-testid="annual-audit-attachments">
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm">
            <div className="flex min-w-0 items-center gap-2 font-medium">
              <FileArchive className="size-4 shrink-0" aria-hidden="true" />
              <span className="truncate">附件包 v{effectivePackage?.package_version ?? "-"}</span>
              {effectivePackage?.job_id ? (
                <span className="shrink-0 text-xs font-normal text-muted-foreground">
                  任务 #{effectivePackage.job_id}
                </span>
              ) : null}
            </div>
            <span className="shrink-0 text-xs text-muted-foreground" aria-live="polite">
              {attachmentStatusLabel(jobStatus || effectivePackage?.status)}
            </span>
          </div>

          {jobTracked && progressTotal > 0 && (
            <div className="space-y-1.5" aria-label={`附件生成进度 ${progressCompleted}/${progressTotal}`}>
              <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                <span>已完成 {progressCompleted}/{progressTotal}</span>
                <span>{progressPercent}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full bg-primary transition-[width] duration-300"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            </div>
          )}

          {jobTracked && progressTotal === 0 && generationActive && (
            <p className="text-xs text-muted-foreground">任务已排队，正在拆分附件生成步骤。</p>
          )}

          {currentPollError && generationActive && (
            <div className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-300" role="status">
              <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
              <span>{currentPollError}</span>
            </div>
          )}

          {retryError && (
            <div className="flex items-start gap-2 text-xs text-destructive" role="alert">
              <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
              <span>{retryError}</span>
            </div>
          )}

          {items.length > 0 && (
            <ol className="border-y" aria-label="附件生成明细">
              {items.map((item, index) => (
                <AttachmentJobItemRow
                  key={item.item_id ?? `${item.source_file_name || item.attachment_type}-${index}`}
                  item={item}
                  index={index}
                />
              ))}
            </ol>
          )}

          {(jobStatus === "failed" || jobStatus === "cancelled") && (
            <div className="flex items-start gap-2 text-xs text-destructive" role="alert">
              <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
              <span>
                {readableMessage(effectivePackage?.error_message)
                  ?? readableErrors(effectivePackage?.errors)[0]
                  ?? (jobStatus === "cancelled"
                    ? "附件生成任务已取消。"
                    : "附件生成未完成，请重新发起生成任务。")}
                {effectivePackage?.retryable ? " 该任务可以重新生成。" : ""}
              </span>
            </div>
          )}

          {artifacts.length > 0 && (
            <div className="grid gap-2 sm:grid-cols-2">
              {artifacts.map((artifact, index) => {
                const fileName = artifact.file_name || `附件 ${index + 1}`;
                const actionKey = `${index}:${fileName}`;
                const deliveryRejection = deliveryRejectionReason(artifact);
                return (
                  <div
                    key={actionKey}
                    className={`flex min-w-0 items-center justify-between gap-2 rounded-lg border bg-background px-3 py-2 ${deliveryRejection ? "border-destructive/60" : ""}`}
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm" title={fileName}>{fileName}</div>
                      <div className="truncate text-xs text-muted-foreground">
                        {artifact.template_version || "模板版本未知"}
                        {artifact.output_file_ext ? ` · ${artifact.output_file_ext}` : ""}
                        {artifact.template_fill_status ? ` · ${artifact.template_fill_status}` : ""}
                      </div>
                      {artifact.result_placement && (
                        <div className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">
                          编制说明：{artifact.result_placement}
                        </div>
                      )}
                      {deliveryRejection && (
                        <div className="mt-1 flex items-start gap-1.5 text-[11px] text-destructive" role="alert">
                          <CircleAlert className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
                          <span className="line-clamp-2">
                            已拒绝交付：{deliveryRejection}
                          </span>
                        </div>
                      )}
                    </div>
                    {!deliveryRejection && (
                      <div className="flex shrink-0 items-center gap-1">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          aria-label={`预览${fileName}`}
                          disabled={!artifact.preview_url || previewing === actionKey}
                          onClick={() => void previewArtifact(artifact, actionKey)}
                        >
                          <Eye data-icon="inline-start" />预览
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          aria-label={`下载${fileName}`}
                          disabled={!artifact.download_url || downloading === actionKey}
                          onClick={() => void download(artifact, actionKey)}
                        >
                          <Download data-icon="inline-start" />下载
                        </Button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {failedCount > 0 && jobStatus !== "failed" && (
            <div className="text-xs text-amber-700 dark:text-amber-300" role="status">
              有 {failedCount} 个附件未能安全生成，其余通过校验的附件已保留。
            </div>
          )}

          {isSuccessfulStatus(jobStatus) && artifacts.length === 0 && (
            <p className="text-xs text-amber-700 dark:text-amber-300">
              任务已结束，但暂未返回可下载附件，请刷新任务状态或重新生成。
            </p>
          )}
        </div>
      )}

      <Dialog open={Boolean(preview)} onOpenChange={(open) => { if (!open) setPreview(null); }}>
        <DialogContent className="max-h-[85vh] max-w-5xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{preview?.file_name || "附件预览"}</DialogTitle>
            <DialogDescription>只读预览；正式交付前仍需项目组复核和签字。</DialogDescription>
          </DialogHeader>
          {preview?.kind === "unsupported" && <p className="text-sm text-muted-foreground">{preview.message || "该格式暂不支持在线预览，请下载查看。"}</p>}
          {preview?.kind === "pdf" && <p className="text-sm text-muted-foreground">{preview.message || `PDF 共 ${preview.page_count ?? "-"} 页。`}</p>}
          {preview?.kind === "text" && <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-lg border bg-muted/20 p-4 text-xs">{preview.text}</pre>}
          {preview?.kind === "document" && <div className="space-y-4 text-sm">
            {(preview.paragraphs || []).map((paragraph, index) => <p key={`p-${index}`}>{paragraph}</p>)}
            {(preview.tables || []).map((table, tableIndex) => <div key={`t-${tableIndex}`} className="overflow-auto rounded-lg border"><table className="min-w-full text-xs"><tbody>{table.map((row, rowIndex) => <tr key={`r-${rowIndex}`} className="border-b last:border-0">{row.map((cell, cellIndex) => <td key={`c-${cellIndex}`} className="px-2 py-1 align-top">{cell}</td>)}</tr>)}</tbody></table></div>)}
          </div>}
          {preview?.kind === "workbook" && <div className="space-y-5">{(preview.sheets || []).map((sheet) => <section key={sheet.name}><h3 className="mb-2 text-sm font-semibold">{sheet.name}</h3><div className="overflow-auto rounded-lg border"><table className="min-w-full text-xs"><tbody>{sheet.rows.map((row, rowIndex) => <tr key={rowIndex} className="border-b last:border-0">{row.map((cell, cellIndex) => <td key={cellIndex} className="whitespace-pre-wrap px-2 py-1 align-top">{cell}</td>)}</tr>)}</tbody></table></div></section>)}</div>}
          {preview?.truncated && <p className="text-xs text-muted-foreground">预览内容已截取，完整内容请下载附件。</p>}
        </DialogContent>
      </Dialog>
    </div>
  );
}

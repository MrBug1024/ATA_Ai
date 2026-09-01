"use client";

import { useState } from "react";
import {
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  Download,
  Eye,
  FileArchive,
  Loader2,
  RefreshCw,
  Square,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api/client";
import { usePreview } from "@/lib/assistant-ui/preview-context";
import { getAuthorizationHeader } from "@/lib/auth/token-store";
import {
  getArtifactDownloadTicket,
  getArtifactPreviewTicket,
  isAttachmentJobRef,
  isTerminalAttachmentJobStatus,
  type AttachmentGenerationItem,
  type AttachmentJobRef,
  type GeneratedArtifact,
} from "@/lib/backend/generated-artifacts";
import {
  useAttachmentJob,
  useCancelAttachmentJob,
  useRetryAttachmentJob,
} from "@/lib/hooks/use-attachment-job";

const STATUS_LABELS: Record<string, string> = {
  queued: "等待生成",
  running: "生成中",
  freezing_context: "冻结上下文",
  loading_template: "校验模板",
  composing: "编制内容",
  composing_payload: "编制内容",
  rendering: "渲染文件",
  validating: "质量校验",
  previewing: "生成预览",
  publishing: "发布附件",
  succeeded: "已生成，等待复核",
  failed: "生成失败",
  cancelled: "已取消",
};

const DELIVERY_LABELS: Record<string, string> = {
  review_draft: "待复核草稿",
  final_candidate: "待签字/签发",
  issued: "正式附件",
};

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function itemIcon(item: AttachmentGenerationItem) {
  if (["freezing_context", "composing", "rendering", "validating", "previewing", "running"].includes(item.status)) {
    return <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden="true" />;
  }
  if (["succeeded", "completed"].includes(item.status)) {
    return <CheckCircle2 className="size-3.5 text-emerald-600" aria-hidden="true" />;
  }
  if (item.status === "failed") return <XCircle className="size-3.5 text-destructive" aria-hidden="true" />;
  if (item.status === "cancelled") return <CircleAlert className="size-3.5 text-muted-foreground" aria-hidden="true" />;
  return <CircleDashed className="size-3.5 text-muted-foreground" aria-hidden="true" />;
}

function ArtifactRow({
  jobRef,
  artifact,
}: {
  jobRef: AttachmentJobRef;
  artifact: GeneratedArtifact;
}) {
  const { openPreview } = usePreview();
  const [busyAction, setBusyAction] = useState<"preview" | "download" | "">("");
  const approved = artifact.delivery_approved === true;

  async function preview() {
    if (!approved || !artifact.preview_available) return;
    try {
      setBusyAction("preview");
      const ticket = await getArtifactPreviewTicket(jobRef.case_id, artifact.id);
      const authorization = getAuthorizationHeader();
      openPreview({
        name: artifact.file_name,
        contentType: ticket.content_type || "application/pdf",
        previewUrl: ticket.url,
        previewUrlIsDownload: false,
        requestHeaders: authorization ? { Authorization: authorization } : undefined,
      });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "获取附件预览失败");
    } finally {
      setBusyAction("");
    }
  }

  async function download() {
    if (!approved) return;
    try {
      setBusyAction("download");
      const ticket = await getArtifactDownloadTicket(jobRef.case_id, artifact.id);
      const response = await apiFetch(ticket.url, undefined, { auth: true });
      if (!response.ok) {
        throw new Error("附件下载失败");
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      try {
        anchor.href = objectUrl;
        anchor.download = ticket.file_name || artifact.file_name;
        anchor.rel = "noopener";
        document.body.appendChild(anchor);
        anchor.click();
      } finally {
        anchor.remove();
        URL.revokeObjectURL(objectUrl);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "获取附件下载票据失败");
    } finally {
      setBusyAction("");
    }
  }

  return (
    <li className="flex min-w-0 flex-col gap-2 border-t py-3 first:border-t-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium" title={artifact.file_name}>{artifact.file_name}</span>
          <Badge variant="outline">{artifact.extension.replace(/^\./, "").toLocaleUpperCase()}</Badge>
          <Badge variant={approved ? "secondary" : "destructive"}>{approved ? "质量门禁通过" : "禁止交付"}</Badge>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>{formatBytes(artifact.file_size)}</span>
          <span>SHA {artifact.sha256.slice(0, 12)}…</span>
          {artifact.quality_status && <span>{artifact.quality_status}</span>}
        </div>
        {!approved && <p className="mt-1 text-xs text-destructive">{artifact.quality_summary || "该文件未通过完整交付门禁。"}</p>}
      </div>
      {approved && (
        <div className="flex shrink-0 gap-1">
          <Button type="button" size="sm" variant="outline" disabled={!artifact.preview_available || Boolean(busyAction)} onClick={() => void preview()}>
            {busyAction === "preview" ? <Loader2 className="animate-spin" data-icon="inline-start" /> : <Eye data-icon="inline-start" />}预览
          </Button>
          <Button type="button" size="sm" variant="ghost" disabled={Boolean(busyAction)} onClick={() => void download()}>
            {busyAction === "download" ? <Loader2 className="animate-spin" data-icon="inline-start" /> : <Download data-icon="inline-start" />}下载
          </Button>
        </div>
      )}
    </li>
  );
}

function GeneratedArtifactListInner({ initialJobRef }: { initialJobRef: AttachmentJobRef }) {
  const jobRef = initialJobRef;
  const query = useAttachmentJob(jobRef);
  const retryMutation = useRetryAttachmentJob(jobRef);
  const cancelMutation = useCancelAttachmentJob(jobRef);
  const job = query.job;
  const status = job?.status;
  const terminal = isTerminalAttachmentJobStatus(status);
  const progress = job?.progress ?? { percent: 0, completed: 0, total: 0, failed: 0 };
  const artifacts = job?.artifacts ?? [];
  const items = job?.items ?? [];
  const totalCount = job ? Math.max(job.expected_item_count, progress.total) : 0;
  const succeededCount = job?.succeeded_item_count ?? 0;

  async function retry() {
    try {
      await retryMutation.retryJob(undefined);
      toast.success("已使用同一冻结输入重新提交失败项");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "重新生成附件失败");
    }
  }

  async function cancel() {
    try {
      await cancelMutation.cancelJob(undefined);
      toast.success("附件任务已取消");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "取消附件任务失败");
    }
  }

  return (
    <div className="mt-3 overflow-hidden rounded-lg border bg-muted/15" data-testid="generated-artifact-list">
      <div className="flex flex-col gap-3 border-b px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <FileArchive className="size-4 text-muted-foreground" aria-hidden="true" />
            <span className="text-sm font-medium">年度审计附件</span>
            <Badge variant="outline">{DELIVERY_LABELS[jobRef.delivery_level] ?? jobRef.delivery_level}</Badge>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            报告 v{jobRef.report_version} · 模板 {jobRef.template_version_label} · 任务 {jobRef.job_id.slice(0, 8)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!job && !query.error && (
            <Badge variant="secondary">
              <Loader2 className="animate-spin" data-icon="inline-start" />加载状态
            </Badge>
          )}
          {!job && query.error && <Badge variant="destructive">状态不可用</Badge>}
          {job && (
            <Badge variant={job.status === "failed" ? "destructive" : terminal ? "outline" : "secondary"}>
              {STATUS_LABELS[job.status] ?? job.status}
            </Badge>
          )}
          {terminal && job?.retryable && (
            <Button type="button" size="sm" variant="outline" onClick={() => void retry()} disabled={retryMutation.isMutating}>
              {retryMutation.isMutating ? <Loader2 className="animate-spin" data-icon="inline-start" /> : <RefreshCw data-icon="inline-start" />}重新生成
            </Button>
          )}
          {job?.status === "queued" && (
            <Button type="button" size="sm" variant="ghost" onClick={() => void cancel()} disabled={cancelMutation.isMutating}>
              <Square data-icon="inline-start" />取消
            </Button>
          )}
        </div>
      </div>

      <div className="space-y-3 px-3 py-3">
        {job && (
          <p className="text-xs text-muted-foreground">
            成功 {succeededCount}/{totalCount} 个附件
          </p>
        )}

        {job && !terminal && (
          <div className="space-y-1.5" aria-label={`附件生成进度 ${progress.completed}/${progress.total}`}>
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{STATUS_LABELS[job.stage] ?? job.stage ?? STATUS_LABELS[job.status]}</span>
              <span>{Math.min(100, Math.max(0, progress.percent))}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full bg-primary transition-[width]" style={{ width: `${Math.min(100, Math.max(0, progress.percent))}%` }} />
            </div>
          </div>
        )}

        {query.error && (
          <div className="flex items-center justify-between gap-3 text-xs text-destructive" role="alert">
            <span className="flex min-w-0 items-start gap-2">
              <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
              <span>{query.error}</span>
            </span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => void query.refresh()}
              disabled={query.isValidating}
            >
              {query.isValidating ? <Loader2 className="animate-spin" data-icon="inline-start" /> : <RefreshCw data-icon="inline-start" />}
              刷新状态
            </Button>
          </div>
        )}

        {!job && !query.error && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
            <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
            正在加载附件任务状态…
          </div>
        )}

        {items.length > 0 && (
          <ol className="border-y" aria-label="附件生成明细">
            {items.map((item) => (
              <li key={item.id} className="flex items-start justify-between gap-3 border-t py-2 first:border-t-0">
                <div className="flex min-w-0 items-start gap-2">
                  <span className="mt-0.5">{itemIcon(item)}</span>
                  <div className="min-w-0">
                    <p className="truncate text-xs font-medium">{item.output_file_name || item.display_name}</p>
                    {item.error_summary && <p className="mt-0.5 text-[11px] text-destructive">{item.error_summary}</p>}
                  </div>
                </div>
                <span className="shrink-0 text-[11px] text-muted-foreground">{STATUS_LABELS[item.status] ?? item.stage ?? item.status}</span>
              </li>
            ))}
          </ol>
        )}

        {job && terminal && status !== "succeeded" && (
          <div className="flex items-start gap-2 text-xs text-destructive" role="alert">
            <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            <span>{job?.error_summary || (status === "cancelled" ? "附件任务已取消。" : "附件生成未通过完整质量门禁。")}</span>
          </div>
        )}

        {artifacts.length > 0 && (
          <ol aria-label="已生成附件">
            {artifacts.map((artifact) => <ArtifactRow key={artifact.id} jobRef={jobRef} artifact={artifact} />)}
          </ol>
        )}

        {status === "succeeded" && artifacts.length === 0 && (
          <p className="text-xs text-destructive">任务已结束，但服务端未返回可交付文件。</p>
        )}
      </div>
    </div>
  );
}

export function GeneratedArtifactList({ attachmentJob }: { attachmentJob: unknown }) {
  if (!isAttachmentJobRef(attachmentJob)) return null;
  return <GeneratedArtifactListInner initialJobRef={attachmentJob} />;
}

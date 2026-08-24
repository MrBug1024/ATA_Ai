"use client";

import { useEffect, useState } from "react";
import { useAui } from "@assistant-ui/react";
import { Download, Eye, FileArchive, MessageCircleQuestion } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { apiFetch, casesUrl } from "@/lib/api/client";

interface AttachmentArtifact {
  artifact_type?: string;
  file_name?: string;
  template_version?: string;
  template_fill_status?: string;
  download_url?: string;
  preview_url?: string;
}

export interface AnnualAttachmentPackage {
  package_version?: number;
  status?: string;
  artifacts?: AttachmentArtifact[];
  errors?: string[];
}

interface AttachmentPreview {
  kind: "document" | "workbook" | "text" | "unsupported";
  file_name?: string;
  message?: string;
  paragraphs?: string[];
  tables?: string[][][];
  sheets?: Array<{ name: string; rows: string[][] }>;
  text?: string;
  truncated?: boolean;
}

const stagePrompts: Record<string, string[]> = {
  awaiting_result_review: ["没有问题", "有问题，请继续审计："],
  awaiting_artifact_confirmation: ["确认生成附件", "暂不生成"],
};

function stageLabel(stage: string): string {
  if (stage === "awaiting_result_review") return "请先确认审计结果";
  if (stage === "awaiting_artifact_confirmation") return "是否生成附件";
  if (stage === "attachments_generated") return "附件已生成，可继续复核";
  return "";
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
  const prompts = stagePrompts[stage ?? ""] ?? [];
  const effectivePackage = (attachmentPackage?.artifacts?.length ? attachmentPackage : recoveredPackage);
  const artifacts = effectivePackage?.artifacts ?? [];

  useEffect(() => {
    if (attachmentPackage?.artifacts?.length || !caseId || !messageContent) return;
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
            artifact_refs?: AttachmentArtifact[];
            errors?: string[];
          }>;
        };
        const packageItem = (payload.attachment_packages ?? []).find(
          (item) => item.package_version === Number(version),
        );
        if (!cancelled && packageItem?.artifact_refs?.length) {
          setRecoveredPackage({
            package_version: packageItem.package_version,
            status: packageItem.status,
            artifacts: packageItem.artifact_refs,
            errors: packageItem.errors,
          });
        }
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [attachmentPackage?.artifacts?.length, caseId, messageContent]);

  async function download(artifact: AttachmentArtifact) {
    const url = artifact.download_url;
    if (!url) return;
    const fileName = artifact.file_name || "annual-audit-attachment";
    try {
      setDownloading(fileName);
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

  async function previewArtifact(artifact: AttachmentArtifact) {
    const url = artifact.preview_url;
    if (!url) return;
    const fileName = artifact.file_name || "年审附件";
    try {
      setPreviewing(fileName);
      const response = await apiFetch(casesUrl(url));
      if (!response.ok) throw new Error(`预览失败（${response.status}）`);
      setPreview((await response.json()) as AttachmentPreview);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "附件预览失败");
    } finally {
      setPreviewing("");
    }
  }

  if (!prompts.length && !artifacts.length) return null;

  return (
    <div className="mt-3 rounded-xl border border-primary/20 bg-primary/5 p-3" data-testid="annual-audit-result-card">
      {prompts.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <MessageCircleQuestion className="size-4 text-primary" aria-hidden="true" />
          <span className="mr-1 text-sm font-medium">{stageLabel(stage ?? "")}</span>
          {prompts.map((prompt) => (
            <Button key={prompt} type="button" size="sm" variant="outline" onClick={() => aui.composer().setText(prompt)}>
              {prompt}
            </Button>
          ))}
        </div>
      )}

      {artifacts.length > 0 && (
        <div className="mt-3 space-y-2" data-testid="annual-audit-attachments">
          <div className="flex items-center gap-2 text-sm font-medium">
            <FileArchive className="size-4" aria-hidden="true" />
            附件包 v{effectivePackage?.package_version ?? "-"} · {effectivePackage?.status ?? "草稿"}
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {artifacts.map((artifact, index) => {
              const fileName = artifact.file_name || `附件 ${index + 1}`;
              return (
                <div key={`${fileName}-${index}`} className="flex min-w-0 items-center justify-between gap-2 rounded-lg border bg-background px-3 py-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm" title={fileName}>{fileName}</div>
                    <div className="truncate text-xs text-muted-foreground">{artifact.template_version || "模板版本未知"}{artifact.template_fill_status ? ` · ${artifact.template_fill_status}` : ""}</div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button type="button" size="sm" variant="outline" aria-label={`预览${fileName}`} disabled={!artifact.preview_url || previewing === fileName} onClick={() => void previewArtifact(artifact)}>
                      <Eye data-icon="inline-start" />预览
                    </Button>
                    <Button type="button" size="sm" variant="ghost" aria-label={`下载${fileName}`} disabled={!artifact.download_url || downloading === fileName} onClick={() => void download(artifact)}>
                      <Download data-icon="inline-start" />下载
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
          {!!effectivePackage?.errors?.length && <div className="text-xs text-amber-700 dark:text-amber-300">有 {effectivePackage.errors.length} 个文件未完成字段填充，请查看生成异常。</div>}
        </div>
      )}

      <Dialog open={Boolean(preview)} onOpenChange={(open) => { if (!open) setPreview(null); }}>
        <DialogContent className="max-h-[85vh] max-w-5xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{preview?.file_name || "附件预览"}</DialogTitle>
            <DialogDescription>只读预览；正式交付前仍需项目组复核和签字。</DialogDescription>
          </DialogHeader>
          {preview?.kind === "unsupported" && <p className="text-sm text-muted-foreground">{preview.message || "该格式暂不支持在线预览，请下载查看。"}</p>}
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

"use client";

import { useReducer, useCallback, useMemo, useRef, useEffect, useId, useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Upload,
  X,
  Loader2,
  FileText,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Case } from "@/lib/hooks/use-cases";
import { useDocCategories } from "@/lib/hooks/use-doc-categories";
import { useCaseDocCategories } from "@/lib/hooks/use-case-doc-categories";
import { useValidateDocCategory } from "@/lib/hooks/use-validate-doc-category";
import { useUploadIngest } from "@/lib/hooks/use-upload-ingest";
import { useMaterialEvent } from "@/lib/hooks/use-material-event";
import { useRetryUploadBatch } from "@/lib/hooks/use-retry-upload-batch";
import { useUploadQueue } from "@/lib/stores/upload-queue";
import type { CaseDocCategoryItem } from "@/lib/types/doc-categories";
import {
  flowReducer,
  initialFlowState,
  validationOutcome,
  uploadMaterialEventId,
  canSubmit as flowCanSubmit,
} from "@/lib/upload/add-material-flow";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  caseItem: Case;
}

export function AddMaterialDialog({ open, onOpenChange, caseItem }: Props) {
  const [flow, dispatch] = useReducer(flowReducer, initialFlowState);
  const {
    step,
    files,
    selectedCategory,
    batchName,
    validationResult,
    materialEventId,
    uploadResult,
    uploadBatchId,
    failureMessage,
  } = flow;
  const inputRef = useRef<HTMLInputElement>(null);
  const currentTaskIdRef = useRef<string | null>(null);
  const fileInputId = useId();
  const [isDraggingFiles, setIsDraggingFiles] = useState(false);

  const addTask = useUploadQueue((s) => s.addTask);
  const updateTask = useUploadQueue((s) => s.updateTask);

  const {
    categories,
    isLoading: categoriesLoading,
    error: categoriesError,
    refresh: refreshCategories,
  } = useDocCategories();
  const {
    caseDocCategories,
    isLoading: caseDocCategoriesLoading,
    error: caseDocCategoriesError,
    refresh: refreshCaseDocCategories,
  } = useCaseDocCategories(open ? caseItem.case_id : null);
  const { validate } = useValidateDocCategory();
  const { upload } = useUploadIngest();
  const {
    retry: retryUploadBatch,
    isMutating: isRetryingUploadBatch,
  } = useRetryUploadBatch(uploadBatchId ?? "");
  const { event: materialEvent } = useMaterialEvent(
    materialEventId,
    step === "processing" ? 3000 : 0
  );

  // Poll material event status
  useEffect(() => {
    if (!materialEvent || step !== "processing") return;

    if (materialEvent.status === "completed") {
      dispatch({ type: "PROCESSING_COMPLETED" });
      if (currentTaskIdRef.current) {
        updateTask(currentTaskIdRef.current, {
          status: "completed",
          materialEvent,
        });
      }
    } else if (materialEvent.status === "failed") {
      dispatch({
        type: "PROCESSING_FAILED",
        message: materialEvent.error_message || "材料解析失败，请重试。",
      });
      if (currentTaskIdRef.current) {
        updateTask(currentTaskIdRef.current, {
          status: "failed",
          materialEvent,
        });
      }
    }
  }, [materialEvent, step, updateTask]);

  // Reset state when dialog opens
  useEffect(() => {
    if (open) {
      dispatch({ type: "RESET" });
      currentTaskIdRef.current = null;
    }
  }, [open]);

  const categoryMap = useMemo(() => {
    const map = new Map<string, CaseDocCategoryItem>();
    caseDocCategories?.categories.forEach((c) => map.set(c.code, c));
    return map;
  }, [caseDocCategories]);
  const uploadedCategoryCount = useMemo(
    () => categories.filter((category) => {
      const item = categoryMap.get(category.code);
      return item?.uploaded || item?.covered_by_case_workpaper;
    }).length,
    [categories, categoryMap]
  );

  const addFiles = useCallback(async (selected: File[]) => {
    if (selected.length === 0) return;
    currentTaskIdRef.current = null;
    dispatch({ type: "FILES_ADDED", files: selected });

    // Auto-validate when files are selected and category is already chosen
    if (selectedCategory && step === "select") {
      dispatch({ type: "VALIDATE_STARTED" });
      try {
        const result = await validate({
          case_id: caseItem.case_id,
          doc_category: selectedCategory,
          file_names: selected.map((file) => file.name),
        });
        dispatch({ type: "VALIDATION_RESULT", result });
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "校验失败");
        dispatch({ type: "VALIDATION_ERRORED" });
      }
    }
  }, [selectedCategory, caseItem.case_id, validate, step]);

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    await addFiles(Array.from(e.target.files ?? []));
    // Allow the same file to be selected again after it is removed.
    e.target.value = "";
  }, [addFiles]);

  const removeFile = (index: number) => {
    currentTaskIdRef.current = null;
    dispatch({ type: "FILE_REMOVED", index });
  };

  const handleValidate = async () => {
    if (!selectedCategory || files.length === 0) return;
    // If already validated and no warnings, proceed to upload
    if (validationResult && validationOutcome(validationResult) === "proceed") {
      await handleUpload();
      return;
    }
    dispatch({ type: "VALIDATE_STARTED" });
    try {
      const result = await validate({
        case_id: caseItem.case_id,
        doc_category: selectedCategory,
        file_names: files.map((file) => file.name),
      });
      dispatch({ type: "VALIDATION_RESULT", result });
      if (validationOutcome(result) === "proceed") {
        await handleUpload();
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "校验失败");
      dispatch({ type: "VALIDATION_ERRORED" });
    }
  };

  const handleUpload = async () => {
    if (files.length === 0 || !selectedCategory) return;
    const stableUploadBatchId =
      uploadBatchId ??
      (typeof globalThis.crypto?.randomUUID === "function"
        ? globalThis.crypto.randomUUID()
        : `upload-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    dispatch({ type: "UPLOAD_STARTED", uploadBatchId: stableUploadBatchId });

    const categoryName =
      categories.find((c) => c.code === selectedCategory)?.name || selectedCategory;

    const taskId =
      currentTaskIdRef.current ??
      addTask({
        caseId: caseItem.case_id,
        caseName: caseItem.case_name,
        categoryName,
        batchName: batchName || undefined,
        fileNames: files.map((f) => f.name),
        status: "uploading",
        materialEventId: null,
        result: null,
        materialEvent: null,
      });
    if (currentTaskIdRef.current) {
      updateTask(taskId, {
        status: "uploading",
        materialEventId: null,
        result: null,
        materialEvent: null,
      });
    }
    currentTaskIdRef.current = taskId;

    try {
      const result = await upload({
        files,
        current_case_id: caseItem.case_id,
        doc_category: selectedCategory,
        batch_name: batchName || undefined,
        upload_batch_id: stableUploadBatchId,
      });
      if (result.error) {
        throw new Error(result.error);
      }
      dispatch({ type: "UPLOAD_SUCCEEDED", result });
      const materialEventId = uploadMaterialEventId(result);
      updateTask(taskId, {
        status: "processing",
        materialEventId,
        result,
      });
      if (!materialEventId) {
        toast.warning("上传已受理，但后端未返回材料事件 ID，无法自动跟踪处理状态");
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "上传失败";
      toast.error(message);
      dispatch({ type: "UPLOAD_FAILED", message });
      updateTask(taskId, { status: "failed" });
    }
  };

  const handleRetryProcessing = async () => {
    if (!uploadBatchId || !uploadResult) return;

    try {
      const result = await retryUploadBatch("auto");
      if (result.accepted === false) {
        throw new Error("后端未接受本次重试");
      }

      // The retry endpoint resumes the existing batch and returns the same
      // material event. Reusing it keeps the dialog polling instead of
      // uploading the selected files again with a failed batch ID.
      const materialEventId = result.material_event_id ?? uploadMaterialEventId(uploadResult);
      if (!materialEventId) {
        throw new Error("后端已接受重试，但未返回可跟踪的材料事件 ID");
      }

      dispatch({
        type: "UPLOAD_SUCCEEDED",
        result: { ...uploadResult, material_event_id: materialEventId },
      });
      if (currentTaskIdRef.current) {
        updateTask(currentTaskIdRef.current, {
          status: "processing",
          materialEventId,
          materialEvent: null,
        });
      }
      toast.success("材料处理已重新提交");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "批次重试失败");
    }
  };

  const isLoading = categoriesLoading || caseDocCategoriesLoading;
  const catalogUnavailable =
    !categoriesLoading && (Boolean(categoriesError) || categories.length === 0);
  const coverageUnavailable =
    !caseDocCategoriesLoading &&
    (Boolean(caseDocCategoriesError) || !caseDocCategories);
  const refreshCoverage = () => {
    void Promise.all([refreshCategories(), refreshCaseDocCategories()]).catch(() => undefined);
  };
  const canSubmit = flowCanSubmit(flow) && !catalogUnavailable;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[calc(100svh-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-[560px]">
        <DialogHeader className="shrink-0 border-b px-4 py-4 pr-12 sm:px-6">
          <DialogTitle className="text-base">上传年审资料</DialogTitle>
          <DialogDescription className="break-all text-xs text-muted-foreground">
            年审项目 <span className="font-mono">#{caseItem.case_id}</span>{" "}
            <span className="break-all">{caseItem.case_name}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4 sm:px-6">
          <div className="flex flex-col gap-5">
            {/* Coverage Grid */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs font-medium text-muted-foreground">审计资料覆盖情况</p>
                {!isLoading && !catalogUnavailable && !coverageUnavailable && (
                  <p className="text-[10px] text-muted-foreground">
                    已有 {uploadedCategoryCount} 类 · 缺失 {Math.max(categories.length - uploadedCategoryCount, 0)} 类
                  </p>
                )}
              </div>
              {catalogUnavailable ? (
                <Alert variant="destructive" className="gap-3 py-3">
                  <AlertTriangle className="size-4 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <AlertTitle className="text-xs">资料目录暂不可用</AlertTitle>
                    <AlertDescription className="mt-1 text-xs">
                      请重新加载目录后再选择资料类别和上传文件。
                    </AlertDescription>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={refreshCoverage}
                    className="shrink-0"
                  >
                    <RefreshCw className="size-3" data-icon="inline-start" />
                    重新加载
                  </Button>
                </Alert>
              ) : isLoading ? (
                <div className="flex items-center justify-center py-4">
                  <Loader2 className="size-4 animate-spin text-muted-foreground/30" />
                </div>
              ) : (
                <>
                  {coverageUnavailable && (
                    <Alert className="gap-3 py-3">
                      <AlertTriangle className="size-4 shrink-0 text-amber-600" />
                      <div className="min-w-0 flex-1">
                        <AlertTitle className="text-xs">覆盖状态暂不可用</AlertTitle>
                        <AlertDescription className="mt-1 text-xs">
                          仍可选择资料类别上传；资料覆盖结果将在接口恢复后刷新。
                        </AlertDescription>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={refreshCoverage}
                        className="shrink-0"
                      >
                        <RefreshCw className="size-3" data-icon="inline-start" />
                        刷新
                      </Button>
                    </Alert>
                  )}
                  <div className="max-h-[min(18rem,34svh)] overflow-y-auto overscroll-contain pr-1">
                    <div className="grid grid-cols-2 gap-2 min-[480px]:grid-cols-3 sm:grid-cols-4">
                    {categories.map((cat) => {
                      const caseCat = categoryMap.get(cat.code);
                      const uploaded = caseCat?.uploaded ?? false;
                      const coveredByCase = caseCat?.covered_by_case_workpaper && !caseCat?.raw_uploaded;
                      const coverageStatus = caseCat?.coverage_status ?? (uploaded ? "ready" : "missing");
                      const coverageLabel = coverageStatus === "failed"
                        ? "解析失败"
                        : coverageStatus === "pending"
                          ? "处理中"
                          : coverageStatus === "raw_only"
                            ? "待解析"
                            : "";
                      return (
                        <div
                          key={cat.code}
                          title={`${cat.name}\n状态: ${coverageStatus === "ready" ? "已覆盖" : coverageLabel || "缺失"}\n文件数: ${caseCat?.file_count ?? 0}\n可用文件: ${caseCat?.usable_file_count ?? 0}\n记录数: ${caseCat?.record_count ?? 0}${caseCat?.failed_event_count ? `\n失败批次: ${caseCat.failed_event_count}` : ""}${caseCat?.pending_event_count ? `\n处理中批次: ${caseCat.pending_event_count}` : ""}${coveredByCase ? "\n来源: 主底稿工作表覆盖" : ""}`}
                          className={cn(
                            "flex min-h-16 flex-col items-center justify-center gap-1 rounded-lg border px-2 py-2 text-center",
                            coverageStatus === "ready"
                              ? "border-emerald-300 bg-emerald-100"
                              : coverageStatus === "failed"
                                ? "border-red-300 bg-red-50"
                                : coverageStatus === "pending" || coverageStatus === "raw_only"
                                  ? "border-amber-300 bg-amber-50"
                              : "border-border/40 bg-muted/30"
                          )}
                        >
                          {coverageStatus === "ready" ? (
                            <CheckCircle2 className="size-4 shrink-0 text-emerald-500" />
                          ) : coverageStatus === "pending" ? (
                            <Loader2 className="size-4 shrink-0 animate-spin text-amber-600" />
                          ) : coverageStatus === "failed" || coverageStatus === "raw_only" ? (
                            <AlertTriangle className={cn("size-4 shrink-0", coverageStatus === "failed" ? "text-red-500" : "text-amber-600")} />
                          ) : (
                            <div className="size-4 shrink-0 rounded-full border-2 border-muted-foreground/20" />
                          )}
                          <span className={cn(
                            "text-[10px] leading-tight",
                            coverageStatus === "ready"
                              ? "text-emerald-600"
                              : coverageStatus === "failed"
                                ? "text-red-700"
                                : coverageStatus === "pending" || coverageStatus === "raw_only"
                                  ? "text-amber-800"
                                  : "text-muted-foreground/60"
                          )}>
                            {cat.name}{coveredByCase ? "（主底稿）" : ""}
                          </span>
                          {coverageLabel && (
                            <span className={cn("text-[9px] leading-none", coverageStatus === "failed" ? "text-red-600" : "text-amber-700")}>
                              {coverageLabel}
                            </span>
                          )}
                        </div>
                      );
                    })}
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* Category Select */}
            <div className="flex flex-col gap-2">
          <label className="text-xs font-medium text-muted-foreground">资料类别</label>
          <Select
            value={selectedCategory}
            onValueChange={(code) => {
              currentTaskIdRef.current = null;
              dispatch({ type: "CATEGORY_SELECTED", code });
            }}
            disabled={categoriesLoading || catalogUnavailable}
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="选择年审资料类别" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {categories.map((cat) => {
                  const caseCat = categoryMap.get(cat.code);
                  const uploaded = caseCat?.uploaded ?? false;
                  const coveredByCase = caseCat?.covered_by_case_workpaper && !caseCat?.raw_uploaded;
                  const coverageStatus = caseCat?.coverage_status ?? (uploaded ? "ready" : "missing");
                  const coverageLabel = coverageStatus === "failed"
                    ? "解析失败"
                    : coverageStatus === "pending"
                      ? "处理中"
                      : coverageStatus === "raw_only"
                        ? "待解析"
                        : "";
                  return (
                    <SelectItem key={cat.code} value={cat.code}>
                      <span className="flex items-center gap-2">
                        {cat.name}
                        {coverageStatus === "ready" && (
                          <CheckCircle2 className="size-3.5 text-emerald-500" />
                        )}
                        {coverageStatus === "pending" && <Loader2 className="size-3.5 animate-spin text-amber-600" />}
                        {(coverageStatus === "failed" || coverageStatus === "raw_only") && (
                          <AlertTriangle className={cn("size-3.5", coverageStatus === "failed" ? "text-red-500" : "text-amber-600")} />
                        )}
                        {coveredByCase && <span className="text-[10px] text-emerald-600">主底稿</span>}
                        {coverageLabel && <span className={cn("text-[10px]", coverageStatus === "failed" ? "text-red-600" : "text-amber-700")}>{coverageLabel}</span>}
                      </span>
                    </SelectItem>
                  );
                })}
              </SelectGroup>
            </SelectContent>
          </Select>
            </div>

            {/* Batch Name */}
            <div className="flex flex-col gap-2">
          <label className="text-xs font-medium text-muted-foreground">批次名称（可选）</label>
          <input
            value={batchName}
            onChange={(e) => {
              currentTaskIdRef.current = null;
              dispatch({ type: "BATCH_NAME_SET", name: e.target.value });
            }}
            placeholder="如：2025年合同批次"
            className="w-full rounded-md border border-border/50 bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
            </div>

            {/* File Upload */}
            <div className="flex flex-col gap-2">
          <label className="text-xs font-medium text-muted-foreground">文件</label>
          {files.length > 0 ? (
              <div className="flex flex-col gap-1.5">
                <div className="max-h-36 space-y-1.5 overflow-y-auto overscroll-contain pr-1">
                  {files.map((f, i) => (
                    <div key={`${f.name}-${i}`} className="flex items-center gap-2.5 rounded-md bg-muted/40 px-3 py-2 text-xs">
                      <FileText className="size-3.5 shrink-0 text-muted-foreground/50" />
                      <span className="min-w-0 flex-1 truncate text-foreground/80">{f.name}</span>
                      <span className="shrink-0 text-muted-foreground/40">{(f.size / 1024 / 1024).toFixed(2)} MB</span>
                      <button
                        type="button"
                        onClick={() => removeFile(i)}
                        aria-label={`移除 ${f.name}`}
                        title="移除文件"
                        className="shrink-0 rounded-sm text-muted-foreground/50 transition-colors hover:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <X className="size-3" />
                      </button>
                    </div>
                  ))}
                </div>
                <label
                  htmlFor={fileInputId}
                  className="mt-1 flex cursor-pointer items-center justify-center gap-1.5 rounded-md border border-dashed border-border/40 py-2 text-xs text-muted-foreground/60 transition-colors hover:border-border/60 hover:bg-accent/10 focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/50"
                >
                  <Upload className="size-3.5" />
                  继续添加文件
                </label>
              </div>
            ) : (
              <label
                htmlFor={fileInputId}
                onDragEnter={(event) => {
                  event.preventDefault();
                  setIsDraggingFiles(true);
                }}
                onDragOver={(event) => event.preventDefault()}
                onDragLeave={() => setIsDraggingFiles(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setIsDraggingFiles(false);
                  void addFiles(Array.from(event.dataTransfer.files ?? []));
                }}
                className={cn(
                  "flex min-h-28 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors select-none",
                  "border-border/40 hover:border-border/60 hover:bg-accent/10 focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/50",
                  isDraggingFiles && "border-primary bg-primary/5"
                )}
              >
                <Upload className="size-5 text-muted-foreground/50" />
                <p className="text-xs text-muted-foreground/60">点击或拖拽选择文件</p>
                <p className="text-[10px] text-muted-foreground/40">支持 PDF / Word / Excel / 图片，单个 ≤ 50MB</p>
              </label>
            )}
              <input
                ref={inputRef}
                id={fileInputId}
                type="file"
                multiple
                className="sr-only"
                aria-label="选择年审资料文件"
                onChange={handleFileSelect}
              />
            </div>

            {/* Validation Alert */}
            {validationResult && (
          <Alert
            variant={validationResult.suspected_duplicate ? "destructive" : "default"}
            className={cn(
              "flex items-start gap-3",
              validationResult.suspected_mismatch && !validationResult.suspected_duplicate && "border-amber-200/60 bg-amber-50/50 text-amber-900"
            )}
          >
            <AlertTriangle className="size-4 mt-0.5 shrink-0" />
            <AlertDescription className="text-xs leading-relaxed">
              {validationResult.message}
            </AlertDescription>
          </Alert>
            )}

            {/* Status displays */}
            {step === "uploading" && (
          <div className="flex items-center gap-2 rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            正在上传文件...
          </div>
            )}

            {step === "processing" && (
          <div className="flex flex-col gap-2 rounded-md bg-muted/40 px-3 py-3 text-xs">
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" />
              正在解析入库...
            </div>
            <p className="text-muted-foreground/60">事件 ID: {materialEventId}</p>
          </div>
            )}

            {step === "completed" && uploadResult && (
          <div className="flex flex-col gap-2 rounded-md border border-border/60 bg-background px-3 py-3 text-xs">
            <div className="flex items-center gap-2 text-foreground">
              <CheckCircle2 className="size-4 text-emerald-600" />
              <span className="font-medium">上传完成</span>
            </div>
            <p className="text-muted-foreground">{materialEvent?.event_payload?.parse_summary || materialEvent?.change_summary || uploadResult.parse_summary || "文件已入库"}</p>
            {materialEvent?.event_payload?.categories_found && materialEvent.event_payload.categories_found.length > 0 && (
              <div className="mt-1">
                <p className="text-[10px] font-medium text-foreground/80">识别出的类别</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {materialEvent.event_payload.categories_found.map((cat) => (
                    <span key={cat} className="rounded-md bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{cat}</span>
                  ))}
                </div>
              </div>
            )}
            {materialEvent?.has_conclusion_changes && (
              <div className="mt-1 rounded-md bg-amber-50/50 border border-amber-200/60 px-2 py-1.5">
                <p className="text-[10px] font-medium text-amber-700">结论变更</p>
                <p className="text-[10px] text-amber-600/80">{materialEvent.change_summary || "本次补件引发了结论变化"}</p>
              </div>
            )}
            {(uploadResult.new_files?.length ?? 0) > 0 && (
              <div className="mt-1">
                <p className="text-[10px] font-medium text-foreground/80">新增文件</p>
                <ul className="mt-0.5 space-y-0.5">
                  {uploadResult.new_files?.map((name) => (
                    <li key={name} className="text-[10px] text-muted-foreground">{name}</li>
                  ))}
                </ul>
              </div>
            )}
            {(uploadResult.duplicate_files?.length ?? 0) > 0 && (
              <div className="mt-1">
                <p className="text-[10px] font-medium text-foreground/80">重复文件</p>
                <ul className="mt-0.5 space-y-0.5">
                  {uploadResult.duplicate_files?.map((name) => (
                    <li key={name} className="text-[10px] text-muted-foreground">{name}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
            )}

            {step === "failed" && (
          <div className="flex flex-col gap-2 rounded-md border border-red-200/60 bg-red-50/50 px-3 py-3 text-xs">
            <div className="flex items-center gap-2 text-red-700">
              <AlertTriangle className="size-4" />
              <span className="font-medium">{uploadResult ? "材料处理失败" : "上传失败"}</span>
            </div>
            <p className="break-words text-red-600/80">
              {failureMessage || "材料解析失败，请重试。"}
            </p>
          </div>
            )}
          </div>
        </div>

        <DialogFooter className="shrink-0 border-t px-4 py-3 sm:px-6">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={step === "uploading" || step === "processing"}
          >
            {step === "completed" || step === "failed" ? "关闭" : "取消"}
          </Button>
          {step === "completed" ? (
            <Button
              size="sm"
              onClick={() => {
                dispatch({ type: "RESET" });
                currentTaskIdRef.current = null;
              }}
            >
              继续上传
            </Button>
          ) : step === "failed" && uploadResult && uploadBatchId ? (
            <Button size="sm" onClick={() => void handleRetryProcessing()} disabled={isRetryingUploadBatch}>
              {isRetryingUploadBatch ? (
                <Loader2 className="size-3 animate-spin" data-icon="inline-start" />
              ) : (
                <RefreshCw className="size-3" data-icon="inline-start" />
              )}
              {isRetryingUploadBatch ? "提交中" : "重试处理"}
            </Button>
          ) : step === "failed" ? (
            <Button size="sm" onClick={() => void handleValidate()}>
              重试上传
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={handleValidate}
              disabled={!canSubmit}
            >
              {(step === "validate" || step === "uploading") && <Loader2 className="size-3 animate-spin" data-icon="inline-start" />}
              确认上传
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

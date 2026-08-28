"use client";

import { useReducer, useCallback, useMemo, useRef, useEffect } from "react";
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
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Upload,
  X,
  Loader2,
  FileText,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Case } from "@/lib/hooks/use-cases";
import { useDocCategories } from "@/lib/hooks/use-doc-categories";
import { useCaseDocCategories } from "@/lib/hooks/use-case-doc-categories";
import { useValidateDocCategory } from "@/lib/hooks/use-validate-doc-category";
import { useUploadIngest } from "@/lib/hooks/use-upload-ingest";
import { useMaterialEvent } from "@/lib/hooks/use-material-event";
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

  const addTask = useUploadQueue((s) => s.addTask);
  const updateTask = useUploadQueue((s) => s.updateTask);

  const { categories, isLoading: categoriesLoading } = useDocCategories();
  const { caseDocCategories, isLoading: caseDocCategoriesLoading } = useCaseDocCategories(
    open ? caseItem.case_id : null
  );
  const { validate } = useValidateDocCategory();
  const { upload } = useUploadIngest();
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

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files ?? []);
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

  const isLoading = categoriesLoading || caseDocCategoriesLoading;
  const canSubmit = flowCanSubmit(flow);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="text-base">上传年审资料</DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            年审项目 <span className="font-mono">#{caseItem.case_id}</span>{" "}
            <span className="truncate">{caseItem.case_name}</span>
          </DialogDescription>
        </DialogHeader>

        {/* Coverage Grid */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-medium text-muted-foreground">审计资料覆盖情况</p>
            {!isLoading && (
              <p className="text-[10px] text-muted-foreground">
                已有 {uploadedCategoryCount} 类 · 缺失 {Math.max(categories.length - uploadedCategoryCount, 0)} 类
              </p>
            )}
          </div>
          {isLoading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="size-4 animate-spin text-muted-foreground/30" />
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-2">
              {categories.map((cat) => {
                const caseCat = categoryMap.get(cat.code);
                const uploaded = caseCat?.uploaded ?? false;
                const coveredByCase = caseCat?.covered_by_case_workpaper && !caseCat?.raw_uploaded;
                return (
                  <div
                    key={cat.code}
                    title={`${cat.name}\n文件数: ${caseCat?.file_count ?? 0}\n记录数: ${caseCat?.record_count ?? 0}${coveredByCase ? "\n来源: 主底稿工作表覆盖" : ""}`}
                    className={cn(
                      "flex flex-col items-center gap-1 rounded-lg border px-2 py-2 text-center",
                      uploaded
                        ? "border-emerald-300 bg-emerald-100"
                        : "border-border/40 bg-muted/30"
                    )}
                  >
                    {uploaded ? (
                      <CheckCircle2 className="size-4 text-emerald-500" />
                    ) : (
                      <div className="size-4 rounded-full border-2 border-muted-foreground/20" />
                    )}
                    <span className={cn("text-[10px] leading-tight", uploaded ? "text-emerald-600" : "text-muted-foreground/60")}>
                      {cat.name}{coveredByCase ? "（主底稿）" : ""}
                    </span>
                  </div>
                );
              })}
            </div>
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
            disabled={categoriesLoading}
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
                  return (
                    <SelectItem key={cat.code} value={cat.code}>
                      <span className="flex items-center gap-2">
                        {cat.name}
                        {uploaded && (
                          <CheckCircle2 className="size-3.5 text-emerald-500" />
                        )}
                        {coveredByCase && <span className="text-[10px] text-emerald-600">主底稿</span>}
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
            className="w-full rounded-md border border-border/50 bg-background px-3 py-2 text-sm outline-none focus:border-border"
          />
        </div>

        {/* File Upload */}
        <div className="flex flex-col gap-2">
          <label className="text-xs font-medium text-muted-foreground">文件</label>
          {files.length > 0 ? (
            <div className="flex flex-col gap-1.5">
              {files.map((f, i) => (
                <div key={`${f.name}-${i}`} className="flex items-center gap-2.5 rounded-md bg-muted/40 px-3 py-2 text-xs">
                  <FileText className="size-3.5 shrink-0 text-muted-foreground/50" />
                  <span className="min-w-0 flex-1 truncate text-foreground/80">{f.name}</span>
                  <span className="shrink-0 text-muted-foreground/40">{(f.size / 1024 / 1024).toFixed(2)} MB</span>
                  <button
                    type="button"
                    onClick={() => removeFile(i)}
                    className="shrink-0 text-muted-foreground/30 hover:text-muted-foreground/70"
                  >
                    <X className="size-3" />
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                className="mt-1 flex items-center justify-center gap-1.5 rounded-md border border-dashed border-border/40 py-2 text-xs text-muted-foreground/60 hover:border-border/60 hover:bg-accent/10"
              >
                <Upload className="size-3.5" />
                继续添加文件
              </button>
            </div>
          ) : (
            <div
              onClick={() => inputRef.current?.click()}
              className={cn(
                "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed py-6 transition-colors select-none",
                "border-border/40 hover:border-border/60 hover:bg-accent/10"
              )}
            >
              <Upload className="size-5 text-muted-foreground/50" />
              <p className="text-xs text-muted-foreground/60">点击或拖拽选择文件</p>
              <p className="text-[10px] text-muted-foreground/40">支持 PDF / Word / Excel / 图片，单个 ≤ 50MB</p>
            </div>
          )}
          <input
            ref={inputRef}
            type="file"
            multiple
            className="hidden"
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
              <span className="font-medium">上传失败</span>
            </div>
            <p className="break-words text-red-600/80">
              {failureMessage || "材料解析失败，请重试。"}
            </p>
          </div>
        )}

        <DialogFooter>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={step === "uploading" || step === "processing"}
          >
            {step === "completed" || step === "failed" ? "关闭" : "取消"}
          </Button>
          {step === "completed" || (step === "failed" && uploadResult) ? (
            <Button
              size="sm"
              onClick={() => {
                dispatch({ type: "RESET" });
                currentTaskIdRef.current = null;
              }}
            >
              继续上传
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

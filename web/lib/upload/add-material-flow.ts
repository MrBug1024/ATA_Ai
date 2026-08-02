import type { UploadAndIngestResponse } from "@/lib/types/doc-categories";

/**
 * 「上传卷宗」对话框的纯状态机。
 * 异步编排(校验请求、上传请求、事件轮询)留在组件里,组件只负责在恰当时机
 * dispatch 事件;所有状态转换都集中在这里,可脱离 UI 单测。
 */
export type Step = "select" | "validate" | "uploading" | "processing" | "completed" | "failed";

export interface ValidationResult {
  ok: boolean;
  suspected_mismatch: boolean;
  suspected_duplicate: boolean;
  message: string;
}

export interface FlowState {
  step: Step;
  files: File[];
  selectedCategory: string;
  batchName: string;
  validationResult: ValidationResult | null;
  materialEventId: string | null;
  uploadResult: UploadAndIngestResponse | null;
  uploadBatchId: string | null;
}

export const initialFlowState: FlowState = {
  step: "select",
  files: [],
  selectedCategory: "",
  batchName: "",
  validationResult: null,
  materialEventId: null,
  uploadResult: null,
  uploadBatchId: null,
};

export type FlowEvent =
  | { type: "FILES_ADDED"; files: File[] }
  | { type: "FILE_REMOVED"; index: number }
  | { type: "CATEGORY_SELECTED"; code: string }
  | { type: "BATCH_NAME_SET"; name: string }
  | { type: "VALIDATE_STARTED" }
  | { type: "VALIDATION_RESULT"; result: ValidationResult }
  | { type: "VALIDATION_ERRORED" }
  | { type: "UPLOAD_STARTED"; uploadBatchId: string }
  | { type: "UPLOAD_SUCCEEDED"; result: UploadAndIngestResponse }
  | { type: "UPLOAD_FAILED" }
  | { type: "PROCESSING_COMPLETED" }
  | { type: "PROCESSING_FAILED" }
  | { type: "RESET" };

export function uploadMaterialEventId(result: UploadAndIngestResponse): string | null {
  return result.material_event_id || result.upload_batch_summary?.material_event_id || null;
}

export function flowReducer(state: FlowState, event: FlowEvent): FlowState {
  switch (event.type) {
    case "FILES_ADDED":
      return {
        ...state,
        files: [...state.files, ...event.files],
        validationResult: null,
        uploadBatchId: null,
      };
    case "FILE_REMOVED":
      return {
        ...state,
        files: state.files.filter((_, i) => i !== event.index),
        validationResult: null,
        uploadBatchId: null,
      };
    case "CATEGORY_SELECTED":
      return {
        ...state,
        selectedCategory: event.code,
        validationResult: null,
        uploadBatchId: null,
      };
    case "BATCH_NAME_SET":
      return { ...state, batchName: event.name, uploadBatchId: null };
    case "VALIDATE_STARTED":
      return { ...state, step: "validate" };
    case "VALIDATION_RESULT":
      return { ...state, step: "select", validationResult: event.result };
    case "VALIDATION_ERRORED":
      return { ...state, step: "select" };
    case "UPLOAD_STARTED":
      return { ...state, step: "uploading", uploadBatchId: event.uploadBatchId };
    case "UPLOAD_SUCCEEDED":
      return {
        ...state,
        step: "processing",
        uploadResult: event.result,
        materialEventId: uploadMaterialEventId(event.result),
      };
    case "UPLOAD_FAILED":
      return { ...state, step: "failed" };
    case "PROCESSING_COMPLETED":
      return { ...state, step: "completed", materialEventId: null };
    case "PROCESSING_FAILED":
      return { ...state, step: "failed", materialEventId: null };
    case "RESET":
      return initialFlowState;
  }
}

/** 校验结果是否可以直接进入上传(无任何告警)。 */
export function validationOutcome(r: ValidationResult): "proceed" | "warn" {
  return r.ok && !r.suspected_mismatch && !r.suspected_duplicate ? "proceed" : "warn";
}

/** 「确认上传」按钮是否可用。 */
export function canSubmit(state: FlowState): boolean {
  return (
    state.selectedCategory !== "" &&
    state.files.length > 0 &&
    (state.step === "select" || state.step === "completed" || state.step === "failed")
  );
}

import { describe, it, expect } from "vitest";
import {
  flowReducer,
  initialFlowState,
  validationOutcome,
  canSubmit,
  type FlowState,
} from "@/lib/upload/add-material-flow";
import type { UploadAndIngestResponse } from "@/lib/types/doc-categories";

const file = (name: string) => new File(["x"], name);

const okResult = { ok: true, suspected_mismatch: false, suspected_duplicate: false, message: "" };
const warnResult = { ok: true, suspected_mismatch: true, suspected_duplicate: false, message: "疑似类别不符" };

function uploadResp(eventId: string): UploadAndIngestResponse {
  return {
    material_event_id: eventId,
  };
}

describe("flowReducer", () => {
  it("FILES_ADDED 追加文件,FILE_REMOVED 按下标移除", () => {
    let s = flowReducer(initialFlowState, { type: "FILES_ADDED", files: [file("a.pdf")] });
    s = flowReducer(s, { type: "FILES_ADDED", files: [file("b.pdf")] });
    expect(s.files.map((f) => f.name)).toEqual(["a.pdf", "b.pdf"]);
    s = flowReducer(s, { type: "FILE_REMOVED", index: 0 });
    expect(s.files.map((f) => f.name)).toEqual(["b.pdf"]);
  });

  it("CATEGORY_SELECTED / BATCH_NAME_SET 写入字段", () => {
    let s = flowReducer(initialFlowState, { type: "CATEGORY_SELECTED", code: "contract" });
    s = flowReducer(s, { type: "BATCH_NAME_SET", name: "批次一" });
    expect(s.selectedCategory).toBe("contract");
    expect(s.batchName).toBe("批次一");
  });

  it("校验生命周期:VALIDATE_STARTED → VALIDATION_RESULT 回到 select 并存结果", () => {
    let s = flowReducer(initialFlowState, { type: "VALIDATE_STARTED" });
    expect(s.step).toBe("validate");
    s = flowReducer(s, { type: "VALIDATION_RESULT", result: warnResult });
    expect(s.step).toBe("select");
    expect(s.validationResult).toEqual(warnResult);
  });

  it("VALIDATION_ERRORED 回到 select,不覆盖已有结果", () => {
    let s: FlowState = { ...initialFlowState, step: "validate", validationResult: okResult };
    s = flowReducer(s, { type: "VALIDATION_ERRORED" });
    expect(s.step).toBe("select");
    expect(s.validationResult).toEqual(okResult);
  });

  it("上传生命周期:UPLOAD_STARTED → UPLOAD_SUCCEEDED 进入 processing 并提取事件 ID", () => {
    let s = flowReducer(initialFlowState, {
      type: "UPLOAD_STARTED",
      uploadBatchId: "batch-stable",
    });
    expect(s.step).toBe("uploading");
    expect(s.uploadBatchId).toBe("batch-stable");
    s = flowReducer(s, { type: "UPLOAD_SUCCEEDED", result: uploadResp("evt-1") });
    expect(s.step).toBe("processing");
    expect(s.materialEventId).toBe("evt-1");
    expect(s.uploadResult).not.toBeNull();
  });

  it("兼容旧响应里嵌套的材料事件 ID", () => {
    const result: UploadAndIngestResponse = {
      upload_batch_summary: { material_event_id: "legacy-event" } as UploadAndIngestResponse["upload_batch_summary"],
    };
    const state = flowReducer(initialFlowState, { type: "UPLOAD_SUCCEEDED", result });
    expect(state.materialEventId).toBe("legacy-event");
  });

  it("UPLOAD_FAILED → failed", () => {
    const s = flowReducer({ ...initialFlowState, step: "uploading" }, { type: "UPLOAD_FAILED" });
    expect(s.step).toBe("failed");
  });

  it("PROCESSING_COMPLETED / PROCESSING_FAILED 清空事件 ID", () => {
    const base: FlowState = { ...initialFlowState, step: "processing", materialEventId: "evt-1" };
    const done = flowReducer(base, { type: "PROCESSING_COMPLETED" });
    expect(done.step).toBe("completed");
    expect(done.materialEventId).toBeNull();
    const failed = flowReducer(base, { type: "PROCESSING_FAILED" });
    expect(failed.step).toBe("failed");
    expect(failed.materialEventId).toBeNull();
  });

  it("RESET 回到初始状态", () => {
    const dirty: FlowState = {
      step: "completed",
      files: [file("a.pdf")],
      selectedCategory: "contract",
      batchName: "b",
      validationResult: warnResult,
      materialEventId: "e",
      uploadResult: uploadResp("e"),
      uploadBatchId: "batch-e",
    };
    expect(flowReducer(dirty, { type: "RESET" })).toEqual(initialFlowState);
  });

  it("上传失败保留批次 ID，输入变化后清空", () => {
    const uploading = flowReducer(initialFlowState, {
      type: "UPLOAD_STARTED",
      uploadBatchId: "batch-retry",
    });
    const failed = flowReducer(uploading, { type: "UPLOAD_FAILED" });
    expect(failed.uploadBatchId).toBe("batch-retry");

    const changed = flowReducer(
      { ...failed, validationResult: okResult },
      {
      type: "CATEGORY_SELECTED",
      code: "judgment",
      }
    );
    expect(changed.uploadBatchId).toBeNull();
    expect(changed.validationResult).toBeNull();
  });

  it("reducer 不可变:不修改输入 state", () => {
    const before = { ...initialFlowState };
    flowReducer(initialFlowState, { type: "FILES_ADDED", files: [file("a.pdf")] });
    expect(initialFlowState).toEqual(before);
  });
});

describe("validationOutcome", () => {
  it("全绿 → proceed", () => {
    expect(validationOutcome(okResult)).toBe("proceed");
  });
  it("mismatch / duplicate / !ok → warn", () => {
    expect(validationOutcome(warnResult)).toBe("warn");
    expect(validationOutcome({ ...okResult, suspected_duplicate: true })).toBe("warn");
    expect(validationOutcome({ ...okResult, ok: false })).toBe("warn");
  });
});

describe("canSubmit", () => {
  const ready: FlowState = {
    ...initialFlowState,
    files: [file("a.pdf")],
    selectedCategory: "contract",
  };
  it("select/completed/failed 且有类别有文件 → true", () => {
    expect(canSubmit(ready)).toBe(true);
    expect(canSubmit({ ...ready, step: "completed" })).toBe(true);
    expect(canSubmit({ ...ready, step: "failed" })).toBe(true);
  });
  it("缺类别 / 缺文件 / 进行中 → false", () => {
    expect(canSubmit({ ...ready, selectedCategory: "" })).toBe(false);
    expect(canSubmit({ ...ready, files: [] })).toBe(false);
    expect(canSubmit({ ...ready, step: "uploading" })).toBe(false);
    expect(canSubmit({ ...ready, step: "processing" })).toBe(false);
    expect(canSubmit({ ...ready, step: "validate" })).toBe(false);
  });
});

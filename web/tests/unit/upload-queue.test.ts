import { describe, it, expect, beforeEach } from "vitest";
import { useUploadQueue, type UploadTask } from "@/lib/stores/upload-queue";

type NewTask = Omit<UploadTask, "id" | "createdAt" | "updatedAt">;

function makeTask(overrides: Partial<NewTask> = {}): NewTask {
  return {
    caseId: 1,
    caseName: "案件A",
    categoryName: "类别",
    fileNames: ["a.pdf"],
    status: "uploading",
    materialEventId: null,
    result: null,
    materialEvent: null,
    ...overrides,
  };
}

beforeEach(() => {
  useUploadQueue.setState({ tasks: [] });
});

describe("useUploadQueue", () => {
  it("addTask 生成 id 并填充时间戳", () => {
    const id = useUploadQueue.getState().addTask(makeTask());
    const tasks = useUploadQueue.getState().tasks;
    expect(tasks).toHaveLength(1);
    expect(tasks[0].id).toBe(id);
    expect(tasks[0].createdAt).toBeTypeOf("number");
    expect(tasks[0].updatedAt).toBe(tasks[0].createdAt);
  });

  it("addTask 多次生成唯一 id", () => {
    const a = useUploadQueue.getState().addTask(makeTask());
    const b = useUploadQueue.getState().addTask(makeTask());
    expect(a).not.toBe(b);
    expect(useUploadQueue.getState().tasks).toHaveLength(2);
  });

  it("updateTask 合并字段并更新 updatedAt", () => {
    const id = useUploadQueue.getState().addTask(makeTask());
    const before = useUploadQueue.getState().tasks[0].updatedAt;
    useUploadQueue.getState().updateTask(id, {
      status: "completed",
      materialEventId: "ev-1",
    });
    const task = useUploadQueue.getState().tasks[0];
    expect(task.status).toBe("completed");
    expect(task.materialEventId).toBe("ev-1");
    expect(task.updatedAt).toBeGreaterThanOrEqual(before);
  });

  it("updateTask 对不存在的 id 不影响其他任务", () => {
    const id = useUploadQueue.getState().addTask(makeTask());
    useUploadQueue.getState().updateTask("missing", { status: "failed" });
    expect(useUploadQueue.getState().tasks[0].id).toBe(id);
    expect(useUploadQueue.getState().tasks[0].status).toBe("uploading");
  });

  it("removeTask 删除指定任务", () => {
    const a = useUploadQueue.getState().addTask(makeTask());
    const b = useUploadQueue.getState().addTask(makeTask());
    useUploadQueue.getState().removeTask(a);
    const tasks = useUploadQueue.getState().tasks;
    expect(tasks).toHaveLength(1);
    expect(tasks[0].id).toBe(b);
  });

  it("clearCompleted 仅保留进行中任务", () => {
    useUploadQueue.getState().addTask(makeTask({ status: "uploading" }));
    useUploadQueue.getState().addTask(makeTask({ status: "processing" }));
    useUploadQueue.getState().addTask(makeTask({ status: "completed" }));
    useUploadQueue.getState().addTask(makeTask({ status: "failed" }));
    useUploadQueue.getState().clearCompleted();
    const statuses = useUploadQueue.getState().tasks.map((t) => t.status);
    expect(statuses).toEqual(["uploading", "processing"]);
  });
});

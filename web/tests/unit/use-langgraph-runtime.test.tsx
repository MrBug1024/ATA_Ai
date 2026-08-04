// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import type { DbMessage } from "@/lib/assistant-ui/types";
import { createChatAttachmentAdapter } from "@/lib/assistant-ui/chat-attachment-adapter";
import type { ChatUploadResponse, FileItem } from "@/lib/types/chat-upload";

// Capture the external-store config so we can drive onNew/onReload/onCancel directly.
let capturedConfig: {
  isRunning: boolean;
  messages: DbMessage[];
  onNew: (m: { content: unknown }) => Promise<void>;
  onCancel: () => Promise<void>;
  onReload: (parentId: string | null) => Promise<void>;
};

vi.mock("@assistant-ui/react", () => ({
  useExternalStoreRuntime: (config: typeof capturedConfig) => {
    capturedConfig = config;
    return { __runtime: true };
  },
}));

interface StreamCallbacks {
  onChunk: (c: string) => void;
  onReplace?: (snapshot: { text: string; parts?: DbMessage["_contentParts"] }) => void;
  onAbortRef: (cancel: () => void) => void;
  onThinking: (u: unknown) => void;
}
const runStreamMock = vi.fn();
vi.mock("@/lib/assistant-ui/sse", () => ({
  runStream: (...args: unknown[]) => runStreamMock(...args),
}));

function makeFileItem(name: string, hash: string): FileItem {
  return {
    name,
    url: `s3://x/${name}`,
    type: "file",
    extension: name.split(".").pop() ?? "",
    content_type: "application/pdf",
    content: "",
    doc_category: "",
    upload_batch_id: "b1",
    file_hash: hash,
    file_size: 10,
    content_ref: "",
    duplicate_of: "",
    storage_ref: `s3://x/${name}`,
    storage_provider: "s3",
    storage_bucket: "x",
    storage_key: name,
    storage_etag: "e",
    storage_version: "v",
  };
}

const uploadMock = vi.fn();
async function attachViaAdapter(name: string, hash: string) {
  const fi = makeFileItem(name, hash);
  const response: ChatUploadResponse = {
    upload_batch_id: "b1",
    case_id: 1,
    entity_id: 0,
    entity_name: "",
    effective_entity_name: "",
    file_count: 1,
    duplicate_files: [],
    files: [fi],
  };
  uploadMock.mockResolvedValueOnce(response);
  const adapter = createChatAttachmentAdapter({ caseId: 1, upload: uploadMock });
  const att = await adapter.add({ file: new File(["x"], name) });
  return { att, fi };
}

import { useLanggraphRuntime } from "@/lib/assistant-ui/use-langgraph-runtime";

beforeEach(() => {
  runStreamMock.mockReset();
  sessionStorage.clear();
});

afterEach(() => {
  // nothing
});

describe("useLanggraphRuntime", () => {
  it("优先使用会话详情里的非空报告引用", () => {
    const initialMessages: DbMessage[] = [
      {
        id: "a1",
        conversationId: "t1",
        role: "assistant",
        content: "历史回答",
        metadata: { final_report_ref: "" },
        createdAt: new Date(),
      },
    ];
    const { result } = renderHook(() =>
      useLanggraphRuntime("t1", 116, initialMessages, undefined, "detail-report-ref")
    );

    expect(result.current.reportRef).toBe("detail-report-ref");
  });

  it("发送空消息时不触发流", async () => {
    renderHook(() => useLanggraphRuntime("t1"));
    await waitFor(() => expect(capturedConfig).toBeDefined());
    await act(async () => {
      await capturedConfig.onNew({ content: "   " });
    });
    expect(runStreamMock).not.toHaveBeenCalled();
  });

  it("发送成功：流式增量结束后 isRunning=false", async () => {
    runStreamMock.mockImplementation(
      async (_req: { threadId: string; query: string }, cb: StreamCallbacks) => {
        cb.onAbortRef(() => {});
        cb.onChunk("hello world");
      }
    );
    renderHook(() => useLanggraphRuntime("t1", 42));
    await waitFor(() => expect(capturedConfig).toBeDefined());

    await act(async () => {
      await capturedConfig.onNew({ content: "hi" });
    });

    expect(runStreamMock).toHaveBeenCalledTimes(1);
    const req = runStreamMock.mock.calls[0][0];
    expect(req).toMatchObject({ threadId: "t1", query: "hi", caseId: 42 });
    expect(req.clientTurnId).toEqual(expect.any(String));
    expect(req.clientTurnId).not.toBe("");
    expect(req.regenerate).toBeUndefined();

    // Last assistant message has the final replacement
    const last = capturedConfig.messages[capturedConfig.messages.length - 1];
    expect(last.role).toBe("assistant");
    expect(last.content).toBe("hello world");
    expect(capturedConfig.isRunning).toBe(false);
  });

  it("分段快照写入 assistant 消息正文和结构化 parts", async () => {
    const parts = [
      { type: "text", text: "## 1. 数据洗脱\n\nA", parentId: "section-1" },
      { type: "reasoning", text: "why", parentId: "section-1" },
    ] as DbMessage["_contentParts"];
    runStreamMock.mockImplementation(
      async (_req: { threadId: string; query: string }, cb: StreamCallbacks) => {
        cb.onAbortRef(() => {});
        cb.onReplace?.({ text: "## 1. 数据洗脱\n\nA", parts });
      }
    );
    renderHook(() => useLanggraphRuntime("t1", 42));
    await waitFor(() => expect(capturedConfig).toBeDefined());

    await act(async () => {
      await capturedConfig.onNew({ content: "hi" });
    });

    const last = capturedConfig.messages[capturedConfig.messages.length - 1];
    expect(last.role).toBe("assistant");
    expect(last.content).toBe("## 1. 数据洗脱\n\nA");
    expect(last._contentParts).toBe(parts);
    expect(capturedConfig.isRunning).toBe(false);
  });

  it("发送出错：最后的流式消息标记为 error", async () => {
    runStreamMock.mockRejectedValue(new Error("stream failed"));
    renderHook(() => useLanggraphRuntime("t1"));
    await waitFor(() => expect(capturedConfig).toBeDefined());

    await act(async () => {
      await capturedConfig.onNew({ content: "hi" });
    });

    const last = capturedConfig.messages[capturedConfig.messages.length - 1];
    expect(last.role).toBe("assistant");
    expect(last._status).toMatchObject({ type: "incomplete", reason: "error", error: "stream failed" });
    expect(capturedConfig.isRunning).toBe(false);
  });

  it("onCancel 调用 abort 并停止运行", async () => {
    const abortSpy = vi.fn();
    runStreamMock.mockImplementation(
      async (_req: unknown, cb: StreamCallbacks) => {
        cb.onAbortRef(abortSpy);
        cb.onChunk("done");
      }
    );
    renderHook(() => useLanggraphRuntime("t1"));
    await waitFor(() => expect(capturedConfig).toBeDefined());
    await act(async () => {
      await capturedConfig.onNew({ content: "hi" });
    });
    await act(async () => {
      await capturedConfig.onCancel();
    });
    expect(abortSpy).toHaveBeenCalled();
    expect(capturedConfig.isRunning).toBe(false);
  });

  it("onReload 对空 parentId / 不存在的消息直接返回", async () => {
    renderHook(() => useLanggraphRuntime("t1"));
    await waitFor(() => expect(capturedConfig).toBeDefined());
    await act(async () => {
      await capturedConfig.onReload(null);
      await capturedConfig.onReload("does-not-exist");
    });
    expect(runStreamMock).not.toHaveBeenCalled();
  });

  it("历史轮次缺少原始 client_turn_id 时禁止重新生成", async () => {
    const initialMessages: DbMessage[] = [
      {
        id: "canonical-turn-hash",
        conversationId: "t1",
        role: "user",
        content: "历史问题",
        metadata: { turn_id: "canonical-turn-hash" },
        createdAt: new Date(),
      },
      {
        id: "assistant-history",
        conversationId: "t1",
        role: "assistant",
        content: "历史回答",
        metadata: null,
        createdAt: new Date(),
      },
    ];
    renderHook(() => useLanggraphRuntime("t1", undefined, initialMessages));
    await waitFor(() => expect(capturedConfig).toBeDefined());

    await act(async () => {
      await capturedConfig.onReload("canonical-turn-hash");
    });

    expect(runStreamMock).not.toHaveBeenCalled();
  });

  it("onReload 复用 parent turn id 并标记重新生成", async () => {
    // First send produces a user+assistant pair (with temp/stream ids).
    runStreamMock.mockImplementationOnce(
      async (_req: unknown, cb: StreamCallbacks) => {
        cb.onAbortRef(() => {});
        cb.onChunk("旧回答");
      }
    );
    runStreamMock.mockImplementationOnce(
      async (_req: unknown, cb: StreamCallbacks) => {
        cb.onAbortRef(() => {});
        cb.onChunk("新回答");
      }
    );

    renderHook(() => useLanggraphRuntime("t1"));
    await waitFor(() => expect(capturedConfig).toBeDefined());

    await act(async () => {
      await capturedConfig.onNew({ content: "原问题" });
    });

    const userMsg = capturedConfig.messages.find((m) => m.role === "user");
    expect(userMsg).toBeDefined();

    await act(async () => {
      await capturedConfig.onReload(userMsg!.id);
    });

    expect(runStreamMock).toHaveBeenCalledTimes(2);
    const firstRequest = runStreamMock.mock.calls[0][0];
    expect(runStreamMock.mock.calls[1][0]).toMatchObject({
      threadId: "t1",
      query: "原问题",
      clientTurnId: firstRequest.clientTurnId,
      regenerate: true,
    });
  });

  it("网络失败重试复用 client turn id 且不标记 regenerate", async () => {
    runStreamMock
      .mockRejectedValueOnce(new Error("network failed"))
      .mockImplementationOnce(async (_req: unknown, cb: StreamCallbacks) => {
        cb.onAbortRef(() => {});
        cb.onChunk("重试成功");
      });

    renderHook(() => useLanggraphRuntime("t1"));
    await waitFor(() => expect(capturedConfig).toBeDefined());

    await act(async () => {
      await capturedConfig.onNew({ content: "原问题" });
    });
    const firstRequest = runStreamMock.mock.calls[0][0];
    const userMsg = capturedConfig.messages.find((message) => message.role === "user");

    await act(async () => {
      await capturedConfig.onReload(userMsg!.id);
    });

    expect(runStreamMock.mock.calls[1][0]).toMatchObject({
      clientTurnId: firstRequest.clientTurnId,
      regenerate: false,
    });
  });

  it("从 sessionStorage 自动发送待发消息（纯字符串向后兼容）", async () => {
    sessionStorage.setItem("pending-message-t1", "自动发送内容");
    runStreamMock.mockResolvedValue(undefined);
    renderHook(() => useLanggraphRuntime("t1"));
    await waitFor(() => expect(runStreamMock).toHaveBeenCalled());
    expect(runStreamMock.mock.calls[0][0]).toMatchObject({ query: "自动发送内容" });
    expect(sessionStorage.getItem("pending-message-t1")).toBeNull();
  });

  it("从 sessionStorage 自动发送 JSON payload，附件经 prime 后透传", async () => {
    const fileItem = makeFileItem("c.pdf", "hp1");
    const payload = {
      content: "用 JSON 发送",
      attachments: [
        {
          id: "att-hp1",
          type: "file",
          name: "c.pdf",
          contentType: "application/pdf",
          content: [],
          status: { type: "complete" },
        },
      ],
      fileItemEntries: [["att-hp1", fileItem]],
    };
    sessionStorage.setItem("pending-message-t1", JSON.stringify(payload));
    runStreamMock.mockResolvedValue(undefined);
    renderHook(() => useLanggraphRuntime("t1", 99));
    await waitFor(() => expect(runStreamMock).toHaveBeenCalled());

    expect(runStreamMock.mock.calls[0][0]).toMatchObject({
      query: "用 JSON 发送",
      caseId: 99,
      uploadedFiles: [fileItem],
    });
    expect(sessionStorage.getItem("pending-message-t1")).toBeNull();
  });

  it("onNew 含附件时把 file_item 传给 runStream", async () => {
    runStreamMock.mockImplementation(async (_req: unknown, cb: StreamCallbacks) => {
      cb.onAbortRef(() => {});
      cb.onChunk("ok");
    });
    renderHook(() => useLanggraphRuntime("t1", 42));
    await waitFor(() => expect(capturedConfig).toBeDefined());

    const { att, fi } = await attachViaAdapter("a.pdf", "h1");

    await act(async () => {
      await capturedConfig.onNew({
        content: "看这个文件",
        attachments: [att],
      } as unknown as { content: string });
    });

    expect(runStreamMock.mock.calls[0][0]).toMatchObject({
      threadId: "t1",
      query: "看这个文件",
      caseId: 42,
      uploadedFiles: [fi],
    });
  });

  it("onNew 含附件时把 attachments 存入用户消息以供渲染", async () => {
    runStreamMock.mockImplementation(async (_req: unknown, cb: StreamCallbacks) => {
      cb.onAbortRef(() => {});
      cb.onChunk("ok");
    });
    renderHook(() => useLanggraphRuntime("t1", 42));
    await waitFor(() => expect(capturedConfig).toBeDefined());

    const { att } = await attachViaAdapter("b.pdf", "h3");

    await act(async () => {
      await capturedConfig.onNew({
        content: "看这个文件",
        attachments: [att],
      } as unknown as { content: string });
    });

    const userMsg = capturedConfig.messages.find((m) => m.role === "user");
    expect(userMsg).toBeDefined();
    expect(userMsg!._attachments).toEqual([att]);
  });

  it("onReload 重发时用 parent 消息保存的附件", async () => {
    runStreamMock.mockImplementationOnce(async (_req: unknown, cb: StreamCallbacks) => {
      cb.onAbortRef(() => {});
      cb.onChunk("首次回答");
    });
    runStreamMock.mockImplementationOnce(async (_req: unknown, cb: StreamCallbacks) => {
      cb.onAbortRef(() => {});
      cb.onChunk("重发回答");
    });

    renderHook(() => useLanggraphRuntime("t1"));
    await waitFor(() => expect(capturedConfig).toBeDefined());

    const { att, fi } = await attachViaAdapter("x.pdf", "h2");

    await act(async () => {
      await capturedConfig.onNew({
        content: "原问题",
        attachments: [att],
      } as unknown as { content: string });
    });

    const userMsg = capturedConfig.messages.find((m) => m.role === "user");
    expect(userMsg).toBeDefined();

    await act(async () => {
      await capturedConfig.onReload(userMsg!.id);
    });

    expect(runStreamMock).toHaveBeenCalledTimes(2);
    expect(runStreamMock.mock.calls[1][0]).toMatchObject({
      query: "原问题",
      uploadedFiles: [fi],
      clientTurnId: userMsg!.id,
      regenerate: true,
    });
  });
});

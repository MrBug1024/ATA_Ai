import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  parseSseStream,
  runStream,
  toLangGraphEvent,
  type StreamContentSnapshot,
} from "@/lib/assistant-ui/sse";

function sseResponseFrom(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
  return new Response(stream);
}

async function collect<T>(it: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const v of it) out.push(v);
  return out;
}

describe("parseSseStream", () => {
  it("解析标准 SSE 事件", async () => {
    const res = sseResponseFrom([
      `event: start\ndata: {}\n\n`,
      `event: node\ndata: {"node":"agent","summary":"思考中"}\n\n`,
    ]);
    const events = await collect(parseSseStream(res));
    expect(events).toEqual([
      { type: "start" },
      { type: "node", node: "agent", summary: "思考中", payload: undefined },
    ]);
  });

  it("跳过空行", async () => {
    const res = sseResponseFrom([
      `\n`,
      `event: final\ndata: {"final_report":"hi"}\n\n`,
    ]);
    const events = await collect(parseSseStream(res));
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("final");
  });

  it("跳过非法 JSON", async () => {
    const res = sseResponseFrom([
      `event: node\ndata: not-json\n\n`,
      `event: final\ndata: {"final_report":"ok"}\n\n`,
    ]);
    const events = await collect(parseSseStream(res));
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("final");
  });

  it("跨块 buffer 拼接", async () => {
    const res = sseResponseFrom([
      `event: final\ndata: {"final_`,
      `report":"hi"}\n\n`,
    ]);
    const events = await collect(parseSseStream(res));
    expect(events).toEqual([{ type: "final", finalReportRef: undefined, finalReport: "hi" }]);
  });

  it("无 body 抛错", async () => {
    const res = new Response(null);
    await expect(collect(parseSseStream(res))).rejects.toThrow("No response body");
  });
});

describe("runStream", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function makeCallbacks() {
    const chunks: string[] = [];
    const replaces: StreamContentSnapshot[] = [];
    const thinking: unknown[] = [];
    return {
      chunks,
      replaces,
      thinking,
      cb: {
        onChunk: (c: string) => chunks.push(c),
        onReplace: (snapshot: StreamContentSnapshot) => replaces.push(snapshot),
        onAbortRef: () => {},
        onThinking: (u: unknown) => thinking.push(u),
      },
    };
  }

  it("成功路径：text_chunk + final", async () => {
    fetchMock.mockResolvedValue(
      sseResponseFrom([
        `event: start\ndata: {}\n\n`,
        `event: node\ndata: {"node":"agent","summary":"步骤1"}\n\n`,
        `event: text_chunk\ndata: {"text":"hel"}\n\n`,
        `event: text_chunk\ndata: {"text":"lo"}\n\n`,
        `event: final\ndata: {"final_report":"hello world"}\n\n`,
      ])
    );

    const { cb, chunks, replaces, thinking } = makeCallbacks();
    let pendingFlush: (() => void) | null = null;
    const flushNow = () => {
      const fn = pendingFlush;
      pendingFlush = null;
      if (fn) fn();
    };
    await runStream(
      { threadId: "t1", query: "query" },
      cb,
      (fn: () => void) => {
        pendingFlush = fn;
      },
      () => {
        pendingFlush = null;
      },
      flushNow
    );
    expect(chunks.join("")).toBe("hello");
    // final_report 内容已不再写回消息，避免 smooth 重放
    expect(replaces).toEqual([]);
    expect(thinking.some((t) => (t as { type: string }).type === "node")).toBe(true);
    expect(thinking.length).toBe(1);
  });

  it("final 无流式正文时用 final_report 兜底", async () => {
    fetchMock.mockResolvedValue(
      sseResponseFrom([
        `event: final\ndata: {"final_report":"only final"}\n\n`,
      ])
    );

    const { cb, chunks, replaces } = makeCallbacks();
    await runStream(
      { threadId: "t1", query: "q" },
      cb,
      () => {},
      () => {},
      () => {}
    );
    expect(chunks).toEqual([]);
    expect(replaces).toEqual([{ text: "only final" }]);
  });

  it("分段事件交错到达时按 section_id 重组成快照", async () => {
    fetchMock.mockResolvedValue(
      sseResponseFrom([
        `event: section_start\ndata: {"section_id":"2","title":"资产清单","audience":"field"}\n\n`,
        `event: section_chunk\ndata: {"section_id":"2","text":"B1"}\n\n`,
        `event: section_start\ndata: {"section_id":"1","title":"数据洗脱","audience":"field"}\n\n`,
        `event: section_chunk\ndata: {"section_id":"1","text":"A1"}\n\n`,
        `event: section_reasoning_chunk\ndata: {"section_id":"1","text":"why A"}\n\n`,
        `event: section_done\ndata: {"section_id":"1"}\n\n`,
        `event: section_chunk\ndata: {"section_id":"2","text":"B2"}\n\n`,
        `event: section_done\ndata: {"section_id":"2"}\n\n`,
      ])
    );

    const { cb, chunks, replaces } = makeCallbacks();
    await runStream(
      { threadId: "t1", query: "q" },
      cb,
      () => {},
      () => {},
      () => {}
    );

    expect(chunks).toEqual([]);
    const last = replaces.at(-1);
    expect(last?.text).toBe("## 1. 数据洗脱\n\nA1\n\n## 2. 资产清单\n\nB1B2");
    expect(last?.parts).toEqual([
      { type: "text", text: "## 1. 数据洗脱\n\nA1", parentId: "section-1" },
      { type: "reasoning", text: "why A", parentId: "section-1" },
      { type: "text", text: "## 2. 资产清单\n\nB1B2", parentId: "section-2" },
    ]);
  });

  it("旧 text_chunk 后接 section 事件时迁移为分段快照", async () => {
    fetchMock.mockResolvedValue(
      sseResponseFrom([
        `event: text_chunk\ndata: {"text":"前言"}\n\n`,
        `event: section_start\ndata: {"section_id":"R1","title":"对账总览"}\n\n`,
        `event: section_chunk\ndata: {"section_id":"R1","text":"复盘"}\n\n`,
      ])
    );

    const { cb, chunks, replaces } = makeCallbacks();
    await runStream(
      { threadId: "t1", query: "q" },
      cb,
      () => {},
      () => {},
      () => {}
    );

    expect(chunks).toEqual(["前言"]);
    expect(replaces.at(-1)?.text).toBe("前言\n\n## R1. 对账总览\n\n复盘\n\n_生成中..._");
  });

  it("error 事件抛出", async () => {
    fetchMock.mockResolvedValue(
      sseResponseFrom([`event: error\ndata: {"message":"boom"}\n\n`])
    );
    const { cb } = makeCallbacks();
    await expect(
      runStream({ threadId: "t1", query: "q" }, cb, () => {}, () => {}, () => {})
    ).rejects.toThrow("boom");
  });

  it("error 事件无 message 时使用默认提示", async () => {
    fetchMock.mockResolvedValue(
      sseResponseFrom([`event: error\ndata: {}\n\n`])
    );
    const { cb } = makeCallbacks();
    await expect(
      runStream({ threadId: "t1", query: "q" }, cb, () => {}, () => {}, () => {})
    ).rejects.toThrow("Stream error");
  });

  it("非 200 响应抛错（带 text body）", async () => {
    fetchMock.mockResolvedValue(
      new Response("Thread not found", { status: 404 })
    );
    const { cb } = makeCallbacks();
    await expect(
      runStream({ threadId: "t1", query: "q" }, cb, () => {}, () => {}, () => {})
    ).rejects.toThrow("Thread not found");
  });

  it("uploadedFiles 被序列化到 body.uploaded_files", async () => {
    fetchMock.mockResolvedValue(sseResponseFrom([`event: done\ndata: {}\n\n`]));
    const { cb } = makeCallbacks();
    await runStream(
      {
        threadId: "t1",
        query: "q",
        uploadedFiles: [
          {
            name: "a.pdf",
            url: "s3://x/a.pdf",
            type: "file",
            extension: ".pdf",
            content_type: "application/pdf",
            content: "",
            doc_category: "",
            upload_batch_id: "b1",
            file_hash: "h1",
            file_size: 10,
            content_ref: "",
            duplicate_of: "",
            storage_ref: "s3://x/a.pdf",
            storage_provider: "s3",
            storage_bucket: "x",
            storage_key: "a.pdf",
            storage_etag: "e",
            storage_version: "v",
          },
        ],
      },
      cb,
      () => {},
      () => {},
      () => {}
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.uploaded_files).toHaveLength(1);
    expect(body.uploaded_files[0].file_hash).toBe("h1");
  });

  it("未传 uploadedFiles 时 body.uploaded_files = []", async () => {
    fetchMock.mockResolvedValue(sseResponseFrom([`event: done\ndata: {}\n\n`]));
    const { cb } = makeCallbacks();
    await runStream(
      { threadId: "t1", query: "q" },
      cb,
      () => {},
      () => {},
      () => {}
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.uploaded_files).toEqual([]);
  });
});

describe("toLangGraphEvent", () => {
  it("final 映射 final_report_ref", () => {
    expect(toLangGraphEvent("final", { final_report_ref: "r-1", final_report: "x" })).toEqual({
      type: "final",
      finalReportRef: "r-1",
      finalReport: "x",
    });
  });

  it("error 缺 message 时给默认值", () => {
    expect(toLangGraphEvent("error", {})).toEqual({ type: "error", message: "Stream error" });
  });

  it("未知事件归入 unknown", () => {
    expect(toLangGraphEvent("heartbeat", { a: 1 })).toEqual({
      type: "unknown",
      event: "heartbeat",
      data: { a: 1 },
    });
  });
});

import { describe, it, expect, vi, beforeEach } from "vitest";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);
vi.stubEnv("NEXT_PUBLIC_LANGGRAPH_API_BASE_URL", "http://lg");

beforeEach(() => {
  mockFetch.mockReset();
});

describe("key builders", () => {
  it("builds expected URLs", async () => {
    const lg = await import("@/lib/backend/langgraph");
    expect(lg.threadsKey()).toBe("http://lg/chat/threads?limit=50&offset=0");
    expect(lg.threadsKey({ caseId: 7, limit: 10, offset: 20 })).toBe(
      "http://lg/chat/threads?case_id=7&limit=10&offset=20"
    );
    expect(lg.isThreadsListKey(lg.threadsKey())).toBe(true);
    expect(lg.isThreadsListKey(lg.threadsKey({ limit: 200 }))).toBe(true);
    expect(lg.isThreadsListKey(lg.threadsKey({ caseId: 7, limit: 200 }))).toBe(true);
    expect(lg.isThreadsListKey("http://lg/chat/threads/t1")).toBe(false);
    expect(lg.isThreadsListKey("http://lg/chat/threads/t1/turns")).toBe(false);
    expect(lg.threadDetailKey("a/b")).toBe("http://lg/chat/threads/a%2Fb");
    expect(lg.threadMessagesKey("a/b")).toBe("http://lg/chat/threads/a%2Fb/messages");
    expect(lg.threadTurnsKey("a/b")).toBe("http://lg/chat/threads/a%2Fb/turns");
    expect(lg.caseMaterialEventsKey(7)).toBe("http://lg/files/cases/7/material-events");
    expect(lg.caseUploadBatchesKey(7)).toBe("http://lg/files/cases/7/upload-batches");
    expect(lg.evolutionItemsKey(7, "ADD", 50)).toBe(
      "http://lg/files/cases/7/evolution-items?limit=50&action=ADD"
    );
    expect(lg.unresolvedItemsKey(7, "pending", 50)).toBe(
      "http://lg/files/cases/7/unresolved-items?limit=50&status=pending"
    );
    expect(lg.materialEventKey("e/1")).toBe("http://lg/files/material-events/e%2F1");
    expect(lg.uploadBatchKey("b 1")).toBe("http://lg/files/upload-batches/b%201");
    expect(lg.uploadBatchRetryUrl("b 1", "graph")).toBe(
      "http://lg/files/upload-batches/b%201/retry?stage=graph"
    );
    expect(lg.pageAnchorsKey(3, 2)).toBe("http://lg/files/page-anchors?file_id=3&page_no=2");
    expect(lg.graphEntitiesKey(7)).toBe("http://lg/graph/cases/7/entities");
    expect(lg.caseProgressKey(7)).toBe("http://lg/cases/7/progress");
    expect(lg.caseForecastKey(7)).toBe("http://lg/cases/7/forecast");
    expect(lg.caseRecoveryKey(7)).toBe("http://lg/cases/7/recovery");
    expect(lg.caseCorrectionsKey(7)).toBe("http://lg/cases/7/corrections");
    expect(lg.caseCorrectionsKey(7, true)).toBe(
      "http://lg/cases/7/corrections?include_history=true"
    );
    expect(lg.caseDeadlineBoardKey(7)).toBe("http://lg/cases/7/deadline-board");
  });
});

describe("case analytics", () => {
  it("getCaseProgress GETs the progress board", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ case_id: 7, recovery_ratio_pct: 50 }),
    });
    const { getCaseProgress } = await import("@/lib/backend/langgraph");
    const data = await getCaseProgress(7);
    expect(mockFetch.mock.calls[0][0]).toBe("http://lg/cases/7/progress");
    expect(data.case_id).toBe(7);
  });

  it("updateCaseProgress issues PUT with JSON body", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    const { updateCaseProgress } = await import("@/lib/backend/langgraph");
    await updateCaseProgress(7, { stage: "处置中" });
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://lg/cases/7/progress");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ stage: "处置中" });
  });

  it("listCaseForecasts unwraps forecasts", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ case_id: 7, forecasts: [{ tranche: "一期" }] }),
    });
    const { listCaseForecasts } = await import("@/lib/backend/langgraph");
    expect(await listCaseForecasts(7)).toEqual([{ tranche: "一期" }]);
  });

  it("seedCaseForecast POSTs report_ref + tranches", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    const { seedCaseForecast } = await import("@/lib/backend/langgraph");
    await seedCaseForecast(7, { report_ref: "r1", tranches: [] });
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://lg/cases/7/forecast");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ report_ref: "r1", tranches: [] });
  });

  it("listCaseRecovery unwraps records", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ case_id: 7, records: [{ id: 1 }] }),
    });
    const { listCaseRecovery } = await import("@/lib/backend/langgraph");
    expect(await listCaseRecovery(7)).toEqual([{ id: 1 }]);
  });

  it("createRecovery POSTs the record payload", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 9 }) });
    const { createRecovery } = await import("@/lib/backend/langgraph");
    const rec = await createRecovery(7, { amount: 100, recovered_at: "2026-01-01" });
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://lg/cases/7/recovery");
    expect(init.method).toBe("POST");
    expect(rec.id).toBe(9);
  });

  it("confirmRecovery POSTs to the confirm path", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 3, status: "confirmed" }) });
    const { confirmRecovery } = await import("@/lib/backend/langgraph");
    await confirmRecovery(7, 3);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://lg/cases/7/recovery/3/confirm");
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
  });

  it("reviewCase POSTs thread_id + query", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ thread_id: "t", case_id: 7, final_report: "ok" }),
    });
    const { reviewCase } = await import("@/lib/backend/langgraph");
    const data = await reviewCase(7, {
      thread_id: "review-thread",
      query: "重新复盘",
    });
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://lg/cases/7/review");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      thread_id: "review-thread",
      query: "重新复盘",
    });
    expect(data.final_report).toBe("ok");
  });

  it("supports corrections and deadline board operations", async () => {
    mockFetch
      .mockResolvedValueOnce({ ok: true, json: async () => ({ case_id: 7, corrections: [{ id: 1 }] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 2, status: "active" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 2, status: "revoked" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ case_id: 7, available: true }) });

    const {
      listCaseCorrections,
      createCorrection,
      revokeCorrection,
      getCaseDeadlineBoard,
    } = await import("@/lib/backend/langgraph");

    expect(await listCaseCorrections(7, true)).toEqual([{ id: 1 }]);
    await createCorrection(7, { target: "房产", instruction: "以新评估价为准" });
    await revokeCorrection(7, 2);
    expect((await getCaseDeadlineBoard(7)).available).toBe(true);

    expect(mockFetch.mock.calls[0][0]).toBe(
      "http://lg/cases/7/corrections?include_history=true"
    );
    expect(mockFetch.mock.calls[1][0]).toBe("http://lg/cases/7/corrections");
    expect(JSON.parse((mockFetch.mock.calls[1][1] as RequestInit).body as string)).toEqual({
      target: "房产",
      instruction: "以新评估价为准",
    });
    expect(mockFetch.mock.calls[2][0]).toBe("http://lg/cases/7/corrections/2/revoke");
    expect((mockFetch.mock.calls[2][1] as RequestInit).body).toBeUndefined();
    expect(mockFetch.mock.calls[3][0]).toBe("http://lg/cases/7/deadline-board");
  });
});

describe("threads", () => {
  it("listThreads preserves pagination metadata", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ threads: [{ thread_id: "t1" }], total: 62, limit: 10, offset: 20 }),
    });
    const { listThreads } = await import("@/lib/backend/langgraph");
    const page = await listThreads({ caseId: 7, limit: 10, offset: 20 });
    expect(page).toEqual({
      threads: [{ thread_id: "t1" }],
      total: 62,
      limit: 10,
      offset: 20,
    });
    expect(mockFetch.mock.calls[0][0]).toBe(
      "http://lg/chat/threads?case_id=7&limit=10&offset=20"
    );
  });

  it("gets thread detail and aggregated turns", async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ thread_id: "a/b", case_id: 7 }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ thread_id: "a/b", turns: [], turn_count: 0 }),
      });
    const { getThreadDetail, getThreadTurns } = await import("@/lib/backend/langgraph");
    expect((await getThreadDetail("a/b")).case_id).toBe(7);
    expect((await getThreadTurns("a/b")).turn_count).toBe(0);
    expect(mockFetch.mock.calls[0][0]).toBe("http://lg/chat/threads/a%2Fb");
    expect(mockFetch.mock.calls[1][0]).toBe("http://lg/chat/threads/a%2Fb/turns");
  });

  it("deleteThread issues DELETE on encoded id", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    const { deleteThread } = await import("@/lib/backend/langgraph");
    await deleteThread("a/b");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://lg/chat/threads/a%2Fb",
      expect.objectContaining({ method: "DELETE" })
    );
  });

  it("getThreadMessages hits messages endpoint", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ thread_id: "t1", messages: [], message_count: 0 }),
    });
    const { getThreadMessages } = await import("@/lib/backend/langgraph");
    const data = await getThreadMessages("t1");
    expect(mockFetch.mock.calls[0][0]).toBe("http://lg/chat/threads/t1/messages");
    expect(data.message_count).toBe(0);
  });
});

describe("chatInvoke", () => {
  it("posts the invoke payload and returns raw Response on ok", async () => {
    const fakeRes = { ok: true };
    mockFetch.mockResolvedValueOnce(fakeRes);
    const { chatInvoke } = await import("@/lib/backend/langgraph");
    const res = await chatInvoke({
      threadId: "t1",
      query: "你好",
      caseId: 9,
      clientTurnId: "turn-2",
      regenerate: true,
      selectedAssistantTurnId: "turn-1",
    });
    expect(res).toBe(fakeRes);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://lg/chat/invoke");
    expect(JSON.parse(init.body as string)).toEqual({
      thread_id: "t1",
      query: "你好",
      current_case_id: 9,
      current_debtor_id: 0,
      current_debtor_name: "",
      stream: true,
      uploaded_files: [],
      client_turn_id: "turn-2",
      regenerate: true,
      selected_assistant_turn_id: "turn-1",
    });
  });

  it("throws BackendError with body text on !ok", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 500, text: async () => "内部错误" });
    const { chatInvoke } = await import("@/lib/backend/langgraph");
    const { BackendError } = await import("@/lib/backend/http");
    const err = await chatInvoke({ threadId: "t", query: "q" }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(BackendError);
    expect((err as Error).message).toBe("内部错误");
  });
});

describe("file endpoints", () => {
  it("listCaseMaterialEvents unwraps material_events", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ material_events: [{ event_id: "e1" }] }),
    });
    const { listCaseMaterialEvents } = await import("@/lib/backend/langgraph");
    expect(await listCaseMaterialEvents(7)).toEqual([{ event_id: "e1" }]);
  });

  it("uploadChatFiles builds the multipart form", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ files: [] }) });
    const { uploadChatFiles } = await import("@/lib/backend/langgraph");
    const file = new File(["x"], "a.pdf");
    await uploadChatFiles({ caseId: 9, docCategory: "contract" }, [file]);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://lg/chat/upload-files");
    const form = init.body as FormData;
    expect(form.get("current_case_id")).toBe("9");
    expect(form.get("doc_category")).toBe("contract");
    expect(form.getAll("files")).toHaveLength(1);
  });

  it("uploadAndIngest builds the multipart form", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    const { uploadAndIngest } = await import("@/lib/backend/langgraph");
    const file = new File(["x"], "a.pdf");
    await uploadAndIngest({
      files: [file],
      current_case_id: 7,
      current_debtor_id: 8,
      current_debtor_name: "债务人",
      doc_category: "contract",
      upload_batch_id: "batch-1",
      operator_id: "u1",
      operator_name: "操作员",
    });
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://lg/files/upload-and-ingest");
    const form = init.body as FormData;
    expect(form.get("current_case_id")).toBe("7");
    expect(form.get("case_id")).toBeNull();
    expect(form.get("current_debtor_id")).toBe("8");
    expect(form.get("current_debtor_name")).toBe("债务人");
    expect(form.get("doc_category")).toBe("contract");
    expect(form.get("upload_batch_id")).toBe("batch-1");
    expect(form.get("operator_id")).toBe("u1");
    expect(form.get("operator_name")).toBe("操作员");
  });

  it("retryUploadBatch POSTs without a body and with the requested stage", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ accepted: true, retry_stage: "parse" }),
    });
    const { retryUploadBatch } = await import("@/lib/backend/langgraph");
    const result = await retryUploadBatch("batch/1", "parse");
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://lg/files/upload-batches/batch%2F1/retry?stage=parse");
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
    expect(result.accepted).toBe(true);
  });
});

// @vitest-environment jsdom
import { Suspense } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { BackendError } from "@/lib/backend/http";
import { convertDbMessage } from "@/lib/assistant-ui/convert-message";
import type { DbMessage } from "@/lib/assistant-ui/types";

async function renderPage() {
  const { default: ChatDetailPage } = await import("@/app/(main)/chat/[id]/page");
  const params = Promise.resolve({ id: "t1" });
  await act(async () => {
    render(
      <Suspense fallback={null}>
        <ChatDetailPage params={params} />
      </Suspense>
    );
    await params;
  });
}

const mockGetThreadDetail = vi.fn();
const mockGetThreadTurns = vi.fn();
const pageMocks = vi.hoisted(() => ({
  assistantChatProps: vi.fn(),
  caseIdParam: null as string | null,
}));
vi.mock("@/lib/backend/langgraph", () => ({
  getThreadDetail: (id: string) => mockGetThreadDetail(id),
  getThreadTurns: (id: string) => mockGetThreadTurns(id),
}));
vi.mock("@/components/chat/assistant-chat", () => ({
  AssistantChat: (props: unknown) => {
    pageMocks.assistantChatProps(props);
    return <div data-testid="assistant-chat" />;
  },
}));
vi.mock("@/lib/hooks/use-chat-upload", () => ({
  useChatUpload: () => ({ upload: vi.fn() }),
}));
vi.mock("@/lib/assistant-ui/chat-attachment-adapter", () => ({
  createChatAttachmentAdapter: vi.fn(),
}));
vi.mock("@/lib/assistant-ui/attachment-store", () => ({
  seedPreviewUrls: vi.fn(),
}));
vi.mock("@/lib/assistant-ui/uploaded-files-to-attachments", () => ({
  uploadedFilesToAttachments: () => ({ attachments: [], seeds: [] }),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: () => pageMocks.caseIdParam }),
}));

describe("ChatDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetThreadDetail.mockReset();
    mockGetThreadTurns.mockReset();
    sessionStorage.clear();
    pageMocks.caseIdParam = null;
    mockGetThreadDetail.mockResolvedValue({
      thread_id: "t1",
      title: "测试会话",
      case_id: 116,
      final_report_ref: "detail-report-ref",
    });
  });

  it("有待发送消息的新会话直接渲染，且不读取尚未创建的线程", async () => {
    sessionStorage.setItem(
      "pending-message-t1",
      JSON.stringify({ content: "请分析这个案件" })
    );

    await renderPage();

    expect(await screen.findByTestId("assistant-chat")).toBeTruthy();
    expect(mockGetThreadDetail).not.toHaveBeenCalled();
    expect(mockGetThreadTurns).not.toHaveBeenCalled();
    expect(pageMocks.assistantChatProps).toHaveBeenLastCalledWith(
      expect.objectContaining({
        threadId: "t1",
        initialMessages: [],
      })
    );
  });

  it.each([
    ["详情接口", "detail"],
    ["轮次接口", "turns"],
  ])("无待发送消息且%s返回 404 时显示错误与重试", async (_label, failedApi) => {
    if (failedApi === "detail") {
      mockGetThreadDetail.mockRejectedValue(new Error("404 Not Found"));
      mockGetThreadTurns.mockResolvedValue({ turns: [] });
    } else {
      mockGetThreadTurns.mockRejectedValue(new Error("404 Not Found"));
    }

    await renderPage();

    expect(await screen.findByText(/加载失败/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /重试/ })).toBeTruthy();
    expect(screen.queryByTestId("assistant-chat")).toBeNull();
  });

  it("shows a safe human-readable backend error below the generic load failure", async () => {
    mockGetThreadTurns.mockRejectedValue(
      new BackendError("年审项目 10 不存在或当前账号无权访问。", 404)
    );

    await renderPage();

    expect(await screen.findByText("会话加载失败")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain(
      "年审项目 10 不存在或当前账号无权访问。"
    );
  });

  it("maps a legacy thread-not-found response to safe annual-audit history guidance", async () => {
    mockGetThreadDetail.mockRejectedValue(
      new BackendError("Thread cross-tenant-thread not found", 404)
    );
    mockGetThreadTurns.mockResolvedValue({ turns: [] });

    await renderPage();

    const message = (await screen.findByRole("status")).textContent ?? "";
    expect(message).toContain("当前年审存储中不可用");
    expect(message).toContain("不能作为审计依据");
    expect(message).not.toContain("cross-tenant-thread");
  });

  it("does not expose an HTML server error page", async () => {
    mockGetThreadTurns.mockRejectedValue(
      new Error("<!doctype html><html><body>proxy failure</body></html>")
    );

    await renderPage();

    expect((await screen.findByRole("status")).textContent).toContain(
      "服务返回了无法安全展示的错误信息，请重试或联系管理员。"
    );
    expect(screen.queryByText(/proxy failure/)).toBeNull();
  });

  it("重试后成功则渲染会话", async () => {
    mockGetThreadTurns
      .mockRejectedValueOnce(new Error("网络错误"))
      .mockResolvedValueOnce({ turns: [] });
    await renderPage();

    const retry = await screen.findByRole("button", { name: /重试/ });
    fireEvent.click(retry);
    await waitFor(() => expect(screen.getByTestId("assistant-chat")).toBeTruthy());
  });

  it("线程为空时正常渲染会话(不误判为错误)", async () => {
    mockGetThreadTurns.mockResolvedValue({ turns: [] });
    await renderPage();
    expect(await screen.findByTestId("assistant-chat")).toBeTruthy();
    expect(screen.queryByText(/加载失败/)).toBeNull();
  });

  it("非法 caseId 参数不覆盖详情案件，并传递权威报告引用", async () => {
    pageMocks.caseIdParam = "not-a-number";
    mockGetThreadTurns.mockResolvedValue({ turns: [] });
    await renderPage();
    await screen.findByTestId("assistant-chat");

    expect(pageMocks.assistantChatProps).toHaveBeenLastCalledWith(
      expect.objectContaining({
        caseId: 116,
        initialReportRef: "detail-report-ref",
      })
    );
  });

  it("restores an assistant version's own evidence snapshot after refresh", async () => {
    mockGetThreadTurns.mockResolvedValue({
      turns: [
        {
          turn_id: "turn-1",
          user: {
            content: "generate annual audit",
            created_at: "2026-08-14T10:00:00+08:00",
            uploaded_files: [],
          },
          assistants: [
            {
              turn_id: "turn-1",
              content: "first report [[cite:1]]",
              created_at: "2026-08-14T10:01:00+08:00",
              final_report_ref: "report:first",
              intent: "full_audit",
              case_id: 116,
              version: 1,
              route_decision: { capability: "audit.full" },
              trace_items: [{ citation_id: "1", claim_id: 701 }],
              citation_coverage: { total_claims: 1, cited_claims: 1 },
              response_analysis_runs: [
                { tool_name: "sales", analysis_type: "sales", analysis_run_id: 31 },
              ],
              unresolved_relations: [{ relation_key: "r-first" }],
              unresolved_claims: [{ claim_text: "first missing evidence" }],
            },
            {
              turn_id: "turn-1",
              content: "second report",
              created_at: "2026-08-14T10:02:00+08:00",
              final_report_ref: "report:second",
              intent: "full_audit",
              case_id: 116,
              version: 2,
              route_decision: null,
              trace_items: [],
              citation_coverage: {},
              response_analysis_runs: [],
              unresolved_relations: [],
              unresolved_claims: [],
              attachment_job: {
                job_id: "job-second",
                case_id: 116,
                assistant_turn_id: "turn-1",
                report_id: 88,
                report_version: 2,
                template_version_id: "template-v2",
                template_version_label: "v2",
                delivery_level: "review_draft",
              },
            },
          ],
        },
      ],
    });

    await renderPage();
    await screen.findByTestId("assistant-chat");

    const props = pageMocks.assistantChatProps.mock.calls.at(-1)?.[0] as {
      initialMessages: Array<{ role: string; metadata: Record<string, unknown> | null }>;
    };
    const assistant = props.initialMessages.find(
      (message) => message.role === "assistant"
    );

    expect(assistant?.metadata).toMatchObject({
      final_report_ref: "report:second",
      trace_items: [],
      response_analysis_runs: [],
      attachment_job: {
        job_id: "job-second",
        report_version: 2,
        template_version_id: "template-v2",
      },
      custom: {
        finalReportRef: "report:second",
        traceItems: [],
        citationCoverage: {},
        responseAnalysisRuns: [],
        unresolvedRelations: [],
        unresolvedClaims: [],
        attachmentJob: {
          job_id: "job-second",
          report_version: 2,
          template_version_id: "template-v2",
        },
      },
    });
  });

  it("keeps each displayed historical turn bound to its own persisted attachment job", async () => {
    const job = (jobId: string, turnId: string, reportVersion: number) => ({
      job_id: jobId,
      case_id: 116,
      assistant_turn_id: turnId,
      report_id: 88,
      report_version: reportVersion,
      template_version_id: `template-v${reportVersion}`,
      template_version_label: `v${reportVersion}`,
      delivery_level: "review_draft",
    });
    const assistant = (
      turnId: string,
      content: string,
      version: number,
      attachmentJob: ReturnType<typeof job> | null
    ) => ({
      turn_id: turnId,
      content,
      created_at: `2026-08-14T10:0${version}:00+08:00`,
      final_report_ref: `report:${turnId}:v${version}`,
      intent: "full_audit",
      case_id: 116,
      version,
      route_decision: null,
      trace_items: [],
      citation_coverage: {},
      response_analysis_runs: [],
      unresolved_relations: [],
      unresolved_claims: [],
      attachment_job: attachmentJob,
    });

    mockGetThreadTurns.mockResolvedValue({
      turns: [
        {
          turn_id: "turn-1",
          user: {
            content: "first request",
            created_at: "2026-08-14T10:00:00+08:00",
            uploaded_files: [],
          },
          assistants: [
            assistant("turn-1", "superseded reply", 1, job("job-superseded", "turn-1", 1)),
            assistant("turn-1", "displayed first reply", 2, job("job-turn-1", "turn-1", 2)),
          ],
        },
        {
          turn_id: "turn-2",
          user: {
            content: "second request",
            created_at: "2026-08-14T11:00:00+08:00",
            uploaded_files: [],
          },
          assistants: [
            assistant("turn-2", "displayed second reply", 1, job("job-turn-2", "turn-2", 3)),
          ],
        },
        {
          turn_id: "turn-3",
          user: {
            content: "explain only",
            created_at: "2026-08-14T12:00:00+08:00",
            uploaded_files: [],
          },
          assistants: [assistant("turn-3", "reply without artifacts", 1, null)],
        },
      ],
    });

    await renderPage();
    await screen.findByTestId("assistant-chat");

    const props = pageMocks.assistantChatProps.mock.calls.at(-1)?.[0] as {
      initialMessages: DbMessage[];
    };
    const assistants = props.initialMessages.filter((message) => message.role === "assistant");

    expect(assistants.map((message) => message.content)).toEqual([
      "displayed first reply",
      "displayed second reply",
      "reply without artifacts",
    ]);
    expect(assistants.map((message) => message.metadata?.attachment_job)).toEqual([
      expect.objectContaining({ job_id: "job-turn-1", report_version: 2 }),
      expect.objectContaining({ job_id: "job-turn-2", report_version: 3 }),
      null,
    ]);
    expect(JSON.stringify(props.initialMessages)).not.toContain("job-superseded");

    expect(
      assistants.map(
        (message) => convertDbMessage(message).metadata?.custom?.attachmentJob ?? null
      )
    ).toEqual([
      expect.objectContaining({ job_id: "job-turn-1", report_version: 2 }),
      expect.objectContaining({ job_id: "job-turn-2", report_version: 3 }),
      null,
    ]);
  });
});

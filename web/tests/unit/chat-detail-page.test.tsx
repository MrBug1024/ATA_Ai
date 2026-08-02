// @vitest-environment jsdom
import { Suspense } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";

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
});

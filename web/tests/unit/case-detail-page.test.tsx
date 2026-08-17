// @vitest-environment jsdom
import { beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const pageMocks = vi.hoisted(() => ({
  conversations: [] as Array<{
    thread_id: string;
    updated_at: string | null;
  }>,
  conversationsLoading: false,
  conversationArgs: vi.fn(),
  getThreadDetail: vi.fn(),
  allowedModules: ["corrections", "graph"] as string[],
}));

vi.mock("@/lib/hooks/use-cases", () => ({
  useCases: () => ({
    cases: [{ case_id: 116, case_name: "测试年审项目", case_type: "年度财务报表审计", entity_name: "测试科技有限公司", status: "planning" }],
    isLoading: false, error: null, total: 1, page: 1, setPage: vi.fn(), keyword: "", setKeyword: vi.fn(), retry: vi.fn(), refresh: vi.fn(),
  }),
}));
vi.mock("@/lib/hooks/use-case-material-events", () => ({
  useCaseMaterialEvents: () => ({ events: [], isLoading: false, error: null, refresh: vi.fn() }),
}));
vi.mock("@/lib/hooks/use-evolution-items", () => ({
  useEvolutionItems: () => ({ items: [], isLoading: false, error: null, refresh: vi.fn() }),
}));
vi.mock("@/lib/hooks/use-unresolved-items", () => ({
  useUnresolvedItems: () => ({ data: null, isLoading: false, error: null, refresh: vi.fn() }),
}));
vi.mock("@/lib/hooks/use-case-doc-categories", () => ({
  useCaseDocCategories: () => ({ caseDocCategories: null, isLoading: false, error: null }),
}));
vi.mock("@/lib/hooks/use-conversations", () => ({
  useConversations: (args: unknown, enabled: boolean) => {
    pageMocks.conversationArgs(args, enabled);
    return {
      conversations: pageMocks.conversations,
      isLoading: pageMocks.conversationsLoading,
      error: null,
      refresh: vi.fn(),
    };
  },
}));
vi.mock("@/lib/hooks/use-auth", () => ({
  useAuth: () => ({
    user: {
      authenticated: true,
      allowed_modules: pageMocks.allowedModules,
    },
  }),
}));
vi.mock("@/lib/backend/langgraph", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/backend/langgraph")>();
  return {
    ...actual,
    getThreadDetail: (...args: Parameters<typeof actual.getThreadDetail>) =>
      pageMocks.getThreadDetail(...args),
  };
});
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "116" }),
}));
vi.mock("@/lib/stores/graph-modal", () => ({
  useGraphModalStore: (sel?: (s: { openModal: () => void }) => unknown) => {
    const state = { openModal: vi.fn() };
    return sel ? sel(state) : state;
  },
}));
vi.mock("@/components/knowledge-graph/demo-validation-gate", () => ({
  DemoValidationGate: () => null,
}));
vi.mock("@/components/knowledge-graph/material-event-timeline", () => ({
  MaterialEventTimeline: () => <div data-testid="material-events" />,
}));
vi.mock("@/components/knowledge-graph/evolution-timeline", () => ({
  EvolutionTimeline: () => <div data-testid="evolution" />,
}));
vi.mock("@/components/knowledge-graph/unresolved-items-panel", () => ({
  UnresolvedItemsPanel: () => <div data-testid="unresolved" />,
}));
vi.mock("@/components/cases/corrections-panel", () => ({
  CorrectionsPanel: () => <div data-testid="corrections-panel" />,
}));
vi.mock("@/components/cases/annual-audit-execution-panel", () => ({
  AnnualAuditExecutionPanel: () => <div data-testid="annual-audit-execution" />,
}));
vi.mock("@/components/ui/sidebar", () => ({
  SidebarTrigger: () => null,
}));

describe("CaseDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pageMocks.conversations = [];
    pageMocks.conversationsLoading = false;
    pageMocks.allowedModules = ["corrections", "graph"];
    pageMocks.getThreadDetail.mockResolvedValue({ final_report_ref: "" });
  });

  it("renders case name in header", async () => {
    const { default: Page } = await import("@/app/(main)/cases/[id]/page");
    render(<Page />);
    expect(screen.getByText("测试年审项目")).toBeTruthy();
  });

  it("renders the analysis and governance tabs", async () => {
    const { default: Page } = await import("@/app/(main)/cases/[id]/page");
    render(<Page />);
    expect(screen.getByText("资料处理记录")).toBeTruthy();
    expect(screen.getByText("审计结论演进")).toBeTruthy();
    expect(screen.getByText("待补资料")).toBeTruthy();
    expect(screen.getByText("审计执行")).toBeTruthy();
    expect(screen.getByText("审计调整")).toBeTruthy();
    expect(screen.queryByText("回款管理")).toBeNull();
    expect(screen.queryByText("时效看板")).toBeNull();
  });

  it("renders MaterialEventTimeline in default tab", async () => {
    const { default: Page } = await import("@/app/(main)/cases/[id]/page");
    render(<Page />);
    expect(screen.getByTestId("material-events")).toBeTruthy();
  });

  it("opens the annual correction panel from its tab", async () => {
    const { default: Page } = await import("@/app/(main)/cases/[id]/page");
    render(<Page />);

    fireEvent.mouseDown(screen.getByRole("tab", { name: "审计调整" }), {
      button: 0,
      ctrlKey: false,
    });
    expect(screen.getByTestId("corrections-panel")).toBeTruthy();
  });

  it("opens the annual audit execution workbench from its tab", async () => {
    const { default: Page } = await import("@/app/(main)/cases/[id]/page");
    render(<Page />);

    fireEvent.mouseDown(screen.getByRole("tab", { name: "审计执行" }), {
      button: 0,
      ctrlKey: false,
    });
    expect(screen.getByTestId("annual-audit-execution")).toBeTruthy();
  });

  it("requests the maximum page and selects the newest thread client-side", async () => {
    pageMocks.conversations = [
      { thread_id: "older", updated_at: "2026-07-01T00:00:00Z" },
      { thread_id: "newer", updated_at: "2026-07-16T00:00:00Z" },
    ];
    const { default: Page } = await import("@/app/(main)/cases/[id]/page");
    render(<Page />);

    expect(pageMocks.conversationArgs).toHaveBeenCalledWith(
      { caseId: 116, limit: 200 },
      true
    );
    await waitFor(() => expect(pageMocks.getThreadDetail).toHaveBeenCalledWith("newer"));
  });

  it("按 allowed_modules 隐藏受限功能并停止对应数据请求", async () => {
    pageMocks.allowedModules = [];
    const { default: Page } = await import("@/app/(main)/cases/[id]/page");
    render(<Page />);

    expect(screen.queryByText("查看图谱")).toBeNull();
    expect(screen.queryByRole("tab", { name: "审计调整" })).toBeNull();
    expect(pageMocks.conversationArgs).toHaveBeenLastCalledWith(
      { caseId: 116, limit: 200 },
      false
    );
    expect(pageMocks.getThreadDetail).not.toHaveBeenCalled();
  });
});

// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  allowedModules: [] as string[],
}));

vi.mock("@assistant-ui/react", () => ({
  AssistantRuntimeProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));
vi.mock("@/lib/assistant-ui/use-langgraph-runtime", () => ({
  useLanggraphRuntime: () => ({
    runtime: {},
    thinkingMap: new Map(),
    reportRef: "report-1",
  }),
}));
vi.mock("@/lib/hooks/use-auth", () => ({
  useAuth: () => ({
    user: {
      authenticated: true,
      allowed_modules: mocks.allowedModules,
    },
  }),
}));
vi.mock("@/lib/stores/graph-modal", () => ({
  useGraphModalStore: (selector: (state: { openModal: () => void }) => unknown) =>
    selector({ openModal: vi.fn() }),
}));
vi.mock("@/components/chat/chatgpt-thread", () => ({
  ChatThread: () => <div data-testid="chat-thread" />,
}));
vi.mock("@/components/knowledge-graph/evidence-drawer", () => ({
  EvidenceDrawer: () => <div data-testid="evidence-drawer" />,
}));
vi.mock("@/components/shared/preview-host", () => ({
  PreviewProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PreviewSidePanel: () => null,
}));
vi.mock("@/components/ui/sidebar", () => ({
  SidebarTrigger: () => null,
}));

describe("AssistantChat graph permissions", () => {
  beforeEach(() => {
    mocks.allowedModules = [];
  });

  it("没有 graph 模块时不挂载图谱入口和证据抽屉", async () => {
    const { AssistantChat } = await import("@/components/chat/assistant-chat");
    render(<AssistantChat threadId="t1" caseId={116} />);

    expect(screen.queryByRole("button", { name: "图谱" })).toBeNull();
    expect(screen.queryByTestId("evidence-drawer")).toBeNull();
  });

  it("获得 graph 模块后显示图谱入口和证据抽屉", async () => {
    mocks.allowedModules = ["graph"];
    const { AssistantChat } = await import("@/components/chat/assistant-chat");
    render(<AssistantChat threadId="t1" caseId={116} />);

    expect(screen.getByRole("button", { name: "图谱" })).toBeTruthy();
    expect(screen.getByTestId("evidence-drawer")).toBeTruthy();
  });
});

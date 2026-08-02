// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MermaidDiagram } from "@/components/assistant-ui/mermaid-diagram";

const { initialize, renderDiagram } = vi.hoisted(() => ({
  initialize: vi.fn(),
  renderDiagram: vi.fn(),
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "dark" }),
}));

vi.mock("mermaid", () => ({
  default: {
    initialize,
    render: renderDiagram,
  },
}));

describe("MermaidDiagram", () => {
  beforeEach(() => {
    initialize.mockReset();
    renderDiagram.mockReset();
    renderDiagram.mockResolvedValue({
      svg: '<svg role="img" aria-label="rendered diagram"></svg>',
    });
  });

  it("uses Mermaid strict security and renders the trimmed diagram", async () => {
    render(<MermaidDiagram code={"  graph TD\nA-->B  "} />);

    await waitFor(() => {
      expect(initialize).toHaveBeenCalledWith({
        startOnLoad: false,
        theme: "dark",
        fontFamily: "inherit",
        securityLevel: "strict",
      });
    });
    expect(renderDiagram).toHaveBeenCalledWith(
      expect.stringMatching(/^mermaid-/),
      "graph TD\nA-->B",
    );
    expect(await screen.findByRole("img", { name: "rendered diagram" })).not.toBeNull();
  });
});

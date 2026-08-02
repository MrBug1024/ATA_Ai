// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { act } from "react";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);
vi.stubEnv("NEXT_PUBLIC_LANGGRAPH_API_BASE_URL", "http://test");

beforeEach(() => { mockFetch.mockReset(); });

describe("useGraphSubgraph", () => {
  it("returns empty nodes/edges before trigger", async () => {
    const { useGraphSubgraph } = await import("@/lib/hooks/use-graph-subgraph");
    const { result } = renderHook(() => useGraphSubgraph());
    expect(result.current.data).toBeNull();
  });

  it("posts to /graph/subgraph and returns nodes/edges", async () => {
    const payload = { case_id: 116, nodes: [{ id: "e-1", entity_id: 1, label: "A", entity_type: "company", risk_level: "low" }], edges: [] };
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => payload });
    const { useGraphSubgraph } = await import("@/lib/hooks/use-graph-subgraph");
    const { result } = renderHook(() => useGraphSubgraph());

    await act(async () => {
      await result.current.fetch({ case_id: 116, center_entity_id: 1, depth: 2 });
    });

    await waitFor(() => expect(result.current.data?.nodes).toHaveLength(1));
    expect(mockFetch).toHaveBeenCalledWith(
      "http://test/graph/subgraph",
      expect.objectContaining({ method: "POST" })
    );
  });
});

describe("useRelationEvidence", () => {
  it("posts to /graph/relation-evidence and returns trace_items", async () => {
    const payload = { case_id: 116, relation_id: 77, trace_items: [{ citation_id: "1", claim_id: 1, claim_type: "t", claim_text: "c", confidence: 0.9, evidences: [] }] };
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => payload });
    const { useRelationEvidence } = await import("@/lib/hooks/use-relation-evidence");
    const { result } = renderHook(() => useRelationEvidence());

    await act(async () => {
      await result.current.fetch({ case_id: 116, relation_id: 77 });
    });

    await waitFor(() => expect(result.current.data?.trace_items).toHaveLength(1));
  });
});

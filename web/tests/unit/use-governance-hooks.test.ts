// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { act } from "react";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);
vi.stubEnv("NEXT_PUBLIC_LANGGRAPH_API_BASE_URL", "http://test");

beforeEach(() => { mockFetch.mockReset(); });

describe("useEvolutionItems", () => {
  it("does not fetch when caseId is null", async () => {
    const { useEvolutionItems } = await import("@/lib/hooks/use-evolution-items");
    renderHook(() => useEvolutionItems(null));
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("fetches evolution items for a given caseId", async () => {
    const payload = { case_id: 116, action: "", evolution_items: [{ id: 1, case_id: 116, action: "ADD", new_claim_text: "new", new_claim_type: "t", superseded_claim_id: null, superseded_claim_type: "", superseded_claim_text: "", new_claim_id: 2, new_relation_id: null, superseded_relation_id: null, rationale: "", evidence_chunk_ids: [], upload_batch_id: "b1", batch_name: "B1", doc_category: "d", material_event_id: "m1", material_event_status: "completed", material_event_type: "supplement_upload", evidences: [], created_at: null }] };
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => payload });
    const { useEvolutionItems } = await import("@/lib/hooks/use-evolution-items");
    const { result } = renderHook(() => useEvolutionItems(116));
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    expect(result.current.items[0].action).toBe("ADD");
  });
});

describe("useUnresolvedItems", () => {
  it("fetches unresolved items", async () => {
    const payload = { case_id: 116, upload_batch_id: "", status: "pending", unresolved_relation_count: 1, unresolved_claim_count: 0, unresolved_relations: [{ id: 1, case_id: 116, extraction_run_id: 1, upload_batch_id: "b", material_event_id: "m", item_type: "relation", relation_key: "k", relation_type: "guarantee", relation_label: "担保", entity_temp_id: "e1", relation_temp_id: "r1", missing_dependencies: ["from_entity:x"], reason: "缺少实体", status: "pending", payload: {}, created_at: null }], unresolved_claims: [] };
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => payload });
    const { useUnresolvedItems } = await import("@/lib/hooks/use-unresolved-items");
    const { result } = renderHook(() => useUnresolvedItems(116));
    await waitFor(() => expect(result.current.data?.unresolved_relation_count).toBe(1));
  });
});

describe("useDemoCaseValidate", () => {
  it("returns null before trigger", async () => {
    const { useDemoCaseValidate } = await import("@/lib/hooks/use-demo-case-validate");
    const { result } = renderHook(() => useDemoCaseValidate());
    expect(result.current.data).toBeNull();
  });

  it("posts validate request and returns ready status", async () => {
    const payload = { case_id: 116, report_ref: "r", ready: true, total_citations: 3, passed_citations: 3, failed_citations: 0, checks: [], issues: [] };
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => payload });
    const { useDemoCaseValidate } = await import("@/lib/hooks/use-demo-case-validate");
    const { result } = renderHook(() => useDemoCaseValidate());

    await act(async () => {
      await result.current.validate({ case_id: 116, report_ref: "r" });
    });

    await waitFor(() => expect(result.current.data?.ready).toBe(true));
  });
});

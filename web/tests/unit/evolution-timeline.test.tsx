// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import type { EvolutionItem } from "@/lib/types/knowledge-graph";

const addItem: EvolutionItem = {
  id: 1, case_id: 116, action: "ADD", new_claim_id: 2, new_claim_type: "debt",
  new_claim_text: "晨光煤矿是债务人", superseded_claim_id: null, superseded_claim_type: "",
  superseded_claim_text: "", new_relation_id: null, superseded_relation_id: null,
  rationale: "", evidence_chunk_ids: [], upload_batch_id: "b1", batch_name: "第一批",
  doc_category: "章程", material_event_id: "m1", material_event_status: "completed",
  material_event_type: "supplement_upload", evidences: [], created_at: "2026-06-01T10:00:00Z",
};

const overrideItem: EvolutionItem = {
  ...addItem, id: 2, action: "OVERRIDE",
  new_claim_text: "晨光煤矿是主债务人",
  superseded_claim_text: "晨光煤矿是债务人",
  rationale: "补充材料确认主债务人",
};

describe("EvolutionTimeline", () => {
  it("renders ADD item with new badge", async () => {
    const { EvolutionTimeline } = await import("@/components/knowledge-graph/evolution-timeline");
    render(<EvolutionTimeline items={[addItem]} isLoading={false} />);
    expect(screen.getByText("晨光煤矿是债务人")).toBeTruthy();
    expect(screen.getAllByText("新增").length).toBeGreaterThan(0);
  });

  it("renders OVERRIDE item with both old and new texts", async () => {
    const { EvolutionTimeline } = await import("@/components/knowledge-graph/evolution-timeline");
    render(<EvolutionTimeline items={[overrideItem]} isLoading={false} />);
    expect(screen.getByText("晨光煤矿是主债务人")).toBeTruthy();
    expect(screen.getByText("晨光煤矿是债务人")).toBeTruthy();
    expect(screen.getAllByText("替代").length).toBeGreaterThan(0);
  });

  it("shows empty state", async () => {
    const { EvolutionTimeline } = await import("@/components/knowledge-graph/evolution-timeline");
    render(<EvolutionTimeline items={[]} isLoading={false} />);
    expect(screen.getByText(/暂无结论演进/)).toBeTruthy();
  });

  it("shows loading state", async () => {
    const { EvolutionTimeline } = await import("@/components/knowledge-graph/evolution-timeline");
    render(<EvolutionTimeline items={[]} isLoading={true} />);
    expect(screen.getByText(/加载中/)).toBeTruthy();
  });
});

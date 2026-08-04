// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import type { EvolutionItem } from "@/lib/types/knowledge-graph";

const addItem: EvolutionItem = {
  id: 1,
  case_id: 7,
  action: "ADD",
  new_claim_id: 2,
  new_claim_type: "audit_balance",
  new_claim_text: "应收账款未经审计余额为1200万元",
  superseded_claim_id: null,
  superseded_claim_type: "",
  superseded_claim_text: "",
  new_relation_id: null,
  superseded_relation_id: null,
  rationale: "",
  evidence_chunk_ids: [],
  upload_batch_id: "annual-batch-1",
  batch_name: "第一批",
  doc_category: "trial_balance",
  material_event_id: "annual-event-1",
  material_event_status: "completed",
  material_event_type: "supplement_upload",
  evidences: [],
  created_at: "2026-06-01T10:00:00Z",
};

const overrideItem: EvolutionItem = {
  ...addItem,
  id: 2,
  action: "OVERRIDE",
  new_claim_text: "应收账款审定余额为1180万元",
  superseded_claim_text: "应收账款未经审计余额为1200万元",
  rationale: "审计调整分录确认余额变化",
};

describe("EvolutionTimeline", () => {
  it("renders an added audit fact", async () => {
    const { EvolutionTimeline } = await import(
      "@/components/knowledge-graph/evolution-timeline"
    );
    render(<EvolutionTimeline items={[addItem]} isLoading={false} />);
    expect(screen.getByText("应收账款未经审计余额为1200万元")).toBeTruthy();
    expect(screen.getAllByText("新增").length).toBeGreaterThan(0);
  });

  it("renders both superseded and replacement audit facts", async () => {
    const { EvolutionTimeline } = await import(
      "@/components/knowledge-graph/evolution-timeline"
    );
    render(<EvolutionTimeline items={[overrideItem]} isLoading={false} />);
    expect(screen.getByText("应收账款审定余额为1180万元")).toBeTruthy();
    expect(screen.getByText("应收账款未经审计余额为1200万元")).toBeTruthy();
    expect(screen.getAllByText("替代").length).toBeGreaterThan(0);
  });

  it("shows empty state", async () => {
    const { EvolutionTimeline } = await import(
      "@/components/knowledge-graph/evolution-timeline"
    );
    render(<EvolutionTimeline items={[]} isLoading={false} />);
    expect(screen.getByText(/暂无结论演进/)).toBeTruthy();
  });

  it("shows loading state", async () => {
    const { EvolutionTimeline } = await import(
      "@/components/knowledge-graph/evolution-timeline"
    );
    render(<EvolutionTimeline items={[]} isLoading={true} />);
    expect(screen.getByText(/加载中/)).toBeTruthy();
  });
});

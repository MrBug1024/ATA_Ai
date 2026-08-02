// tests/unit/unresolved-items-panel.test.tsx
// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import type { UnresolvedItemsResponse } from "@/lib/types/knowledge-graph";

const mockData: UnresolvedItemsResponse = {
  case_id: 116,
  upload_batch_id: "",
  status: "pending",
  unresolved_relation_count: 1,
  unresolved_claim_count: 1,
  unresolved_relations: [{
    id: 1, case_id: 116, extraction_run_id: 1, upload_batch_id: "b1",
    material_event_id: "m1", item_type: "relation", relation_key: "k1",
    relation_type: "guarantee", relation_label: "担保", entity_temp_id: "e1",
    relation_temp_id: "r1", missing_dependencies: ["from_entity:晨光煤矿"],
    reason: "缺少实体：晨光煤矿", status: "pending", payload: {}, created_at: null,
  }],
  unresolved_claims: [{
    id: 2, case_id: 116, extraction_run_id: 1, upload_batch_id: "b1",
    material_event_id: "m1", item_type: "claim", entity_name: "张某某",
    entity_key: "k2", relation_key: "r2", claim_type: "debt",
    claim_text: "张某某是担保人", missing_dependencies: ["relation:guarantee"],
    reason: "缺少关系：guarantee", status: "pending", payload: {}, created_at: null,
  }],
};

describe("UnresolvedItemsPanel", () => {
  it("shows summary counts", async () => {
    const { UnresolvedItemsPanel } = await import("@/components/knowledge-graph/unresolved-items-panel");
    render(<UnresolvedItemsPanel data={mockData} isLoading={false} />);
    expect(screen.getByText(/1 条关系未决/)).toBeTruthy();
    expect(screen.getByText(/1 条断言未决/)).toBeTruthy();
  });

  it("shows missing dependency tag for relations", async () => {
    const { UnresolvedItemsPanel } = await import("@/components/knowledge-graph/unresolved-items-panel");
    render(<UnresolvedItemsPanel data={mockData} isLoading={false} />);
    expect(screen.getByText("from_entity:晨光煤矿")).toBeTruthy();
  });

  it("shows missing dependency tag for claims", async () => {
    const { UnresolvedItemsPanel } = await import("@/components/knowledge-graph/unresolved-items-panel");
    render(<UnresolvedItemsPanel data={mockData} isLoading={false} />);
    expect(screen.getByText("relation:guarantee")).toBeTruthy();
  });

  it("shows all-resolved empty state when counts are zero", async () => {
    const { UnresolvedItemsPanel } = await import("@/components/knowledge-graph/unresolved-items-panel");
    const empty: UnresolvedItemsResponse = {
      ...mockData,
      unresolved_relation_count: 0,
      unresolved_claim_count: 0,
      unresolved_relations: [],
      unresolved_claims: [],
    };
    render(<UnresolvedItemsPanel data={empty} isLoading={false} />);
    expect(screen.getByText(/全部依赖已补齐/)).toBeTruthy();
  });

  it("renders nothing when data is null", async () => {
    const { UnresolvedItemsPanel } = await import("@/components/knowledge-graph/unresolved-items-panel");
    const { container } = render(<UnresolvedItemsPanel data={null} isLoading={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows loading state", async () => {
    const { UnresolvedItemsPanel } = await import("@/components/knowledge-graph/unresolved-items-panel");
    render(<UnresolvedItemsPanel data={null} isLoading={true} />);
    expect(screen.getByText(/加载中/)).toBeTruthy();
  });
});

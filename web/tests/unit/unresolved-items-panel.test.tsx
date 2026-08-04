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
    relation_temp_id: "r1", missing_dependencies: ["from_entity:示例制造有限公司"],
    reason: "缺少实体：示例制造有限公司", status: "pending", payload: {}, created_at: null,
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
    expect(screen.getByText("from_entity:示例制造有限公司")).toBeTruthy();
  });

  it("shows missing dependency tag for claims", async () => {
    const { UnresolvedItemsPanel } = await import("@/components/knowledge-graph/unresolved-items-panel");
    render(<UnresolvedItemsPanel data={mockData} isLoading={false} />);
    expect(screen.getByText("relation:guarantee")).toBeTruthy();
  });

  it("distinguishes an empty graph queue from material completeness", async () => {
    const { UnresolvedItemsPanel } = await import("@/components/knowledge-graph/unresolved-items-panel");
    const empty: UnresolvedItemsResponse = {
      ...mockData,
      unresolved_relation_count: 0,
      unresolved_claim_count: 0,
      unresolved_relations: [],
      unresolved_claims: [],
    };
    render(<UnresolvedItemsPanel data={empty} isLoading={false} />);
    expect(screen.getByText(/无图谱未决关系或断言/)).toBeTruthy();
    expect(screen.queryByText(/全部依赖已补齐/)).toBeNull();
  });

  it("shows missing annual material categories", async () => {
    const { UnresolvedItemsPanel } = await import("@/components/knowledge-graph/unresolved-items-panel");
    render(
      <UnresolvedItemsPanel
        data={{
          ...mockData,
          unresolved_relation_count: 0,
          unresolved_claim_count: 0,
          unresolved_relations: [],
          unresolved_claims: [],
        }}
        isLoading={false}
        caseDocCategories={{
          case_id: 116,
          missing_categories: ["journal_entries"],
          categories: [
            {
              code: "journal_entries",
              name: "序时账/凭证明细",
              uploaded: false,
              file_count: 0,
              record_count: 0,
              last_uploaded_at: null,
            },
          ],
        }}
      />
    );
    expect(screen.getByText("序时账/凭证明细")).toBeTruthy();
    expect(screen.getByText(/尚未上传可识别资料/)).toBeTruthy();
    expect(screen.getByTestId("material-coverage-summary").textContent).toContain("已识别 0 类资料");
    expect(screen.getByTestId("material-coverage-summary").textContent).toContain("仍缺 1 类资料");
  });

  it("shows available and missing material categories together", async () => {
    const { UnresolvedItemsPanel } = await import("@/components/knowledge-graph/unresolved-items-panel");
    render(
      <UnresolvedItemsPanel
        data={null}
        isLoading={false}
        caseDocCategories={{
          case_id: 116,
          missing_categories: ["bank_statements"],
          categories: [
            {
              code: "receivables",
              name: "应收账款明细",
              uploaded: true,
              file_count: 1,
              record_count: 4780,
              last_uploaded_at: "2026-08-03T20:00:00",
            },
            {
              code: "bank_statements",
              name: "银行流水",
              uploaded: false,
              file_count: 0,
              record_count: 0,
              last_uploaded_at: null,
            },
          ],
        }}
      />
    );
    expect(screen.getByText("当前已有资料类别")).toBeTruthy();
    expect(screen.getByText("应收账款明细")).toBeTruthy();
    expect(screen.getByText(/1 个文件 · 4780 条结构化记录/)).toBeTruthy();
    expect(screen.getByText("仍缺资料类别")).toBeTruthy();
    expect(screen.getByText("银行流水")).toBeTruthy();
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

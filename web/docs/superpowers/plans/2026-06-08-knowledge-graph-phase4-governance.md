# Knowledge Graph — Phase 4: Case Governance Page

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Prerequisite:** Phase 1 complete (types, hooks, stores exist).

**Goal:** A new `/cases/[id]` page with three tabs — 材料事件 / 结论演进 / 未决补件 — plus a demo-case validation gate in the page header. Accessible from the cases list via a "治理 →" link.

**Architecture:** Each tab is a standalone component consuming a Phase 1 hook. `DemoValidationGate` uses `useDemoCaseValidate` + `useConversations` to derive `reportRef`. The page itself is a standard Next.js dynamic route.

**Tech Stack:** Next.js app router, shadcn Tabs, Vitest + Testing Library

---

### Task 13: DemoValidationGate

**Files:**
- Create: `components/knowledge-graph/demo-validation-gate.tsx`
- Test: `tests/unit/demo-validation-gate.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/demo-validation-gate.test.tsx
// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";

const mockValidate = vi.fn();
vi.mock("@/lib/hooks/use-demo-case-validate", () => ({
  useDemoCaseValidate: () => ({
    data: null, isMutating: false, error: null, validate: mockValidate, reset: vi.fn(),
  }),
}));

describe("DemoValidationGate", () => {
  it("shows Validate button when reportRef is provided", async () => {
    const { DemoValidationGate } = await import("@/components/knowledge-graph/demo-validation-gate");
    render(<DemoValidationGate caseId={116} reportRef="final_report:demo-116" />);
    expect(screen.getByRole("button", { name: /验收/ })).toBeTruthy();
  });

  it("does not render when reportRef is null", async () => {
    const { DemoValidationGate } = await import("@/components/knowledge-graph/demo-validation-gate");
    const { container } = render(<DemoValidationGate caseId={116} reportRef={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("calls validate with correct args on button click", async () => {
    const { DemoValidationGate } = await import("@/components/knowledge-graph/demo-validation-gate");
    render(<DemoValidationGate caseId={116} reportRef="final_report:demo-116" />);
    fireEvent.click(screen.getByRole("button", { name: /验收/ }));
    expect(mockValidate).toHaveBeenCalledWith({ case_id: 116, report_ref: "final_report:demo-116" });
  });

  it("shows ready badge when validation passes", async () => {
    vi.doMock("@/lib/hooks/use-demo-case-validate", () => ({
      useDemoCaseValidate: () => ({
        data: { ready: true, total_citations: 3, passed_citations: 3, failed_citations: 0, checks: [], issues: [], case_id: 116, report_ref: "r" },
        isMutating: false, error: null, validate: mockValidate, reset: vi.fn(),
      }),
    }));
    const { DemoValidationGate } = await import("@/components/knowledge-graph/demo-validation-gate");
    render(<DemoValidationGate caseId={116} reportRef="r" />);
    expect(screen.getByText(/可发布/)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pnpm test tests/unit/demo-validation-gate.test.tsx
```

Expected: `Cannot find module '@/components/knowledge-graph/demo-validation-gate'`

- [ ] **Step 3: Implement `demo-validation-gate.tsx`**

```tsx
// components/knowledge-graph/demo-validation-gate.tsx
"use client";

import { CheckCircle, XCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useDemoCaseValidate } from "@/lib/hooks/use-demo-case-validate";

interface DemoValidationGateProps {
  caseId: number;
  reportRef: string | null;
}

export function DemoValidationGate({ caseId, reportRef }: DemoValidationGateProps) {
  const { data, isMutating, validate } = useDemoCaseValidate();

  if (!reportRef) return null;

  return (
    <div className="flex items-center gap-2">
      {!data && (
        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1.5 text-xs"
          disabled={isMutating}
          onClick={() => validate({ case_id: caseId, report_ref: reportRef })}
        >
          {isMutating && <Loader2 className="h-3 w-3 animate-spin" />}
          验收
        </Button>
      )}

      {data?.ready && (
        <div className="flex items-center gap-1.5">
          <span className="flex items-center gap-1 rounded-md bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-500">
            <CheckCircle className="h-3 w-3" />
            ✓ 可发布
          </span>
          <Button size="sm" className="h-7 text-xs">发布</Button>
        </div>
      )}

      {data && !data.ready && (
        <div className="space-y-1">
          <span className="flex items-center gap-1 rounded-md bg-destructive/10 px-2 py-0.5 text-xs text-destructive">
            <XCircle className="h-3 w-3" />
            {data.failed_citations} 条角标失败
          </span>
          <div className="max-h-32 overflow-y-auto space-y-0.5">
            {data.checks.filter((c) => !c.ok).map((c) => (
              <div key={c.citation_id} className="rounded bg-muted/50 px-2 py-1 text-xs">
                <span className="text-muted-foreground">[{c.citation_id}]</span>{" "}
                {c.claim_text}
                {c.issues.map((issue, i) => (
                  <div key={i} className="text-destructive/80">{issue}</div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run — expect PASS**

```bash
pnpm test tests/unit/demo-validation-gate.test.tsx
```

Expected: `✓ 4 tests passed`

- [ ] **Step 5: Commit**

```bash
git add components/knowledge-graph/demo-validation-gate.tsx tests/unit/demo-validation-gate.test.tsx
git commit -m "feat(kg): add DemoValidationGate component"
```

---

### Task 14: MaterialEventTimeline

**Files:**
- Create: `components/knowledge-graph/material-event-timeline.tsx`
- Test: `tests/unit/material-event-timeline.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/material-event-timeline.test.tsx
// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

const mockEvent = {
  material_event_id: "m1",
  case_id: 116,
  debtor_id: 1,
  upload_batch_id: "b1",
  event_type: "supplement_upload",
  status: "completed" as const,
  batch_name: "第一批材料",
  doc_category: "章程",
  operator_id: "u1",
  operator_name: "张操作员",
  file_count: 3,
  records_inserted: 120,
  event_payload: {},
  stage: "completed",
  has_conclusion_changes: true,
  reconciliation_item_count: 2,
  add_item_count: 1,
  override_item_count: 1,
  change_summary: "新增1条结论",
  error_message: "",
  started_at: "2026-06-01T10:00:00Z",
  completed_at: "2026-06-01T10:05:00Z",
  failed_at: null,
  created_at: "2026-06-01T09:55:00Z",
  updated_at: "2026-06-01T10:05:00Z",
};

describe("MaterialEventTimeline", () => {
  it("renders event batch name", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    render(<MaterialEventTimeline events={[mockEvent]} isLoading={false} />);
    expect(screen.getByText("第一批材料")).toBeTruthy();
  });

  it("shows conclusion-change badge when has_conclusion_changes is true", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    render(<MaterialEventTimeline events={[mockEvent]} isLoading={false} />);
    expect(screen.getByText(/结论变化/)).toBeTruthy();
  });

  it("shows empty state when no events", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    render(<MaterialEventTimeline events={[]} isLoading={false} />);
    expect(screen.getByText(/暂无材料事件/)).toBeTruthy();
  });

  it("shows error message when status is failed", async () => {
    const { MaterialEventTimeline } = await import("@/components/knowledge-graph/material-event-timeline");
    const failedEvent = { ...mockEvent, status: "failed" as const, error_message: "OCR超时" };
    render(<MaterialEventTimeline events={[failedEvent]} isLoading={false} />);
    expect(screen.getByText("OCR超时")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pnpm test tests/unit/material-event-timeline.test.tsx
```

Expected: `Cannot find module '@/components/knowledge-graph/material-event-timeline'`

- [ ] **Step 3: Implement `material-event-timeline.tsx`**

```tsx
// components/knowledge-graph/material-event-timeline.tsx
"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";
import type { CaseMaterialEventItem } from "@/lib/types/doc-categories";

const STATUS_DOT: Record<string, string> = {
  completed: "bg-emerald-500",
  processing: "bg-blue-500 animate-pulse",
  failed: "bg-destructive",
  received: "bg-muted-foreground",
};

const STAGE_LABELS: Record<string, string> = {
  stored: "已存储",
  ocr_running: "OCR进行中",
  graph_running: "图谱提取中",
  completed: "已完成",
  failed: "失败",
};

interface MaterialEventTimelineProps {
  events: CaseMaterialEventItem[];
  isLoading: boolean;
}

export function MaterialEventTimeline({ events, isLoading }: MaterialEventTimelineProps) {
  const [expandedError, setExpandedError] = useState<string | null>(null);

  if (isLoading) {
    return <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">加载中…</div>;
  }

  if (events.length === 0) {
    return <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">暂无材料事件</div>;
  }

  return (
    <div className="space-y-0">
      {events.map((ev, i) => (
        <div key={ev.material_event_id} className="relative flex gap-4 pb-6">
          {/* Timeline line */}
          {i < events.length - 1 && (
            <div className="absolute left-[7px] top-4 h-full w-px bg-border" />
          )}
          {/* Dot */}
          <div className={cn("mt-1 h-3.5 w-3.5 shrink-0 rounded-full", STATUS_DOT[ev.status] ?? STATUS_DOT.received)} />
          {/* Card */}
          <div className="flex-1 rounded-md border p-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="text-sm font-medium">{ev.batch_name}</div>
                <div className="text-xs text-muted-foreground">{ev.doc_category} · {ev.operator_name}</div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                  {STAGE_LABELS[ev.stage] ?? ev.stage}
                </span>
                {ev.has_conclusion_changes && (
                  <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-500">
                    ↑ {ev.add_item_count + ev.override_item_count} 条结论变化
                  </span>
                )}
              </div>
            </div>
            <div className="mt-1.5 text-xs text-muted-foreground">
              {ev.file_count} 个文件 · {ev.records_inserted} 条记录
              {ev.created_at && <> · {new Date(ev.created_at).toLocaleString("zh-CN")}</>}
            </div>
            {ev.status === "failed" && ev.error_message && (
              <button
                className="mt-1.5 flex w-full items-center gap-1 text-xs text-destructive"
                onClick={() => setExpandedError(expandedError === ev.material_event_id ? null : ev.material_event_id)}
              >
                {expandedError === ev.material_event_id ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                查看错误
              </button>
            )}
            {expandedError === ev.material_event_id && (
              <div className="mt-1 rounded bg-destructive/10 p-2 text-xs text-destructive">
                {ev.error_message}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run — expect PASS**

```bash
pnpm test tests/unit/material-event-timeline.test.tsx
```

Expected: `✓ 4 tests passed`

- [ ] **Step 5: Commit**

```bash
git add components/knowledge-graph/material-event-timeline.tsx tests/unit/material-event-timeline.test.tsx
git commit -m "feat(kg): add MaterialEventTimeline component"
```

---

### Task 15: EvolutionTimeline

**Files:**
- Create: `components/knowledge-graph/evolution-timeline.tsx`
- Test: `tests/unit/evolution-timeline.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/evolution-timeline.test.tsx
// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
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
  it("renders ADD item with green badge", async () => {
    const { EvolutionTimeline } = await import("@/components/knowledge-graph/evolution-timeline");
    render(<EvolutionTimeline items={[addItem]} isLoading={false} />);
    expect(screen.getByText("晨光煤矿是债务人")).toBeTruthy();
    expect(screen.getByText("新增")).toBeTruthy();
  });

  it("renders OVERRIDE item with both old and new texts", async () => {
    const { EvolutionTimeline } = await import("@/components/knowledge-graph/evolution-timeline");
    render(<EvolutionTimeline items={[overrideItem]} isLoading={false} />);
    expect(screen.getByText("晨光煤矿是主债务人")).toBeTruthy();
    expect(screen.getByText("晨光煤矿是债务人")).toBeTruthy();
    expect(screen.getByText("替代")).toBeTruthy();
  });

  it("shows empty state", async () => {
    const { EvolutionTimeline } = await import("@/components/knowledge-graph/evolution-timeline");
    render(<EvolutionTimeline items={[]} isLoading={false} />);
    expect(screen.getByText(/暂无结论演进/)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pnpm test tests/unit/evolution-timeline.test.tsx
```

Expected: `Cannot find module '@/components/knowledge-graph/evolution-timeline'`

- [ ] **Step 3: Implement `evolution-timeline.tsx`**

```tsx
// components/knowledge-graph/evolution-timeline.tsx
"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";
import type { EvolutionItem } from "@/lib/types/knowledge-graph";

interface EvolutionTimelineProps {
  items: EvolutionItem[];
  isLoading: boolean;
}

export function EvolutionTimeline({ items, isLoading }: EvolutionTimelineProps) {
  const [filter, setFilter] = useState<"ALL" | "ADD" | "OVERRIDE">("ALL");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  if (isLoading) {
    return <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">加载中…</div>;
  }

  const filtered = filter === "ALL" ? items : items.filter((i) => i.action === filter);

  if (filtered.length === 0) {
    return (
      <div className="space-y-4">
        <FilterBar filter={filter} onChange={setFilter} />
        <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">暂无结论演进</div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <FilterBar filter={filter} onChange={setFilter} />
      <div className="space-y-3">
        {filtered.map((item) => {
          const isExpanded = expanded.has(item.id ?? -1);
          return (
            <div key={item.id ?? item.new_claim_id} className="rounded-md border p-3">
              <div className="flex items-start justify-between gap-2">
                <span className={cn(
                  "mt-0.5 rounded px-1.5 py-0.5 text-xs font-medium shrink-0",
                  item.action === "ADD"
                    ? "bg-emerald-500/10 text-emerald-500"
                    : "bg-amber-500/10 text-amber-500"
                )}>
                  {item.action === "ADD" ? "新增" : "替代"}
                </span>
                <div className="flex-1 space-y-1.5">
                  {item.action === "ADD" ? (
                    <p className="text-sm">{item.new_claim_text}</p>
                  ) : (
                    <div className="grid grid-cols-2 gap-2">
                      <p className="text-sm text-muted-foreground line-through">{item.superseded_claim_text}</p>
                      <p className="text-sm">{item.new_claim_text}</p>
                    </div>
                  )}
                  <div className="text-xs text-muted-foreground">
                    {item.batch_name} · {item.doc_category}
                    {item.created_at && <> · {new Date(item.created_at).toLocaleDateString("zh-CN")}</>}
                  </div>
                  {item.action === "OVERRIDE" && item.rationale && (
                    <p className="text-xs text-muted-foreground">
                      {item.rationale.length > 60 && !isExpanded
                        ? item.rationale.slice(0, 60) + "…"
                        : item.rationale}
                    </p>
                  )}
                </div>
                {item.evidences.length > 0 && (
                  <button
                    className="shrink-0 text-xs text-primary hover:text-primary/80"
                    onClick={() => setExpanded((prev) => {
                      const next = new Set(prev);
                      if (next.has(item.id ?? -1)) next.delete(item.id ?? -1);
                      else next.add(item.id ?? -1);
                      return next;
                    })}
                  >
                    {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                  </button>
                )}
              </div>
              {isExpanded && (
                <div className="mt-2 space-y-1 border-t pt-2">
                  {item.evidences.map((ev) => (
                    <div key={ev.chunk_id} className="flex gap-2 text-xs text-muted-foreground">
                      <span className="shrink-0">{ev.file_name} P.{ev.page_no}</span>
                      <span className="line-clamp-1">{ev.quote_text}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FilterBar({ filter, onChange }: { filter: string; onChange: (f: "ALL" | "ADD" | "OVERRIDE") => void }) {
  return (
    <div className="flex gap-1">
      {(["ALL", "ADD", "OVERRIDE"] as const).map((f) => (
        <button
          key={f}
          onClick={() => onChange(f)}
          className={cn(
            "rounded px-2.5 py-1 text-xs transition-colors",
            filter === f ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-muted"
          )}
        >
          {f === "ALL" ? "全部" : f === "ADD" ? "新增" : "替代"}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run — expect PASS**

```bash
pnpm test tests/unit/evolution-timeline.test.tsx
```

Expected: `✓ 3 tests passed`

- [ ] **Step 5: Commit**

```bash
git add components/knowledge-graph/evolution-timeline.tsx tests/unit/evolution-timeline.test.tsx
git commit -m "feat(kg): add EvolutionTimeline component"
```

---

### Task 16: UnresolvedItemsPanel

**Files:**
- Create: `components/knowledge-graph/unresolved-items-panel.tsx`
- Test: `tests/unit/unresolved-items-panel.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/unresolved-items-panel.test.tsx
// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
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

  it("shows missing dependencies as tags", async () => {
    const { UnresolvedItemsPanel } = await import("@/components/knowledge-graph/unresolved-items-panel");
    render(<UnresolvedItemsPanel data={mockData} isLoading={false} />);
    expect(screen.getByText("from_entity:晨光煤矿")).toBeTruthy();
  });

  it("shows all-resolved empty state when counts are zero", async () => {
    const { UnresolvedItemsPanel } = await import("@/components/knowledge-graph/unresolved-items-panel");
    const empty: UnresolvedItemsResponse = { ...mockData, unresolved_relation_count: 0, unresolved_claim_count: 0, unresolved_relations: [], unresolved_claims: [] };
    render(<UnresolvedItemsPanel data={empty} isLoading={false} />);
    expect(screen.getByText(/全部依赖已补齐/)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pnpm test tests/unit/unresolved-items-panel.test.tsx
```

Expected: `Cannot find module '@/components/knowledge-graph/unresolved-items-panel'`

- [ ] **Step 3: Implement `unresolved-items-panel.tsx`**

```tsx
// components/knowledge-graph/unresolved-items-panel.tsx
"use client";

import { CheckCircle } from "lucide-react";
import type { UnresolvedItemsResponse } from "@/lib/types/knowledge-graph";

interface UnresolvedItemsPanelProps {
  data: UnresolvedItemsResponse | null;
  isLoading: boolean;
}

export function UnresolvedItemsPanel({ data, isLoading }: UnresolvedItemsPanelProps) {
  if (isLoading) {
    return <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">加载中…</div>;
  }

  if (!data) return null;

  const totalUnresolved = data.unresolved_relation_count + data.unresolved_claim_count;

  if (totalUnresolved === 0) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-emerald-500">
        <CheckCircle className="h-4 w-4" />
        全部依赖已补齐
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        <span>{data.unresolved_relation_count} 条关系未决</span>
        <span>·</span>
        <span>{data.unresolved_claim_count} 条断言未决</span>
      </div>

      {data.unresolved_relations.length > 0 && (
        <section>
          <h4 className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">未决关系</h4>
          <div className="space-y-2">
            {data.unresolved_relations.map((r) => (
              <div key={r.id ?? r.relation_temp_id} className="rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-muted px-1.5 py-0.5 text-xs">{r.relation_type}</span>
                  <span className="text-sm">{r.relation_label}</span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{r.reason}</p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {r.missing_dependencies.map((dep) => (
                    <span key={dep} className="rounded bg-destructive/10 px-1.5 py-0.5 text-xs text-destructive">
                      {dep}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {data.unresolved_claims.length > 0 && (
        <section>
          <h4 className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">未决断言</h4>
          <div className="space-y-2">
            {data.unresolved_claims.map((c) => (
              <div key={c.id ?? c.entity_key} className="rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-muted px-1.5 py-0.5 text-xs">{c.claim_type}</span>
                  <span className="text-sm">{c.claim_text}</span>
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">{c.entity_name}</div>
                <p className="mt-1 text-xs text-muted-foreground">{c.reason}</p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {c.missing_dependencies.map((dep) => (
                    <span key={dep} className="rounded bg-destructive/10 px-1.5 py-0.5 text-xs text-destructive">
                      {dep}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run — expect PASS**

```bash
pnpm test tests/unit/unresolved-items-panel.test.tsx
```

Expected: `✓ 3 tests passed`

- [ ] **Step 5: Commit**

```bash
git add components/knowledge-graph/unresolved-items-panel.tsx tests/unit/unresolved-items-panel.test.tsx
git commit -m "feat(kg): add UnresolvedItemsPanel component"
```

---

### Task 17: `/cases/[id]` Page + Cases List Update

**Files:**
- Create: `app/(main)/cases/[id]/page.tsx`
- Modify: `app/(main)/cases/page.tsx` (add "治理 →" link)
- Test: `tests/unit/case-detail-page.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/case-detail-page.test.tsx
// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// Mock all child components and hooks
vi.mock("@/lib/hooks/use-cases", () => ({
  useCases: () => ({ cases: [{ id: 116, case_name: "测试案件116", case_type: "破产", debtor_names: "晨光煤矿" }], isLoading: false }),
}));
vi.mock("@/lib/hooks/use-case-material-events", () => ({
  useCaseMaterialEvents: () => ({ events: [], isLoading: false }),
}));
vi.mock("@/lib/hooks/use-evolution-items", () => ({
  useEvolutionItems: () => ({ items: [], isLoading: false }),
}));
vi.mock("@/lib/hooks/use-unresolved-items", () => ({
  useUnresolvedItems: () => ({ data: null, isLoading: false }),
}));
vi.mock("@/lib/hooks/use-conversations", () => ({
  useConversations: () => ({ conversations: [], isLoading: false }),
}));
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "116" }),
}));
vi.mock("@/lib/stores/graph-modal", () => ({
  useGraphModalStore: () => ({ openModal: vi.fn() }),
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

describe("CaseDetailPage", () => {
  it("renders case name in header", async () => {
    const { default: Page } = await import("@/app/(main)/cases/[id]/page");
    render(<Page />);
    expect(screen.getByText("测试案件116")).toBeTruthy();
  });

  it("renders three tabs", async () => {
    const { default: Page } = await import("@/app/(main)/cases/[id]/page");
    render(<Page />);
    expect(screen.getByText("材料事件")).toBeTruthy();
    expect(screen.getByText("结论演进")).toBeTruthy();
    expect(screen.getByText("未决补件")).toBeTruthy();
  });

  it("renders MaterialEventTimeline in default tab", async () => {
    const { default: Page } = await import("@/app/(main)/cases/[id]/page");
    render(<Page />);
    expect(screen.getByTestId("material-events")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pnpm test tests/unit/case-detail-page.test.tsx
```

Expected: `Cannot find module '@/app/(main)/cases/[id]/page'`

- [ ] **Step 3: Implement `app/(main)/cases/[id]/page.tsx`**

```tsx
// app/(main)/cases/[id]/page.tsx
"use client";

import { useParams } from "next/navigation";
import { Network } from "lucide-react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { useCases } from "@/lib/hooks/use-cases";
import { useCaseMaterialEvents } from "@/lib/hooks/use-case-material-events";
import { useEvolutionItems } from "@/lib/hooks/use-evolution-items";
import { useUnresolvedItems } from "@/lib/hooks/use-unresolved-items";
import { useConversations } from "@/lib/hooks/use-conversations";
import { useGraphModalStore } from "@/lib/stores/graph-modal";
import { DemoValidationGate } from "@/components/knowledge-graph/demo-validation-gate";
import { MaterialEventTimeline } from "@/components/knowledge-graph/material-event-timeline";
import { EvolutionTimeline } from "@/components/knowledge-graph/evolution-timeline";
import { UnresolvedItemsPanel } from "@/components/knowledge-graph/unresolved-items-panel";

export default function CaseDetailPage() {
  const params = useParams();
  const caseId = Number(params.id);

  const { cases } = useCases();
  const caseItem = cases.find((c) => c.id === caseId) ?? null;

  const { events, isLoading: eventsLoading } = useCaseMaterialEvents(caseId);
  const { items: evolutionItems, isLoading: evolutionLoading } = useEvolutionItems(caseId);
  const { data: unresolvedData, isLoading: unresolvedLoading } = useUnresolvedItems(caseId);
  const { conversations } = useConversations();
  const openGraph = useGraphModalStore((s) => s.openModal);

  // Derive reportRef from the most recent conversation linked to this case
  const latestThread = conversations
    .filter((c) => c.case_id === caseId)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0];
  const reportRef = latestThread ? `final_report:${latestThread.thread_id}` : null;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b px-4 py-3">
        <SidebarTrigger />
        <div className="flex-1">
          <h1 className="text-base font-semibold">{caseItem?.case_name ?? `案件 ${caseId}`}</h1>
          {caseItem?.debtor_names && (
            <p className="text-xs text-muted-foreground">{caseItem.debtor_names}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <DemoValidationGate caseId={caseId} reportRef={reportRef} />
          <Button
            variant="outline"
            size="sm"
            className="h-7 gap-1.5 text-xs"
            onClick={() => openGraph({ caseId })}
          >
            <Network className="h-3.5 w-3.5" />
            查看图谱
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="events" className="flex flex-1 flex-col overflow-hidden">
        <TabsList className="mx-4 mt-3 justify-start rounded-none border-b bg-transparent p-0">
          <TabsTrigger value="events" className="rounded-none border-b-2 border-transparent px-4 pb-2 data-[state=active]:border-primary">
            材料事件
          </TabsTrigger>
          <TabsTrigger value="evolution" className="rounded-none border-b-2 border-transparent px-4 pb-2 data-[state=active]:border-primary">
            结论演进
          </TabsTrigger>
          <TabsTrigger value="unresolved" className="rounded-none border-b-2 border-transparent px-4 pb-2 data-[state=active]:border-primary">
            未决补件
          </TabsTrigger>
        </TabsList>

        <div className="flex-1 overflow-y-auto p-4">
          <TabsContent value="events" className="mt-0">
            <MaterialEventTimeline events={events} isLoading={eventsLoading} />
          </TabsContent>
          <TabsContent value="evolution" className="mt-0">
            <EvolutionTimeline items={evolutionItems} isLoading={evolutionLoading} />
          </TabsContent>
          <TabsContent value="unresolved" className="mt-0">
            <UnresolvedItemsPanel data={unresolvedData} isLoading={unresolvedLoading} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
```

- [ ] **Step 4: Add `shadcn Tabs` if not present**

```bash
pnpm dlx shadcn@latest add tabs
```

- [ ] **Step 5: Add "治理 →" link in cases list**

In `app/(main)/cases/page.tsx`, find the case card render and add a link. Locate where each case card is rendered and add inside the card actions area:

```tsx
import Link from "next/link";

// Inside each case card, add:
<Link
  href={`/cases/${c.id}`}
  className="text-xs text-muted-foreground hover:text-foreground transition-colors"
>
  治理 →
</Link>
```

- [ ] **Step 6: Run — expect PASS**

```bash
pnpm test tests/unit/case-detail-page.test.tsx
```

Expected: `✓ 3 tests passed`

- [ ] **Step 7: Run all Phase 4 tests**

```bash
pnpm test tests/unit/demo-validation-gate.test.tsx tests/unit/material-event-timeline.test.tsx tests/unit/evolution-timeline.test.tsx tests/unit/unresolved-items-panel.test.tsx tests/unit/case-detail-page.test.tsx
```

Expected: `✓ 17 tests passed`

- [ ] **Step 8: Commit**

```bash
git add app/\(main\)/cases/\[id\]/ components/knowledge-graph/ app/\(main\)/cases/page.tsx tests/unit/case-detail-page.test.tsx
git commit -m "feat(kg): add CaseDetailPage with governance tabs"
```

---

### Task 18: Run Full Test Suite

- [ ] **Step 1: Run all tests**

```bash
pnpm test
```

Expected: All tests pass. If failures, fix before proceeding.

- [ ] **Step 2: Final commit if any fixes**

```bash
git add -p  # stage only fixes
git commit -m "fix(kg): resolve test failures after full suite run"
```

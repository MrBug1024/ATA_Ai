# Knowledge Graph — Phase 3: Graph Modal

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Prerequisite:** Phase 1 complete (types, hooks, stores exist).

**Goal:** A full-screen modal with a Cytoscape.js force-directed graph. Clicking a node highlights it and shows entity info in a right panel. Clicking an edge fetches and shows relation claims + evidence. Depth and relation-type filters re-render the graph live.

**Architecture:** `CytoscapeCanvas` wraps the cytoscape instance with a `useEffect` lifecycle. `RelationDetailPanel` is a pure display component fed by `useRelationEvidence`. `GraphModal` orchestrates both, reads from `graphModalStore`, and mounts globally in `app-shell`.

**Tech Stack:** cytoscape, cytoscape-fcose, TypeScript, shadcn Dialog, Vitest

---

### Task 9: Install Cytoscape

**Files:** `package.json` (modified by pnpm)

- [ ] **Step 1: Install packages**

```bash
pnpm add cytoscape cytoscape-fcose
pnpm add -D @types/cytoscape
```

- [ ] **Step 2: Verify install**

```bash
node -e "require('cytoscape'); console.log('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add package.json pnpm-lock.yaml
git commit -m "chore: add cytoscape and cytoscape-fcose dependencies"
```

---

### Task 10: CytoscapeCanvas

**Files:**
- Create: `components/knowledge-graph/cytoscape-canvas.tsx`
- Test: `tests/unit/cytoscape-canvas.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/cytoscape-canvas.test.tsx
// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import React from "react";

// Cytoscape is hard to test in jsdom — test the data-transform logic only
describe("buildCytoscapeElements", () => {
  it("maps GraphNode to cytoscape node element", async () => {
    const { buildCytoscapeElements } = await import("@/components/knowledge-graph/cytoscape-canvas");
    const nodes = [{ id: "e-1", entity_id: 1, label: "A", entity_type: "company", risk_level: "high" as const }];
    const edges = [{ id: "r-1", relation_id: 1, source: "e-1", target: "e-2", label: "担保", relation_type: "guarantee", confidence: 0.9 }];
    const elements = buildCytoscapeElements(nodes, edges, "e-1");
    const nodeEl = elements.find((e) => e.data.id === "e-1");
    expect(nodeEl?.data.label).toBe("A");
    expect(nodeEl?.data.entityType).toBe("company");
    expect(nodeEl?.data.isCenter).toBe(true);
    const edgeEl = elements.find((e) => e.data.id === "r-1");
    expect(edgeEl?.data.confidence).toBe(0.9);
  });

  it("marks only the center node with isCenter=true", async () => {
    const { buildCytoscapeElements } = await import("@/components/knowledge-graph/cytoscape-canvas");
    const nodes = [
      { id: "e-1", entity_id: 1, label: "A", entity_type: "company", risk_level: "low" as const },
      { id: "e-2", entity_id: 2, label: "B", entity_type: "person", risk_level: "low" as const },
    ];
    const elements = buildCytoscapeElements(nodes, [], "e-1");
    expect(elements.find((e) => e.data.id === "e-1")?.data.isCenter).toBe(true);
    expect(elements.find((e) => e.data.id === "e-2")?.data.isCenter).toBe(false);
  });
});
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pnpm test tests/unit/cytoscape-canvas.test.tsx
```

Expected: `Cannot find module '@/components/knowledge-graph/cytoscape-canvas'`

- [ ] **Step 3: Implement `cytoscape-canvas.tsx`**

```tsx
// components/knowledge-graph/cytoscape-canvas.tsx
"use client";

import { useRef, useEffect } from "react";
import cytoscape from "cytoscape";
// @ts-expect-error no types for fcose
import fcose from "cytoscape-fcose";
import type { GraphNode, GraphEdge } from "@/lib/types/knowledge-graph";

cytoscape.use(fcose);

const ENTITY_COLORS: Record<string, string> = {
  company: "#1e3a5f",
  person: "#1e3a1e",
  mine_right: "#2a1e3a",
};

const RISK_BORDER: Record<string, string> = {
  high: "#ef4444",
  medium: "#f97316",
  low: "#334155",
  unknown: "#334155",
};

export interface CyElement {
  data: {
    id: string;
    label?: string;
    entityType?: string;
    riskLevel?: string;
    isCenter?: boolean;
    source?: string;
    target?: string;
    relationId?: number;
    confidence?: number;
  };
}

export function buildCytoscapeElements(
  nodes: GraphNode[],
  edges: GraphEdge[],
  centerEntityId?: string
): CyElement[] {
  return [
    ...nodes.map((n) => ({
      data: {
        id: n.id,
        label: n.label,
        entityType: n.entity_type,
        riskLevel: n.risk_level,
        isCenter: n.id === centerEntityId,
      },
    })),
    ...edges.map((e) => ({
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        relationId: e.relation_id,
        confidence: e.confidence,
      },
    })),
  ];
}

interface CytoscapeCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  centerEntityId?: string;
  onNodeClick?: (nodeId: string, entityId: number, label: string, entityType: string, riskLevel: string) => void;
  onEdgeClick?: (edgeId: string, relationId: number, label: string) => void;
}

export function CytoscapeCanvas({
  nodes, edges, centerEntityId, onNodeClick, onEdgeClick,
}: CytoscapeCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const elements = buildCytoscapeElements(nodes, edges, centerEntityId);

    if (!cyRef.current) {
      cyRef.current = cytoscape({
        container: containerRef.current,
        elements,
        style: [
          {
            selector: "node",
            style: {
              label: "data(label)",
              "text-valign": "center",
              "text-halign": "center",
              "font-size": 11,
              color: "#f8fafc",
              "background-color": (el: cytoscape.NodeSingular) =>
                ENTITY_COLORS[el.data("entityType")] ?? "#1e1e2e",
              "border-width": 2,
              "border-color": (el: cytoscape.NodeSingular) =>
                RISK_BORDER[el.data("riskLevel")] ?? "#334155",
              width: (el: cytoscape.NodeSingular) => el.data("isCenter") ? 48 : 32,
              height: (el: cytoscape.NodeSingular) => el.data("isCenter") ? 48 : 32,
            },
          },
          {
            selector: "edge",
            style: {
              label: "data(label)",
              "font-size": 9,
              color: "#94a3b8",
              "text-rotation": "autorotate",
              "curve-style": "bezier",
              "target-arrow-shape": "triangle",
              width: 1.5,
              "line-color": "#334155",
              "target-arrow-color": "#334155",
              opacity: (el: cytoscape.EdgeSingular) =>
                0.4 + (el.data("confidence") ?? 0.5) * 0.6,
            },
          },
          {
            selector: ":selected",
            style: { "border-color": "#ffffff", "border-width": 3 },
          },
        ],
        layout: { name: "fcose", animate: true, animationDuration: 300 } as cytoscape.LayoutOptions,
      });

      cyRef.current.on("tap", "node", (evt) => {
        const n = evt.target;
        onNodeClick?.(n.id(), n.data("entity_id"), n.data("label"), n.data("entityType"), n.data("riskLevel"));
      });

      cyRef.current.on("tap", "edge", (evt) => {
        const e = evt.target;
        onEdgeClick?.(e.id(), e.data("relationId"), e.data("label"));
      });
    } else {
      cyRef.current.json({ elements });
      cyRef.current.layout({ name: "fcose", animate: true, animationDuration: 300 } as cytoscape.LayoutOptions).run();
    }
  }, [nodes, edges, centerEntityId]);

  useEffect(() => {
    return () => { cyRef.current?.destroy(); cyRef.current = null; };
  }, []);

  if (nodes.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        该实体暂无关联关系
      </div>
    );
  }

  if (nodes.length > 80) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-destructive px-8 text-center">
        节点过多（{nodes.length} 个），建议缩小深度或筛选关系类型
      </div>
    );
  }

  return <div ref={containerRef} className="flex-1" />;
}
```

- [ ] **Step 4: Run — expect PASS**

```bash
pnpm test tests/unit/cytoscape-canvas.test.tsx
```

Expected: `✓ 2 tests passed`

- [ ] **Step 5: Commit**

```bash
git add components/knowledge-graph/cytoscape-canvas.tsx tests/unit/cytoscape-canvas.test.tsx
git commit -m "feat(kg): add CytoscapeCanvas with fcose layout"
```

---

### Task 11: RelationDetailPanel

**Files:**
- Create: `components/knowledge-graph/relation-detail-panel.tsx`
- Test: `tests/unit/relation-detail-panel.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/relation-detail-panel.test.tsx
// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

const mockFetch = vi.fn().mockResolvedValue(undefined);
vi.mock("@/lib/hooks/use-relation-evidence", () => ({
  useRelationEvidence: () => ({ data: null, isMutating: false, error: null, fetch: mockFetch, reset: vi.fn() }),
}));

const mockOpenDrawer = vi.fn();
vi.mock("@/lib/stores/evidence-drawer", () => ({
  useEvidenceDrawerStore: () => ({ openDrawer: mockOpenDrawer }),
}));

describe("RelationDetailPanel", () => {
  it("shows nothing when no selection", async () => {
    const { RelationDetailPanel } = await import("@/components/knowledge-graph/relation-detail-panel");
    const { container } = render(<RelationDetailPanel selection={null} caseId={116} reportRef={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("fetches relation evidence when edge selected", async () => {
    const { RelationDetailPanel } = await import("@/components/knowledge-graph/relation-detail-panel");
    const selection = { type: "edge" as const, edgeId: "r-1", relationId: 77, label: "担保" };
    render(<RelationDetailPanel selection={selection} caseId={116} reportRef={null} />);
    expect(mockFetch).toHaveBeenCalledWith({ case_id: 116, relation_id: 77 });
  });

  it("shows entity info when node selected", async () => {
    const { RelationDetailPanel } = await import("@/components/knowledge-graph/relation-detail-panel");
    const selection = { type: "node" as const, nodeId: "e-1", entityId: 1, label: "晨光煤矿", entityType: "company", riskLevel: "high" };
    render(<RelationDetailPanel selection={selection} caseId={116} reportRef={null} />);
    expect(screen.getByText("晨光煤矿")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pnpm test tests/unit/relation-detail-panel.test.tsx
```

Expected: `Cannot find module '@/components/knowledge-graph/relation-detail-panel'`

- [ ] **Step 3: Implement `relation-detail-panel.tsx`**

```tsx
// components/knowledge-graph/relation-detail-panel.tsx
"use client";

import { useEffect } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useRelationEvidence } from "@/lib/hooks/use-relation-evidence";
import { useEvidenceDrawerStore } from "@/lib/stores/evidence-drawer";
import type { EvidenceItem } from "@/lib/types/knowledge-graph";

type NodeSelection = {
  type: "node";
  nodeId: string;
  entityId: number;
  label: string;
  entityType: string;
  riskLevel: string;
};

type EdgeSelection = {
  type: "edge";
  edgeId: string;
  relationId: number;
  label: string;
};

export type PanelSelection = NodeSelection | EdgeSelection | null;

const RISK_COLORS: Record<string, string> = {
  high: "text-destructive bg-destructive/10",
  medium: "text-amber-500 bg-amber-500/10",
  low: "text-emerald-500 bg-emerald-500/10",
  unknown: "text-muted-foreground bg-muted",
};

const RISK_LABELS: Record<string, string> = {
  high: "高风险", medium: "中风险", low: "低风险", unknown: "未知",
};

interface RelationDetailPanelProps {
  selection: PanelSelection;
  caseId: number;
  reportRef: string | null;
}

export function RelationDetailPanel({ selection, caseId, reportRef }: RelationDetailPanelProps) {
  const { data, isMutating, error, fetch, reset } = useRelationEvidence();
  const openDrawer = useEvidenceDrawerStore((s) => s.openDrawer);

  useEffect(() => {
    if (!selection) { reset(); return; }
    if (selection.type === "edge") {
      fetch({ case_id: caseId, relation_id: selection.relationId }).catch(() => {});
    } else {
      reset();
    }
  }, [selection, caseId]);

  if (!selection) return null;

  return (
    <div className="flex w-80 shrink-0 flex-col overflow-hidden border-l">
      <div className="border-b px-4 py-3">
        <div className="text-xs text-muted-foreground">
          {selection.type === "node" ? "节点详情" : "关系详情"}
        </div>
        <div className="mt-0.5 font-medium text-sm">
          {selection.type === "node" ? selection.label : selection.label}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {selection.type === "node" && (
          <div className="space-y-2 text-sm">
            <div className="flex gap-2 text-xs">
              <span className="text-muted-foreground">类型</span>
              <span>{selection.entityType}</span>
            </div>
            <div className="flex gap-2 text-xs">
              <span className="text-muted-foreground">风险</span>
              <span className={cn("rounded px-1.5 py-0.5 text-xs", RISK_COLORS[selection.riskLevel] ?? RISK_COLORS.unknown)}>
                {RISK_LABELS[selection.riskLevel] ?? selection.riskLevel}
              </span>
            </div>
          </div>
        )}

        {selection.type === "edge" && (
          <>
            {isMutating && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            {error && <p className="text-xs text-destructive">{error}</p>}
            {data?.trace_items.map((item) => (
              <div key={item.claim_id} className="mb-3 rounded-md border p-2">
                <p className="text-xs leading-snug text-foreground">{item.claim_text}</p>
                <div className="mt-2 space-y-1">
                  {item.evidences.map((ev) => (
                    <EvidenceChip
                      key={ev.chunk_id}
                      evidence={ev}
                      caseId={caseId}
                      reportRef={reportRef}
                      citationId={item.citation_id}
                      onOpen={openDrawer}
                    />
                  ))}
                </div>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}

function EvidenceChip({
  evidence, caseId, reportRef, citationId, onOpen,
}: {
  evidence: EvidenceItem;
  caseId: number;
  reportRef: string | null;
  citationId: string;
  onOpen: ReturnType<typeof useEvidenceDrawerStore>["openDrawer"];
}) {
  return (
    <button
      className="flex w-full items-center gap-1.5 rounded bg-muted/50 px-2 py-1 text-left text-xs hover:bg-muted transition-colors"
      onClick={() => {
        if (!reportRef) return;
        onOpen({ caseId, reportRef, citationId });
      }}
    >
      <span className="truncate text-muted-foreground">{evidence.file_name}</span>
      <span className="shrink-0 text-muted-foreground/60">P.{evidence.page_no}</span>
    </button>
  );
}
```

- [ ] **Step 4: Run — expect PASS**

```bash
pnpm test tests/unit/relation-detail-panel.test.tsx
```

Expected: `✓ 3 tests passed`

- [ ] **Step 5: Commit**

```bash
git add components/knowledge-graph/relation-detail-panel.tsx tests/unit/relation-detail-panel.test.tsx
git commit -m "feat(kg): add RelationDetailPanel component"
```

---

### Task 12: GraphModal + Toolbar + App-Shell Integration

**Files:**
- Create: `components/knowledge-graph/graph-modal.tsx`
- Modify: `components/layout/app-shell.tsx`
- Modify: `app/(main)/chat/[id]/page.tsx` (add toolbar button)
- Test: `tests/unit/graph-modal.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/graph-modal.test.tsx
// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

vi.mock("@/components/knowledge-graph/cytoscape-canvas", () => ({
  CytoscapeCanvas: () => <div data-testid="cytoscape" />,
}));
vi.mock("@/components/knowledge-graph/relation-detail-panel", () => ({
  RelationDetailPanel: () => null,
}));

const mockFetch = vi.fn().mockResolvedValue({ nodes: [], edges: [] });
vi.mock("@/lib/hooks/use-graph-subgraph", () => ({
  useGraphSubgraph: () => ({ data: null, isMutating: false, error: null, fetch: mockFetch, reset: vi.fn() }),
}));

let storeState = { open: false, caseId: 0, centerEntityId: undefined, closeModal: vi.fn() };
vi.mock("@/lib/stores/graph-modal", () => ({
  useGraphModalStore: (sel?: (s: typeof storeState) => unknown) => sel ? sel(storeState) : storeState,
}));

describe("GraphModal", () => {
  it("renders nothing when closed", async () => {
    storeState = { ...storeState, open: false };
    const { GraphModal } = await import("@/components/knowledge-graph/graph-modal");
    const { container } = render(<GraphModal />);
    expect(container.firstChild).toBeNull();
  });

  it("renders canvas when open", async () => {
    storeState = { ...storeState, open: true, caseId: 116, centerEntityId: undefined };
    const { GraphModal } = await import("@/components/knowledge-graph/graph-modal");
    render(<GraphModal />);
    expect(screen.getByTestId("cytoscape")).toBeTruthy();
  });

  it("calls fetch subgraph when opened", async () => {
    storeState = { ...storeState, open: true, caseId: 116, centerEntityId: 12 };
    const { GraphModal } = await import("@/components/knowledge-graph/graph-modal");
    render(<GraphModal />);
    expect(mockFetch).toHaveBeenCalledWith(expect.objectContaining({ case_id: 116, center_entity_id: 12, depth: 2 }));
  });
});
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pnpm test tests/unit/graph-modal.test.tsx
```

Expected: `Cannot find module '@/components/knowledge-graph/graph-modal'`

- [ ] **Step 3: Implement `graph-modal.tsx`**

```tsx
// components/knowledge-graph/graph-modal.tsx
"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useGraphModalStore } from "@/lib/stores/graph-modal";
import { useGraphSubgraph } from "@/lib/hooks/use-graph-subgraph";
import { CytoscapeCanvas } from "./cytoscape-canvas";
import { RelationDetailPanel, type PanelSelection } from "./relation-detail-panel";
import type { GraphNode, GraphEdge } from "@/lib/types/knowledge-graph";

const DEPTH_OPTIONS = [1, 2, 3] as const;

export function GraphModal() {
  const open = useGraphModalStore((s) => s.open);
  const caseId = useGraphModalStore((s) => s.caseId);
  const centerEntityId = useGraphModalStore((s) => s.centerEntityId);
  const closeModal = useGraphModalStore((s) => s.closeModal);

  const { data, isMutating, fetch, reset } = useGraphSubgraph();
  const [depth, setDepth] = useState<1 | 2 | 3>(2);
  const [selection, setSelection] = useState<PanelSelection>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);

  useEffect(() => {
    if (!open) { reset(); setNodes([]); setEdges([]); setSelection(null); return; }
    if (!centerEntityId) return;
    fetch({ case_id: caseId, center_entity_id: centerEntityId, depth }).then((res) => {
      setNodes(res.nodes);
      setEdges(res.edges);
    }).catch(() => {});
  }, [open, caseId, centerEntityId, depth]);

  useEffect(() => {
    if (data) { setNodes(data.nodes); setEdges(data.edges); }
  }, [data]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-background">
      {/* Toolbar */}
      <div className="flex items-center gap-3 border-b px-4 py-2.5">
        <span className="text-sm font-medium text-muted-foreground">🕸 知识图谱</span>
        <span className="text-sm text-foreground">案件 {caseId}</span>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-muted-foreground">深度</span>
          {DEPTH_OPTIONS.map((d) => (
            <Button
              key={d}
              variant={depth === d ? "secondary" : "ghost"}
              size="sm"
              className="h-7 w-7 p-0 text-xs"
              onClick={() => setDepth(d)}
            >
              {d}
            </Button>
          ))}
          <Button variant="ghost" size="icon" className="ml-2 h-7 w-7" onClick={closeModal}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        <CytoscapeCanvas
          nodes={nodes}
          edges={edges}
          centerEntityId={centerEntityId ? `e-${centerEntityId}` : undefined}
          onNodeClick={(nodeId, entityId, label, entityType, riskLevel) =>
            setSelection({ type: "node", nodeId, entityId, label, entityType, riskLevel })
          }
          onEdgeClick={(edgeId, relationId, label) =>
            setSelection({ type: "edge", edgeId, relationId, label })
          }
        />
        <RelationDetailPanel selection={selection} caseId={caseId} reportRef={null} />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Mount `GraphModal` in `app-shell.tsx`**

```tsx
// components/layout/app-shell.tsx
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar";
import { AppSidebar } from "./app-sidebar";
import { EvidenceDrawer } from "@/components/knowledge-graph/evidence-drawer";
import { GraphModal } from "@/components/knowledge-graph/graph-modal";

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <SidebarProvider className="h-svh min-h-0 overflow-hidden bg-sidebar">
      <AppSidebar />
      <SidebarInset className="flex min-h-0 flex-col overflow-hidden">
        {children}
      </SidebarInset>
      <EvidenceDrawer />
      <GraphModal />
    </SidebarProvider>
  );
}
```

- [ ] **Step 5: Add "图谱" button in chat toolbar**

In `app/(main)/chat/[id]/page.tsx`, find the top toolbar area and add:

```tsx
import { Network } from "lucide-react";
import { useGraphModalStore } from "@/lib/stores/graph-modal";

// Inside component:
const openGraph = useGraphModalStore((s) => s.openModal);

// In toolbar JSX (next to existing buttons):
<Button
  variant="ghost"
  size="sm"
  className="gap-1.5 text-xs text-muted-foreground"
  onClick={() => openGraph({ caseId: currentCaseId })}
  disabled={!currentCaseId}
>
  <Network className="h-3.5 w-3.5" />
  图谱
</Button>
```

- [ ] **Step 6: Run — expect PASS**

```bash
pnpm test tests/unit/graph-modal.test.tsx
```

Expected: `✓ 3 tests passed`

- [ ] **Step 7: Run all Phase 3 tests**

```bash
pnpm test tests/unit/cytoscape-canvas.test.tsx tests/unit/relation-detail-panel.test.tsx tests/unit/graph-modal.test.tsx
```

Expected: `✓ 8 tests passed`

- [ ] **Step 8: Commit**

```bash
git add components/knowledge-graph/graph-modal.tsx components/layout/app-shell.tsx app/\(main\)/chat/\[id\]/page.tsx tests/unit/graph-modal.test.tsx
git commit -m "feat(kg): add GraphModal with Cytoscape canvas and relation detail panel"
```

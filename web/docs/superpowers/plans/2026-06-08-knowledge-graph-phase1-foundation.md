# Knowledge Graph — Phase 1: Types, Hooks, Stores

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay the data layer — types, SWR hooks for all 7 new endpoints, and two Zustand stores — so every subsequent phase can build on stable interfaces.

**Architecture:** Pure data layer. No UI. All hooks mirror the existing `use-case-material-events.ts` pattern: `useSWR` for GETs, `useSWRMutation` for POSTs. Zustand stores use the same `create` pattern as `upload-queue.ts`.

**Tech Stack:** TypeScript, SWR 2.x (`useSWR` + `useSWRMutation`), Zustand, Vitest

---

### Task 1: Type Definitions

**Files:**
- Create: `lib/types/knowledge-graph.ts`
- Test: `tests/unit/knowledge-graph-types.test.ts`

- [ ] **Step 1: Write the type file**

```ts
// lib/types/knowledge-graph.ts

export interface BBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface EvidenceItem {
  chunk_id: string;
  file_id: number;
  file_name: string;
  page_no: number;
  quote_text: string;
  bbox_list: BBox[];
  page_image_ref: string;
  source_page_id: number;
}

export interface PageAnchorsResponse {
  file_id: number;
  page_no: number;
  page_width: number;
  page_height: number;
  page_image_ref: string;
  anchors: EvidenceItem[];
}

export interface EvidenceResolveRequest {
  case_id: number;
  report_ref: string;
  citation_id: string;
  claim_id?: number;
}

export interface EvidenceResolveResponse {
  case_id: number;
  report_ref: string;
  citation_id: string;
  claim_id: number;
  claim_text: string;
  evidences: EvidenceItem[];
  primary_evidence: EvidenceItem | null;
  primary_page: PageAnchorsResponse | null;
}

export interface GraphNode {
  id: string;
  entity_id: number;
  label: string;
  entity_type: string;
  risk_level: "low" | "medium" | "high" | "unknown";
}

export interface GraphEdge {
  id: string;
  relation_id: number;
  source: string;
  target: string;
  label: string;
  relation_type: string;
  confidence: number;
}

export interface SubgraphRequest {
  case_id: number;
  center_entity_id: number;
  depth?: number;
  relation_types?: string[];
}

export interface SubgraphResponse {
  case_id: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface TraceItem {
  citation_id: string;
  claim_id: number;
  claim_type: string;
  claim_text: string;
  confidence: number;
  evidences: EvidenceItem[];
}

export interface RelationEvidenceRequest {
  case_id: number;
  relation_id: number;
}

export interface RelationEvidenceResponse {
  case_id: number;
  relation_id: number;
  trace_items: TraceItem[];
}

export interface EvolutionItem {
  id: number | null;
  case_id: number;
  action: "ADD" | "OVERRIDE";
  new_claim_id: number | null;
  new_claim_type: string;
  new_claim_text: string;
  superseded_claim_id: number | null;
  superseded_claim_type: string;
  superseded_claim_text: string;
  new_relation_id: number | null;
  superseded_relation_id: number | null;
  rationale: string;
  evidence_chunk_ids: string[];
  upload_batch_id: string;
  batch_name: string;
  doc_category: string;
  material_event_id: string;
  material_event_status: string;
  material_event_type: string;
  evidences: EvidenceItem[];
  created_at: string | null;
}

export interface EvolutionItemsResponse {
  case_id: number;
  action: string;
  evolution_items: EvolutionItem[];
}

export interface UnresolvedRelation {
  id: number | null;
  case_id: number;
  extraction_run_id: number;
  upload_batch_id: string;
  material_event_id: string;
  item_type: "relation";
  relation_key: string;
  relation_type: string;
  relation_label: string;
  entity_temp_id: string;
  relation_temp_id: string;
  missing_dependencies: string[];
  reason: string;
  status: string;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface UnresolvedClaim {
  id: number | null;
  case_id: number;
  extraction_run_id: number;
  upload_batch_id: string;
  material_event_id: string;
  item_type: "claim";
  entity_name: string;
  entity_key: string;
  relation_key: string;
  claim_type: string;
  claim_text: string;
  missing_dependencies: string[];
  reason: string;
  status: string;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface UnresolvedItemsResponse {
  case_id: number;
  upload_batch_id: string;
  status: string;
  unresolved_relation_count: number;
  unresolved_claim_count: number;
  unresolved_relations: UnresolvedRelation[];
  unresolved_claims: UnresolvedClaim[];
}

export interface ValidationCheck {
  citation_id: string;
  claim_id: number;
  claim_text: string;
  ok: boolean;
  evidence_count: number;
  anchor_count: number;
  file_id: number;
  page_no: number;
  issues: string[];
}

export interface ValidationRequest {
  case_id: number;
  report_ref: string;
  citation_ids?: string[];
}

export interface ValidationResponse {
  case_id: number;
  report_ref: string;
  ready: boolean;
  total_citations: number;
  passed_citations: number;
  failed_citations: number;
  checks: ValidationCheck[];
  issues: string[];
}
```

- [ ] **Step 2: Write a smoke-test that imports all types**

```ts
// tests/unit/knowledge-graph-types.test.ts
import { describe, it, expectTypeOf } from "vitest";
import type {
  BBox,
  EvidenceItem,
  GraphNode,
  GraphEdge,
  EvolutionItem,
  ValidationResponse,
} from "@/lib/types/knowledge-graph";

describe("knowledge-graph types", () => {
  it("BBox has x y w h as numbers", () => {
    expectTypeOf<BBox>().toMatchTypeOf<{
      x: number; y: number; w: number; h: number;
    }>();
  });

  it("EvidenceItem.chunk_id is string, file_id is number", () => {
    expectTypeOf<EvidenceItem["chunk_id"]>().toBeString();
    expectTypeOf<EvidenceItem["file_id"]>().toBeNumber();
  });

  it("GraphNode.risk_level is union", () => {
    expectTypeOf<GraphNode["risk_level"]>().toEqualTypeOf<
      "low" | "medium" | "high" | "unknown"
    >();
  });

  it("EvolutionItem.action is ADD or OVERRIDE", () => {
    expectTypeOf<EvolutionItem["action"]>().toEqualTypeOf<"ADD" | "OVERRIDE">();
  });

  it("ValidationResponse.ready is boolean", () => {
    expectTypeOf<ValidationResponse["ready"]>().toBeBoolean();
  });
});
```

- [ ] **Step 3: Run — expect PASS (type-only tests always pass if types compile)**

```bash
pnpm test tests/unit/knowledge-graph-types.test.ts
```

Expected: `✓ 5 tests passed`

- [ ] **Step 4: Commit**

```bash
git add lib/types/knowledge-graph.ts tests/unit/knowledge-graph-types.test.ts
git commit -m "feat(kg): add knowledge-graph type definitions"
```

---

### Task 2: Evidence Hooks (`useEvidenceResolve`, `usePageAnchors`)

**Files:**
- Create: `lib/hooks/use-evidence-resolve.ts`
- Create: `lib/hooks/use-page-anchors.ts`
- Test: `tests/unit/use-evidence-resolve.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// tests/unit/use-evidence-resolve.test.ts
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { act } from "react";

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// Stub env so langgraphUrl resolves to empty-base
vi.stubEnv("NEXT_PUBLIC_LANGGRAPH_API_BASE_URL", "http://test");

beforeEach(() => { mockFetch.mockReset(); });

describe("useEvidenceResolve", () => {
  it("returns null data before trigger", async () => {
    const { useEvidenceResolve } = await import("@/lib/hooks/use-evidence-resolve");
    const { result } = renderHook(() => useEvidenceResolve());
    expect(result.current.data).toBeNull();
    expect(result.current.isMutating).toBe(false);
  });

  it("calls /evidence/resolve with correct body and returns data", async () => {
    const payload = { claim_id: 1, claim_text: "test", evidences: [], primary_evidence: null, primary_page: null, case_id: 116, report_ref: "r", citation_id: "1" };
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => payload });
    const { useEvidenceResolve } = await import("@/lib/hooks/use-evidence-resolve");
    const { result } = renderHook(() => useEvidenceResolve());

    await act(async () => {
      await result.current.resolve({ case_id: 116, report_ref: "r", citation_id: "1" });
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "http://test/evidence/resolve",
      expect.objectContaining({ method: "POST" })
    );
    await waitFor(() => expect(result.current.data?.claim_text).toBe("test"));
  });

  it("sets error on non-ok response", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 404 });
    const { useEvidenceResolve } = await import("@/lib/hooks/use-evidence-resolve");
    const { result } = renderHook(() => useEvidenceResolve());

    await act(async () => {
      await result.current.resolve({ case_id: 1, report_ref: "r", citation_id: "1" }).catch(() => {});
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());
  });
});

describe("usePageAnchors", () => {
  it("fetches page anchors when fileId and pageNo provided", async () => {
    const payload = { file_id: 1, page_no: 3, page_width: 800, page_height: 1100, page_image_ref: "http://img", anchors: [] };
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => payload });
    const { usePageAnchors } = await import("@/lib/hooks/use-page-anchors");
    const { result } = renderHook(() => usePageAnchors(1, 3));

    await waitFor(() => expect(result.current.data?.page_no).toBe(3));
  });

  it("does not fetch when fileId is null", async () => {
    const { usePageAnchors } = await import("@/lib/hooks/use-page-anchors");
    renderHook(() => usePageAnchors(null, 1));
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pnpm test tests/unit/use-evidence-resolve.test.ts
```

Expected: `Cannot find module '@/lib/hooks/use-evidence-resolve'`

- [ ] **Step 3: Implement `use-evidence-resolve.ts`**

```ts
// lib/hooks/use-evidence-resolve.ts
"use client";

import { useState, useCallback } from "react";
import { apiFetch, langgraphUrl } from "@/lib/api/client";
import type {
  EvidenceResolveRequest,
  EvidenceResolveResponse,
} from "@/lib/types/knowledge-graph";

export function useEvidenceResolve() {
  const [data, setData] = useState<EvidenceResolveResponse | null>(null);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resolve = useCallback(async (req: EvidenceResolveRequest) => {
    setIsMutating(true);
    setError(null);
    try {
      const res = await apiFetch(langgraphUrl("/evidence/resolve"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });
      if (!res.ok) throw new Error(`evidence/resolve failed: ${res.status}`);
      const json = (await res.json()) as EvidenceResolveResponse;
      setData(json);
      return json;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setError(msg);
      throw err;
    } finally {
      setIsMutating(false);
    }
  }, []);

  const reset = useCallback(() => { setData(null); setError(null); }, []);

  return { data, isMutating, error, resolve, reset };
}
```

- [ ] **Step 4: Implement `use-page-anchors.ts`**

```ts
// lib/hooks/use-page-anchors.ts
"use client";

import useSWR from "swr";
import { apiFetch, langgraphUrl } from "@/lib/api/client";
import type { PageAnchorsResponse } from "@/lib/types/knowledge-graph";

const fetcher = (url: string): Promise<PageAnchorsResponse> =>
  apiFetch(url).then((r) => {
    if (!r.ok) throw new Error(`page-anchors failed: ${r.status}`);
    return r.json() as Promise<PageAnchorsResponse>;
  });

export function usePageAnchors(
  fileId: number | null,
  pageNo: number | null,
  chunkId?: string
) {
  const params = new URLSearchParams();
  if (fileId !== null) params.set("file_id", String(fileId));
  if (pageNo !== null) params.set("page_no", String(pageNo));
  if (chunkId) params.set("chunk_id", chunkId);

  const key =
    fileId !== null && pageNo !== null
      ? langgraphUrl(`/files/page-anchors?${params}`)
      : null;

  const { data, error, isLoading } = useSWR<PageAnchorsResponse>(key, fetcher);

  return {
    data: data ?? null,
    isLoading,
    error: error instanceof Error ? error.message : null,
  };
}
```

- [ ] **Step 5: Run — expect PASS**

```bash
pnpm test tests/unit/use-evidence-resolve.test.ts
```

Expected: `✓ 5 tests passed`

- [ ] **Step 6: Commit**

```bash
git add lib/hooks/use-evidence-resolve.ts lib/hooks/use-page-anchors.ts tests/unit/use-evidence-resolve.test.ts
git commit -m "feat(kg): add useEvidenceResolve and usePageAnchors hooks"
```

---

### Task 3: Graph Hooks (`useGraphSubgraph`, `useRelationEvidence`)

**Files:**
- Create: `lib/hooks/use-graph-subgraph.ts`
- Create: `lib/hooks/use-relation-evidence.ts`
- Test: `tests/unit/use-graph-hooks.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// tests/unit/use-graph-hooks.test.ts
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
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pnpm test tests/unit/use-graph-hooks.test.ts
```

Expected: `Cannot find module '@/lib/hooks/use-graph-subgraph'`

- [ ] **Step 3: Implement both hooks**

```ts
// lib/hooks/use-graph-subgraph.ts
"use client";

import { useState, useCallback } from "react";
import { apiFetch, langgraphUrl } from "@/lib/api/client";
import type { SubgraphRequest, SubgraphResponse } from "@/lib/types/knowledge-graph";

export function useGraphSubgraph() {
  const [data, setData] = useState<SubgraphResponse | null>(null);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async (req: SubgraphRequest) => {
    setIsMutating(true);
    setError(null);
    try {
      const res = await apiFetch(langgraphUrl("/graph/subgraph"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });
      if (!res.ok) throw new Error(`graph/subgraph failed: ${res.status}`);
      const json = (await res.json()) as SubgraphResponse;
      setData(json);
      return json;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setError(msg);
      throw err;
    } finally {
      setIsMutating(false);
    }
  }, []);

  const reset = useCallback(() => { setData(null); setError(null); }, []);

  return { data, isMutating, error, fetch, reset };
}
```

```ts
// lib/hooks/use-relation-evidence.ts
"use client";

import { useState, useCallback } from "react";
import { apiFetch, langgraphUrl } from "@/lib/api/client";
import type {
  RelationEvidenceRequest,
  RelationEvidenceResponse,
} from "@/lib/types/knowledge-graph";

export function useRelationEvidence() {
  const [data, setData] = useState<RelationEvidenceResponse | null>(null);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async (req: RelationEvidenceRequest) => {
    setIsMutating(true);
    setError(null);
    try {
      const res = await apiFetch(langgraphUrl("/graph/relation-evidence"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });
      if (!res.ok) throw new Error(`graph/relation-evidence failed: ${res.status}`);
      const json = (await res.json()) as RelationEvidenceResponse;
      setData(json);
      return json;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setError(msg);
      throw err;
    } finally {
      setIsMutating(false);
    }
  }, []);

  const reset = useCallback(() => { setData(null); setError(null); }, []);

  return { data, isMutating, error, fetch, reset };
}
```

- [ ] **Step 4: Run — expect PASS**

```bash
pnpm test tests/unit/use-graph-hooks.test.ts
```

Expected: `✓ 4 tests passed`

- [ ] **Step 5: Commit**

```bash
git add lib/hooks/use-graph-subgraph.ts lib/hooks/use-relation-evidence.ts tests/unit/use-graph-hooks.test.ts
git commit -m "feat(kg): add useGraphSubgraph and useRelationEvidence hooks"
```

---

### Task 4: Governance Hooks

**Files:**
- Create: `lib/hooks/use-evolution-items.ts`
- Create: `lib/hooks/use-unresolved-items.ts`
- Create: `lib/hooks/use-demo-case-validate.ts`
- Test: `tests/unit/use-governance-hooks.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// tests/unit/use-governance-hooks.test.ts
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
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pnpm test tests/unit/use-governance-hooks.test.ts
```

Expected: `Cannot find module '@/lib/hooks/use-evolution-items'`

- [ ] **Step 3: Implement `use-evolution-items.ts`**

```ts
// lib/hooks/use-evolution-items.ts
"use client";

import useSWR from "swr";
import { apiFetch, langgraphUrl } from "@/lib/api/client";
import type { EvolutionItem, EvolutionItemsResponse } from "@/lib/types/knowledge-graph";

const fetcher = (url: string): Promise<EvolutionItem[]> =>
  apiFetch(url).then((r) => {
    if (!r.ok) throw new Error(`evolution-items failed: ${r.status}`);
    return r.json().then((d: EvolutionItemsResponse) => d.evolution_items ?? []);
  });

export function useEvolutionItems(
  caseId: number | null,
  action?: "ADD" | "OVERRIDE",
  limit = 50
) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (action) params.set("action", action);

  const key = caseId !== null
    ? langgraphUrl(`/files/cases/${caseId}/evolution-items?${params}`)
    : null;

  const { data, error, isLoading, mutate } = useSWR<EvolutionItem[]>(key, fetcher);

  return {
    items: data ?? [],
    isLoading,
    error: error instanceof Error ? error.message : null,
    refresh: mutate,
  };
}
```

- [ ] **Step 4: Implement `use-unresolved-items.ts`**

```ts
// lib/hooks/use-unresolved-items.ts
"use client";

import useSWR from "swr";
import { apiFetch, langgraphUrl } from "@/lib/api/client";
import type { UnresolvedItemsResponse } from "@/lib/types/knowledge-graph";

const fetcher = (url: string): Promise<UnresolvedItemsResponse> =>
  apiFetch(url).then((r) => {
    if (!r.ok) throw new Error(`unresolved-items failed: ${r.status}`);
    return r.json() as Promise<UnresolvedItemsResponse>;
  });

export function useUnresolvedItems(
  caseId: number | null,
  status: "pending" | "resolved" | "" = "pending",
  limit = 50
) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status) params.set("status", status);

  const key = caseId !== null
    ? langgraphUrl(`/files/cases/${caseId}/unresolved-items?${params}`)
    : null;

  const { data, error, isLoading, mutate } = useSWR<UnresolvedItemsResponse>(key, fetcher);

  return {
    data: data ?? null,
    isLoading,
    error: error instanceof Error ? error.message : null,
    refresh: mutate,
  };
}
```

- [ ] **Step 5: Implement `use-demo-case-validate.ts`**

```ts
// lib/hooks/use-demo-case-validate.ts
"use client";

import { useState, useCallback } from "react";
import { apiFetch, langgraphUrl } from "@/lib/api/client";
import type { ValidationRequest, ValidationResponse } from "@/lib/types/knowledge-graph";

export function useDemoCaseValidate() {
  const [data, setData] = useState<ValidationResponse | null>(null);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const validate = useCallback(async (req: ValidationRequest) => {
    setIsMutating(true);
    setError(null);
    try {
      const res = await apiFetch(langgraphUrl("/graph/demo-case-trace/validate"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });
      if (!res.ok) throw new Error(`validate failed: ${res.status}`);
      const json = (await res.json()) as ValidationResponse;
      setData(json);
      return json;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setError(msg);
      throw err;
    } finally {
      setIsMutating(false);
    }
  }, []);

  const reset = useCallback(() => { setData(null); setError(null); }, []);

  return { data, isMutating, error, validate, reset };
}
```

- [ ] **Step 6: Run — expect PASS**

```bash
pnpm test tests/unit/use-governance-hooks.test.ts
```

Expected: `✓ 5 tests passed`

- [ ] **Step 7: Commit**

```bash
git add lib/hooks/use-evolution-items.ts lib/hooks/use-unresolved-items.ts lib/hooks/use-demo-case-validate.ts tests/unit/use-governance-hooks.test.ts
git commit -m "feat(kg): add governance hooks (evolution, unresolved, validate)"
```

---

### Task 5: Zustand Stores

**Files:**
- Create: `lib/stores/evidence-drawer.ts`
- Create: `lib/stores/graph-modal.ts`
- Test: `tests/unit/kg-stores.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// tests/unit/kg-stores.test.ts
import { describe, it, expect, beforeEach } from "vitest";

describe("evidenceDrawerStore", () => {
  beforeEach(async () => {
    // reset store state between tests
    const { useEvidenceDrawerStore } = await import("@/lib/stores/evidence-drawer");
    useEvidenceDrawerStore.setState({
      open: false, caseId: 0, reportRef: "", citationId: "",
      selectedEvidenceIndex: 0, currentPage: null,
    });
  });

  it("opens drawer with correct params", async () => {
    const { useEvidenceDrawerStore } = await import("@/lib/stores/evidence-drawer");
    useEvidenceDrawerStore.getState().openDrawer({
      caseId: 116, reportRef: "final_report:demo-116", citationId: "1",
    });
    const s = useEvidenceDrawerStore.getState();
    expect(s.open).toBe(true);
    expect(s.caseId).toBe(116);
    expect(s.citationId).toBe("1");
  });

  it("closes drawer and resets", async () => {
    const { useEvidenceDrawerStore } = await import("@/lib/stores/evidence-drawer");
    useEvidenceDrawerStore.getState().openDrawer({ caseId: 1, reportRef: "r", citationId: "2" });
    useEvidenceDrawerStore.getState().closeDrawer();
    expect(useEvidenceDrawerStore.getState().open).toBe(false);
  });
});

describe("graphModalStore", () => {
  beforeEach(async () => {
    const { useGraphModalStore } = await import("@/lib/stores/graph-modal");
    useGraphModalStore.setState({ open: false, caseId: 0, centerEntityId: undefined });
  });

  it("opens modal with caseId", async () => {
    const { useGraphModalStore } = await import("@/lib/stores/graph-modal");
    useGraphModalStore.getState().openModal({ caseId: 116 });
    expect(useGraphModalStore.getState().open).toBe(true);
    expect(useGraphModalStore.getState().caseId).toBe(116);
  });

  it("opens modal with optional centerEntityId", async () => {
    const { useGraphModalStore } = await import("@/lib/stores/graph-modal");
    useGraphModalStore.getState().openModal({ caseId: 116, centerEntityId: 12 });
    expect(useGraphModalStore.getState().centerEntityId).toBe(12);
  });

  it("closes modal", async () => {
    const { useGraphModalStore } = await import("@/lib/stores/graph-modal");
    useGraphModalStore.getState().openModal({ caseId: 1 });
    useGraphModalStore.getState().closeModal();
    expect(useGraphModalStore.getState().open).toBe(false);
  });
});
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pnpm test tests/unit/kg-stores.test.ts
```

Expected: `Cannot find module '@/lib/stores/evidence-drawer'`

- [ ] **Step 3: Implement `evidence-drawer.ts`**

```ts
// lib/stores/evidence-drawer.ts
"use client";

import { create } from "zustand";
import type { PageAnchorsResponse } from "@/lib/types/knowledge-graph";

interface OpenDrawerParams {
  caseId: number;
  reportRef: string;
  citationId: string;
}

interface EvidenceDrawerState {
  open: boolean;
  caseId: number;
  reportRef: string;
  citationId: string;
  selectedEvidenceIndex: number;
  currentPage: PageAnchorsResponse | null;
  openDrawer: (params: OpenDrawerParams) => void;
  closeDrawer: () => void;
  setSelectedEvidenceIndex: (index: number) => void;
  setCurrentPage: (page: PageAnchorsResponse | null) => void;
}

export const useEvidenceDrawerStore = create<EvidenceDrawerState>((set) => ({
  open: false,
  caseId: 0,
  reportRef: "",
  citationId: "",
  selectedEvidenceIndex: 0,
  currentPage: null,

  openDrawer: ({ caseId, reportRef, citationId }) =>
    set({ open: true, caseId, reportRef, citationId, selectedEvidenceIndex: 0, currentPage: null }),

  closeDrawer: () =>
    set({ open: false, caseId: 0, reportRef: "", citationId: "", selectedEvidenceIndex: 0, currentPage: null }),

  setSelectedEvidenceIndex: (index) => set({ selectedEvidenceIndex: index }),

  setCurrentPage: (page) => set({ currentPage: page }),
}));
```

- [ ] **Step 4: Implement `graph-modal.ts`**

```ts
// lib/stores/graph-modal.ts
"use client";

import { create } from "zustand";

interface OpenModalParams {
  caseId: number;
  centerEntityId?: number;
}

interface GraphModalState {
  open: boolean;
  caseId: number;
  centerEntityId: number | undefined;
  openModal: (params: OpenModalParams) => void;
  closeModal: () => void;
  setCenterEntityId: (id: number) => void;
}

export const useGraphModalStore = create<GraphModalState>((set) => ({
  open: false,
  caseId: 0,
  centerEntityId: undefined,

  openModal: ({ caseId, centerEntityId }) =>
    set({ open: true, caseId, centerEntityId }),

  closeModal: () =>
    set({ open: false, caseId: 0, centerEntityId: undefined }),

  setCenterEntityId: (id) => set({ centerEntityId: id }),
}));
```

- [ ] **Step 5: Run — expect PASS**

```bash
pnpm test tests/unit/kg-stores.test.ts
```

Expected: `✓ 7 tests passed`

- [ ] **Step 6: Run all Phase 1 tests**

```bash
pnpm test tests/unit/knowledge-graph-types.test.ts tests/unit/use-evidence-resolve.test.ts tests/unit/use-graph-hooks.test.ts tests/unit/use-governance-hooks.test.ts tests/unit/kg-stores.test.ts
```

Expected: `✓ 26 tests passed`

- [ ] **Step 7: Commit**

```bash
git add lib/stores/evidence-drawer.ts lib/stores/graph-modal.ts tests/unit/kg-stores.test.ts
git commit -m "feat(kg): add evidence-drawer and graph-modal Zustand stores"
```

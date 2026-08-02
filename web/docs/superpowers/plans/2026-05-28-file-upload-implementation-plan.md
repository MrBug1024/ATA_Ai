# 案件文件上传 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成案件文件上传的端到端功能：多文件上传、异步处理状态轮询、批次详情与案件批次列表查询。

**Architecture:** 在已有 `app/api/ingest/upload` 和 `AddMaterialDialog` 基础上，新增两个 API Route 代理（查询批次详情、查询案件批次列表），扩展前端 hooks 支持多文件与轮询，改造对话框实现完整的上传状态机。

**Tech Stack:** Next.js API Routes, React, SWR, Tailwind CSS, shadcn/ui, Vitest

---

## File Structure

| File | 责任 |
|------|------|
| `app/api/files/upload-batches/[id]/route.ts` | 代理 `GET /files/upload-batches/{id}` → LangGraph |
| `app/api/files/cases/[id]/upload-batches/route.ts` | 代理 `GET /files/cases/{id}/upload-batches` → LangGraph |
| `lib/types/doc-categories.ts` | 扩展 UploadBatchDetail / CaseUploadBatch 类型 |
| `lib/hooks/use-upload-batch.ts` | SWR + 轮询查询批次详情 |
| `lib/hooks/use-case-upload-batches.ts` | SWR 查询案件批次列表 |
| `lib/hooks/use-upload-ingest.ts` | 扩展为支持多文件 + batch_name |
| `components/cases/add-material-dialog.tsx` | 改造为多文件、状态轮询、结果展示 |
| `tests/integration/upload-batches.test.ts` | API Route 代理测试 |
| `tests/unit/use-upload-batch.test.tsx` | Hook 测试 |
| `tests/unit/use-case-upload-batches.test.tsx` | Hook 测试 |

---

## Task 1: 新增代理 Route — 查询上传批次详情

**Files:**
- Create: `app/api/files/upload-batches/[id]/route.ts`
- Test: `tests/integration/upload-batches.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NextRequest } from "next/server";

const requireSessionMock = vi.fn();
vi.mock("@/lib/api/guards", () => ({
  requireSession: () => requireSessionMock(),
  getSession: () => requireSessionMock(),
}));

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  requireSessionMock.mockReset();
  process.env.LANGGRAPH_API_BASE_URL = "http://lg:8081";
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  vi.unstubAllGlobals();
});

const getRoute = () => import("@/app/api/files/upload-batches/[id]/route");

describe("GET /api/files/upload-batches/[id]", () => {
  it("200 透传上游响应", async () => {
    requireSessionMock.mockResolvedValue({ user: { id: "u1" } });
    const upstreamData = {
      upload_batch_id: "local-abc",
      status: "completed",
      file_count: 2,
      files: [{ file_id: 1, file_name: "a.pdf" }],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(upstreamData), { status: 200 })
      )
    );

    const { GET } = await getRoute();
    const req = new NextRequest("http://localhost/api/files/upload-batches/local-abc");
    const res = await GET(req, { params: Promise.resolve({ id: "local-abc" }) });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.upload_batch_id).toBe("local-abc");
    expect(body.file_count).toBe(2);
  });

  it("401 未认证", async () => {
    requireSessionMock.mockRejectedValue(new Error("Unauthorized"));
    const { GET } = await getRoute();
    const req = new NextRequest("http://localhost/api/files/upload-batches/x");
    const res = await GET(req, { params: Promise.resolve({ id: "x" }) });
    expect(res.status).toBe(401);
  });

  it("503 未配置 LANGGRAPH_API_BASE_URL", async () => {
    requireSessionMock.mockResolvedValue({ user: { id: "u1" } });
    delete process.env.LANGGRAPH_API_BASE_URL;
    const { GET } = await getRoute();
    const req = new NextRequest("http://localhost/api/files/upload-batches/x");
    const res = await GET(req, { params: Promise.resolve({ id: "x" }) });
    expect(res.status).toBe(503);
  });

  it("503 上游 unreachable", async () => {
    requireSessionMock.mockResolvedValue({ user: { id: "u1" } });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));
    const { GET } = await getRoute();
    const req = new NextRequest("http://localhost/api/files/upload-batches/x");
    const res = await GET(req, { params: Promise.resolve({ id: "x" }) });
    expect(res.status).toBe(503);
  });

  it("502 上游返回非 JSON", async () => {
    requireSessionMock.mockResolvedValue({ user: { id: "u1" } });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<html>", { status: 200 }))
    );
    const { GET } = await getRoute();
    const req = new NextRequest("http://localhost/api/files/upload-batches/x");
    const res = await GET(req, { params: Promise.resolve({ id: "x" }) });
    expect(res.status).toBe(502);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm vitest run tests/integration/upload-batches.test.ts`
Expected: FAIL — module not found `@/app/api/files/upload-batches/[id]/route`

- [ ] **Step 3: Implement the route**

```typescript
import { NextRequest } from "next/server";
import { requireSession } from "@/lib/api/guards";
import { unauthorizedResponse, errorResponse } from "@/lib/api/response";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    await requireSession();
  } catch {
    return unauthorizedResponse();
  }

  const { id } = await params;
  if (!id) {
    return errorResponse("Missing upload batch id", 400);
  }

  const LANGGRAPH_BASE = process.env.LANGGRAPH_API_BASE_URL;
  if (!LANGGRAPH_BASE) {
    return errorResponse("LANGGRAPH_API_BASE_URL is not configured", 503);
  }

  const upstream = new URL(`${LANGGRAPH_BASE}/files/upload-batches/${encodeURIComponent(id)}`);
  for (const [key, value] of request.nextUrl.searchParams.entries()) {
    upstream.searchParams.set(key, value);
  }

  let upstreamRes: Response;
  try {
    upstreamRes = await fetch(upstream.toString(), {
      headers: { Accept: "application/json" },
      next: { revalidate: 0 },
    });
  } catch {
    return errorResponse("LangGraph API unreachable", 503);
  }

  let data: unknown;
  try {
    data = await upstreamRes.json();
  } catch {
    return errorResponse("LangGraph API returned non-JSON response", 502);
  }

  return Response.json(data, { status: upstreamRes.status });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm vitest run tests/integration/upload-batches.test.ts`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/integration/upload-batches.test.ts app/api/files/upload-batches/
git commit -m "feat: add proxy route for GET /files/upload-batches/{id}"
```

---

## Task 2: 新增代理 Route — 查询案件上传批次列表

**Files:**
- Create: `app/api/files/cases/[id]/upload-batches/route.ts`
- Modify: `tests/integration/upload-batches.test.ts`

- [ ] **Step 1: Write the failing test（追加到已有 test 文件）**

在 `tests/integration/upload-batches.test.ts` 底部追加：

```typescript
const getCaseBatchesRoute = () => import("@/app/api/files/cases/[id]/upload-batches/route");

describe("GET /api/files/cases/[id]/upload-batches", () => {
  it("200 透传上游响应", async () => {
    requireSessionMock.mockResolvedValue({ user: { id: "u1" } });
    const upstreamData = {
      case_id: 1,
      upload_batches: [
        { upload_batch_id: "b1", batch_name: "批次1", doc_category: "loan_contract", status: "completed", file_count: 3 },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(upstreamData), { status: 200 })
      )
    );

    const { GET } = await getCaseBatchesRoute();
    const req = new NextRequest("http://localhost/api/files/cases/1/upload-batches");
    const res = await GET(req, { params: Promise.resolve({ id: "1" }) });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.case_id).toBe(1);
    expect(body.upload_batches).toHaveLength(1);
  });

  it("401 未认证", async () => {
    requireSessionMock.mockRejectedValue(new Error("Unauthorized"));
    const { GET } = await getCaseBatchesRoute();
    const req = new NextRequest("http://localhost/api/files/cases/1/upload-batches");
    const res = await GET(req, { params: Promise.resolve({ id: "1" }) });
    expect(res.status).toBe(401);
  });

  it("503 未配置 base url", async () => {
    requireSessionMock.mockResolvedValue({ user: { id: "u1" } });
    delete process.env.LANGGRAPH_API_BASE_URL;
    const { GET } = await getCaseBatchesRoute();
    const req = new NextRequest("http://localhost/api/files/cases/1/upload-batches");
    const res = await GET(req, { params: Promise.resolve({ id: "1" }) });
    expect(res.status).toBe(503);
  });

  it("503 上游 unreachable", async () => {
    requireSessionMock.mockResolvedValue({ user: { id: "u1" } });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    const { GET } = await getCaseBatchesRoute();
    const req = new NextRequest("http://localhost/api/files/cases/1/upload-batches");
    const res = await GET(req, { params: Promise.resolve({ id: "1" }) });
    expect(res.status).toBe(503);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm vitest run tests/integration/upload-batches.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: Implement the route**

```typescript
import { NextRequest } from "next/server";
import { requireSession } from "@/lib/api/guards";
import { unauthorizedResponse, errorResponse } from "@/lib/api/response";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    await requireSession();
  } catch {
    return unauthorizedResponse();
  }

  const { id } = await params;
  const caseIdNum = Number(id);
  if (!Number.isFinite(caseIdNum)) {
    return errorResponse("Invalid case id", 422);
  }

  const LANGGRAPH_BASE = process.env.LANGGRAPH_API_BASE_URL;
  if (!LANGGRAPH_BASE) {
    return errorResponse("LANGGRAPH_API_BASE_URL is not configured", 503);
  }

  const upstream = new URL(`${LANGGRAPH_BASE}/files/cases/${caseIdNum}/upload-batches`);
  for (const [key, value] of request.nextUrl.searchParams.entries()) {
    upstream.searchParams.set(key, value);
  }

  let upstreamRes: Response;
  try {
    upstreamRes = await fetch(upstream.toString(), {
      headers: { Accept: "application/json" },
      next: { revalidate: 0 },
    });
  } catch {
    return errorResponse("LangGraph API unreachable", 503);
  }

  let data: unknown;
  try {
    data = await upstreamRes.json();
  } catch {
    return errorResponse("LangGraph API returned non-JSON response", 502);
  }

  return Response.json(data, { status: upstreamRes.status });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm vitest run tests/integration/upload-batches.test.ts`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/integration/upload-batches.test.ts app/api/files/cases/
git commit -m "feat: add proxy route for GET /files/cases/{id}/upload-batches"
```

---

## Task 3: 扩展类型定义

**Files:**
- Modify: `lib/types/doc-categories.ts`

- [ ] **Step 1: 追加 UploadBatch 相关类型**

在 `lib/types/doc-categories.ts` 底部追加：

```typescript
// GET /files/upload-batches/{id}
export interface UploadBatchFile {
  upload_batch_link_id: number;
  file_id: number;
  file_name: string;
  file_sha256: string;
  duplicate_of: string;
  file_type: string;
  content_type: string;
  storage_provider: string;
  storage_bucket: string;
  storage_key: string;
  storage_ref: string;
  created_at: string;
  page_count: number;
  chunk_count: number;
  doc_categories: string[];
}

export interface UploadBatchPersistenceChecks {
  source_upload_batch_exists: boolean;
  source_file_upload_batch_count: number;
  source_file_count_matches: boolean;
  source_page_file_count: number;
  source_chunk_file_count: number;
  source_file_doc_category_count: number;
  all_files_have_chunks: boolean;
  all_files_have_doc_category: boolean;
}

export interface UploadBatchDetail {
  upload_batch_id: string;
  case_id: number;
  debtor_id: number;
  batch_name: string;
  doc_category: string;
  operator_id: string;
  operator_name: string;
  status: string;
  stage: string;
  file_count: number;
  new_file_count: number;
  duplicate_file_count: number;
  suspected_mismatch_file_count: number;
  records_inserted: number;
  metadata: Record<string, unknown>;
  has_conclusion_changes: boolean;
  reconciliation_item_count: number;
  add_item_count: number;
  override_item_count: number;
  change_summary: string;
  created_at: string;
  updated_at: string;
  files: UploadBatchFile[];
  persistence_checks: UploadBatchPersistenceChecks;
}

// GET /files/cases/{id}/upload-batches
export interface CaseUploadBatchItem {
  upload_batch_id: string;
  batch_name: string;
  doc_category: string;
  status: string;
  file_count: number;
  new_file_count: number;
  duplicate_file_count: number;
  created_at: string;
  updated_at: string;
}

export interface CaseUploadBatchesResp {
  case_id: number;
  upload_batches: CaseUploadBatchItem[];
}
```

- [ ] **Step 2: Commit**

```bash
git add lib/types/doc-categories.ts
git commit -m "feat: add UploadBatchDetail and CaseUploadBatch types"
```

---

## Task 4: 新增 Hook — 查询批次详情（含轮询）

**Files:**
- Create: `lib/hooks/use-upload-batch.ts`
- Test: `tests/unit/use-upload-batch.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { useUploadBatch } from "@/lib/hooks/use-upload-batch";

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

describe("useUploadBatch", () => {
  it("返回批次详情", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        upload_batch_id: "b1",
        status: "completed",
        file_count: 2,
        files: [{ file_id: 1, file_name: "a.pdf" }],
      }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const { result } = renderHook(() => useUploadBatch("b1"), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.batch).not.toBeNull());
    expect(result.current.batch?.upload_batch_id).toBe("b1");
    expect(result.current.batch?.file_count).toBe(2);
    expect(result.current.isLoading).toBe(false);
  });

  it("batchId 为 null 时不请求", async () => {
    const mockFetch = vi.fn();
    vi.stubGlobal("fetch", mockFetch);

    const { result } = renderHook(() => useUploadBatch(null), { wrapper: Wrapper });
    expect(result.current.batch).toBeNull();
    expect(result.current.isLoading).toBe(false);
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm vitest run tests/unit/use-upload-batch.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement the hook**

```typescript
"use client";

import useSWR from "swr";
import type { UploadBatchDetail } from "@/lib/types/doc-categories";

const fetcher = (url: string): Promise<UploadBatchDetail> =>
  fetch(url).then((r) => {
    if (!r.ok) throw new Error("Failed to fetch upload batch");
    return r.json();
  });

export function useUploadBatch(batchId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<UploadBatchDetail>(
    batchId !== null ? `/api/files/upload-batches/${encodeURIComponent(batchId)}` : null,
    fetcher,
    { refreshInterval: 0 }
  );

  return {
    batch: data ?? null,
    isLoading,
    error: error ? (error instanceof Error ? error.message : "Unknown error") : null,
    refresh: mutate,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm vitest run tests/unit/use-upload-batch.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/hooks/use-upload-batch.ts tests/unit/use-upload-batch.test.tsx
git commit -m "feat: add useUploadBatch hook for querying batch details"
```

---

## Task 5: 新增 Hook — 查询案件上传批次列表

**Files:**
- Create: `lib/hooks/use-case-upload-batches.ts`
- Test: `tests/unit/use-case-upload-batches.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { useCaseUploadBatches } from "@/lib/hooks/use-case-upload-batches";

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  );
}

describe("useCaseUploadBatches", () => {
  it("返回案件上传批次列表", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          case_id: 1,
          upload_batches: [
            { upload_batch_id: "b1", batch_name: "批次1", doc_category: "loan_contract", status: "completed", file_count: 2 },
          ],
        }),
      })
    );

    const { result } = renderHook(() => useCaseUploadBatches(1), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.batches).toHaveLength(1));
    expect(result.current.batches[0].upload_batch_id).toBe("b1");
    expect(result.current.isLoading).toBe(false);
  });

  it("caseId 为 null 时不请求", () => {
    const mockFetch = vi.fn();
    vi.stubGlobal("fetch", mockFetch);

    const { result } = renderHook(() => useCaseUploadBatches(null), { wrapper: Wrapper });
    expect(result.current.batches).toHaveLength(0);
    expect(result.current.isLoading).toBe(false);
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm vitest run tests/unit/use-case-upload-batches.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement the hook**

```typescript
"use client";

import useSWR from "swr";
import type { CaseUploadBatchesResp, CaseUploadBatchItem } from "@/lib/types/doc-categories";

const fetcher = (url: string): Promise<CaseUploadBatchItem[]> =>
  fetch(url).then((r) => {
    if (!r.ok) throw new Error("Failed to fetch case upload batches");
    return r.json().then((data: CaseUploadBatchesResp) => data.upload_batches ?? []);
  });

export function useCaseUploadBatches(caseId: number | null) {
  const { data, error, isLoading, mutate } = useSWR<CaseUploadBatchItem[]>(
    caseId !== null ? `/api/files/cases/${caseId}/upload-batches` : null,
    fetcher
  );

  return {
    batches: data ?? [],
    isLoading,
    error: error ? (error instanceof Error ? error.message : "Unknown error") : null,
    refresh: mutate,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm vitest run tests/unit/use-case-upload-batches.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/hooks/use-case-upload-batches.ts tests/unit/use-case-upload-batches.test.tsx
git commit -m "feat: add useCaseUploadBatches hook"
```

---

## Task 6: 扩展 useUploadIngest 支持多文件

**Files:**
- Modify: `lib/hooks/use-upload-ingest.ts`
- Modify: `app/api/ingest/upload/route.ts`

- [ ] **Step 1: 改造代理 Route 支持多文件**

修改 `app/api/ingest/upload/route.ts`，将单文件验证改为支持多文件：

```typescript
// 将原来的单文件验证替换为多文件收集
  const files: File[] = [];
  for (const [key, value] of formData.entries()) {
    if (key === "files" && value instanceof File) {
      files.push(value);
    }
  }

  if (files.length === 0) {
    return errorResponse("Missing or invalid files field", 400);
  }
```

同时把 `upstreamForm.append("files", files)` 改为循环 append：

```typescript
  const upstreamForm = new FormData();
  for (const f of files) {
    upstreamForm.append("files", f);
  }
  upstreamForm.append("case_id", caseId);
  upstreamForm.append("doc_category", docCategory);

  // 透传可选字段
  const batchName = formData.get("batch_name");
  if (typeof batchName === "string") upstreamForm.append("batch_name", batchName);
```

- [ ] **Step 2: 扩展 Hook 支持多文件和 batch_name**

```typescript
"use client";

import { useCallback } from "react";
import type { UploadAndIngestResponse } from "@/lib/types/doc-categories";

interface UploadIngestReq {
  files: File[];
  case_id: number;
  doc_category: string;
  batch_name?: string;
}

export function useUploadIngest() {
  const upload = useCallback(async (req: UploadIngestReq): Promise<UploadAndIngestResponse> => {
    const form = new FormData();
    for (const f of req.files) {
      form.append("files", f);
    }
    form.append("case_id", String(req.case_id));
    form.append("doc_category", req.doc_category);
    if (req.batch_name) {
      form.append("batch_name", req.batch_name);
    }

    const res = await fetch("/api/ingest/upload", {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Upload failed: ${res.status}`);
    }
    return res.json();
  }, []);

  return { upload };
}
```

- [ ] **Step 3: Commit**

```bash
git add lib/hooks/use-upload-ingest.ts app/api/ingest/upload/route.ts
git commit -m "feat: support multiple files and batch_name in upload"
```

---

## Task 7: 改造 AddMaterialDialog 实现完整上传状态机

**Files:**
- Modify: `components/cases/add-material-dialog.tsx`

- [ ] **Step 1: 引入新 hooks 并扩展状态**

在文件顶部新增 import：

```typescript
import { useUploadBatch } from "@/lib/hooks/use-upload-batch";
import type { UploadBatchDetail } from "@/lib/types/doc-categories";
```

扩展 Step 类型和状态：

```typescript
type Step = "select" | "validate" | "uploading" | "processing" | "completed" | "failed";
```

组件内新增状态：

```typescript
const [files, setFiles] = useState<File[]>([]);
const [batchName, setBatchName] = useState("");
const [uploadBatchId, setUploadBatchId] = useState<string | null>(null);
const [uploadResult, setUploadResult] = useState<UploadAndIngestResponse | null>(null);
const { batch, isLoading: batchLoading } = useUploadBatch(uploadBatchId);
```

- [ ] **Step 2: 实现轮询逻辑**

使用 `useEffect` 监听 `batch` 变化，实现状态机推进：

```typescript
useEffect(() => {
  if (!batch || step !== "processing") return;

  if (batch.status === "completed") {
    setStep("completed");
    setUploadBatchId(null);
  } else if (batch.status === "failed") {
    setStep("failed");
    setUploadBatchId(null);
  }
  // status === "processing" 时保持轮询（SWR 可配 refreshInterval）
}, [batch, step]);
```

修改 `useUploadBatch` 的调用为带轮询的版本：

```typescript
const { batch, isLoading: batchLoading } = useUploadBatch(
  uploadBatchId,
  step === "processing" ? 3000 : 0
);
```

需要在 `use-upload-batch.ts` 中支持 `refreshInterval` 参数。

- [ ] **Step 3: 改造为多文件选择**

将文件选择从单文件改为多文件：

```typescript
const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
  const selected = Array.from(e.target.files ?? []);
  if (selected.length === 0) return;
  setFiles((prev) => [...prev, ...selected]);
}, []);

const removeFile = (index: number) => {
  setFiles((prev) => prev.filter((_, i) => i !== index));
};
```

input 添加 `multiple` 属性：

```tsx
<input ref={inputRef} type="file" className="hidden" multiple onChange={handleFileSelect} />
```

- [ ] **Step 4: 改造 handleValidate 和 handleUpload**

```typescript
const handleValidate = async () => {
  if (!selectedCategory || files.length === 0) return;
  setStep("validate");
  try {
    const result = await validate({
      case_id: caseItem.case_id,
      doc_category: selectedCategory,
      filename: files[0].name, // 校验接口目前只支持单文件名，取第一个
    });
    setValidationResult(result);
    if (result.ok && !result.suspected_mismatch && !result.suspected_duplicate) {
      await handleUpload();
    } else {
      setStep("select");
    }
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "校验失败");
    setStep("select");
  }
};

const handleUpload = async () => {
  if (files.length === 0 || !selectedCategory) return;
  setStep("uploading");
  try {
    const result = await upload({
      files,
      case_id: caseItem.case_id,
      doc_category: selectedCategory,
      batch_name: batchName || undefined,
    });
    if (result.error) {
      throw new Error(result.error);
    }
    setUploadResult(result);
    setUploadBatchId(result.upload_batch_id);
    setStep("processing");
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "上传失败");
    setStep("failed");
  }
};
```

- [ ] **Step 5: 改造 UI — 批次名称、多文件列表、进度展示**

在类别选择下方添加批次名称输入：

```tsx
<div className="flex flex-col gap-2">
  <label className="text-xs font-medium text-muted-foreground">批次名称（可选）</label>
  <input
    value={batchName}
    onChange={(e) => setBatchName(e.target.value)}
    placeholder="如：2025年合同批次"
    className="w-full rounded-md border border-border/50 bg-background px-3 py-2 text-sm outline-none focus:border-border"
  />
</div>
```

文件区域改为多文件列表：

```tsx
<div className="flex flex-col gap-2">
  <label className="text-xs font-medium text-muted-foreground">文件</label>
  {files.length > 0 ? (
    <div className="flex flex-col gap-1.5">
      {files.map((f, i) => (
        <div key={`${f.name}-${i}`} className="flex items-center gap-2.5 rounded-md bg-muted/40 px-3 py-2 text-xs">
          <FileText className="size-3.5 shrink-0 text-muted-foreground/50" />
          <span className="min-w-0 flex-1 truncate text-foreground/80">{f.name}</span>
          <span className="shrink-0 text-muted-foreground/40">{(f.size / 1024 / 1024).toFixed(2)} MB</span>
          <button type="button" onClick={() => removeFile(i)} className="shrink-0 text-muted-foreground/30 hover:text-muted-foreground/70">
            <X className="size-3" />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="mt-1 flex items-center justify-center gap-1.5 rounded-md border border-dashed border-border/40 py-2 text-xs text-muted-foreground/60 hover:border-border/60 hover:bg-accent/10"
      >
        <Upload className="size-3.5" />
        继续添加文件
      </button>
    </div>
  ) : (
    <div
      onClick={() => inputRef.current?.click()}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed py-6 transition-colors select-none",
        "border-border/40 hover:border-border/60 hover:bg-accent/10"
      )}
    >
      <Upload className="size-5 text-muted-foreground/50" />
      <p className="text-xs text-muted-foreground/60">点击或拖拽选择文件</p>
      <p className="text-[10px] text-muted-foreground/40">支持 PDF / Word / Excel / 图片，单个 ≤ 50MB</p>
    </div>
  )}
</div>
```

- [ ] **Step 6: 添加上传中 / 完成 / 失败状态展示**

在 DialogContent 底部根据 `step` 展示不同状态：

```tsx
{step === "uploading" && (
  <div className="flex items-center gap-2 rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
    <Loader2 className="size-3.5 animate-spin" />
    正在上传文件...
  </div>
)}

{step === "processing" && (
  <div className="flex flex-col gap-2 rounded-md bg-muted/40 px-3 py-3 text-xs">
    <div className="flex items-center gap-2 text-muted-foreground">
      <Loader2 className="size-3.5 animate-spin" />
      正在解析入库...
    </div>
    <p className="text-muted-foreground/60">批次 ID: {uploadBatchId}</p>
  </div>
)}

{step === "completed" && uploadResult && (
  <div className="flex flex-col gap-2 rounded-md border border-emerald-200/60 bg-emerald-50/50 px-3 py-3 text-xs">
    <div className="flex items-center gap-2 text-emerald-700">
      <CheckCircle2 className="size-4" />
      <span className="font-medium">上传完成</span>
    </div>
    <p className="text-emerald-600/80">{uploadResult.parse_summary || "文件已入库"}</p>
    {uploadResult.new_files.length > 0 && (
      <div className="mt-1">
        <p className="text-[10px] font-medium text-emerald-700/70">新增文件</p>
        <ul className="mt-0.5 space-y-0.5">
          {uploadResult.new_files.map((name) => (
            <li key={name} className="text-[10px] text-emerald-600/60">{name}</li>
          ))}
        </ul>
      </div>
    )}
    {uploadResult.duplicate_files.length > 0 && (
      <div className="mt-1">
        <p className="text-[10px] font-medium text-amber-600/70">重复文件</p>
        <ul className="mt-0.5 space-y-0.5">
          {uploadResult.duplicate_files.map((name) => (
            <li key={name} className="text-[10px] text-amber-600/60">{name}</li>
          ))}
        </ul>
      </div>
    )}
  </div>
)}

{step === "failed" && (
  <div className="flex flex-col gap-2 rounded-md border border-red-200/60 bg-red-50/50 px-3 py-3 text-xs">
    <div className="flex items-center gap-2 text-red-700">
      <AlertTriangle className="size-4" />
      <span className="font-medium">上传失败</span>
    </div>
    <p className="text-red-600/80">请检查网络后重试</p>
  </div>
)}
```

- [ ] **Step 7: 更新按钮状态和 reset 逻辑**

重置状态时要清理新字段：

```typescript
useEffect(() => {
  if (open) {
    setSelectedCategory("");
    setFiles([]);
    setBatchName("");
    setStep("select");
    setValidationResult(null);
    setUploadBatchId(null);
    setUploadResult(null);
  }
}, [open]);
```

更新 submit 条件：

```typescript
const canSubmit = selectedCategory && files.length > 0 && (step === "select" || step === "completed" || step === "failed");
```

Footer 按钮根据 step 调整：

```tsx
<DialogFooter>
  <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)} disabled={step === "uploading" || step === "processing"}>
    {step === "completed" || step === "failed" ? "关闭" : "取消"}
  </Button>
  {step === "completed" || step === "failed" ? (
    <Button size="sm" onClick={() => {
      setStep("select");
      setFiles([]);
      setBatchName("");
      setValidationResult(null);
      setUploadBatchId(null);
      setUploadResult(null);
    }}>
      继续上传
    </Button>
  ) : (
    <Button size="sm" onClick={handleValidate} disabled={!canSubmit}>
      {(step === "validate" || step === "uploading") && <Loader2 className="size-3 animate-spin" data-icon="inline-start" />}
      确认上传
    </Button>
  )}
</DialogFooter>
```

- [ ] **Step 8: Commit**

```bash
git add components/cases/add-material-dialog.tsx
git commit -m "feat: redesign AddMaterialDialog with multi-file, batch name, and polling"
```

---

## Task 8: 为 useUploadBatch 添加轮询支持

**Files:**
- Modify: `lib/hooks/use-upload-batch.ts`

- [ ] **Step 1: 添加 refreshInterval 参数**

```typescript
"use client";

import useSWR from "swr";
import type { UploadBatchDetail } from "@/lib/types/doc-categories";

const fetcher = (url: string): Promise<UploadBatchDetail> =>
  fetch(url).then((r) => {
    if (!r.ok) throw new Error("Failed to fetch upload batch");
    return r.json();
  });

export function useUploadBatch(batchId: string | null, refreshInterval = 0) {
  const { data, error, isLoading, mutate } = useSWR<UploadBatchDetail>(
    batchId !== null ? `/api/files/upload-batches/${encodeURIComponent(batchId)}` : null,
    fetcher,
    { refreshInterval }
  );

  return {
    batch: data ?? null,
    isLoading,
    error: error ? (error instanceof Error ? error.message : "Unknown error") : null,
    refresh: mutate,
  };
}
```

- [ ] **Step 2: Commit**

```bash
git add lib/hooks/use-upload-batch.ts
git commit -m "feat: support polling interval in useUploadBatch"
```

---

## Task 9: 运行全部测试验证

**Files:**
- All modified files

- [ ] **Step 1: 运行所有新增和受影响的测试**

Run:
```bash
pnpm vitest run tests/integration/upload-batches.test.ts tests/unit/use-upload-batch.test.tsx tests/unit/use-case-upload-batches.test.tsx
```

Expected: PASS

- [ ] **Step 2: 运行类型检查**

Run:
```bash
pnpm tsc --noEmit
```

Expected: 无类型错误

- [ ] **Step 3: Commit（如有修复）**

```bash
git add -A
git commit -m "fix: typecheck and test fixes" || echo "no fixes needed"
```

---

## Spec Coverage Check

| Spec 要求 | 对应 Task |
|-----------|-----------|
| 查询上传批次详情 `GET /files/upload-batches/{id}` | Task 1, 4, 8 |
| 查询案件上传批次列表 `GET /files/cases/{id}/upload-batches` | Task 2, 5 |
| 上传文件并异步触发摄入 `POST /files/upload-and-ingest` | Task 6, 7 |
| 多文件上传 | Task 6, 7 |
| 批次名称 | Task 6, 7 |
| 上传前校验 | Task 7（复用现有 validate 逻辑） |
| 状态轮询（stored → processing → completed/failed） | Task 7, 8 |
| 结果展示（新增/重复/失败文件列表） | Task 7 |
| 代理层测试 | Task 1, 2 |
| Hook 测试 | Task 4, 5 |

---

## Placeholder Scan

- ✅ 无 "TBD" / "TODO" / "implement later"
- ✅ 所有步骤包含实际代码
- ✅ 所有测试包含具体断言
- ✅ 类型名称前后一致

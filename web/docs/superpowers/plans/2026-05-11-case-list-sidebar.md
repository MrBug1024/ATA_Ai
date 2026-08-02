# 案件列表侧边栏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a case list section to the app sidebar that proxies `GET /api/cases` to an internal backend, displays each case with name, debtor, risk-score badge, and status, supports 300ms-debounced keyword search and load-more pagination, and navigates to `/chat` with a pre-filled composer when a case is clicked.

**Architecture:** A new Next.js proxy route (`app/api/cases/route.ts`) forwards auth-guarded requests to `http://10.0.10.2:8080/api/cases`. A SWR hook (`lib/hooks/use-cases.ts`) manages `keyword`/`page` state and accumulates pages. An internal `CaseList` component in `components/layout/app-sidebar.tsx` renders the list. The chat page (`app/(main)/chat/page.tsx`) reads `case_id`, `case_name`, and `debtor` URL params and passes `initialComposerValue` to `ChatThread`. An internal `ComposerInitializer` component calls `useAui().composer().setText()` on mount to pre-fill the input.

**Tech Stack:** Next.js App Router, SWR, shadcn/ui sidebar primitives, `@assistant-ui/react` (`useAui`), Tailwind CSS v4, Vitest

---

### Task 1: API proxy route

**Files:**
- Create: `app/api/cases/route.ts`
- Modify: `.env.example`
- Test: `tests/integration/cases.test.ts`

- [x] **Step 1: Write the failing test**

```ts
// tests/integration/cases.test.ts
import { describe, it, expect } from "vitest";
import { NextRequest } from "next/server";

const getRoute = () => import("@/app/api/cases/route");

describe("GET /api/cases", () => {
  it("无认证时返回 4xx", async () => {
    const { GET } = await getRoute();
    const req = new NextRequest("http://localhost:3000/api/cases");
    const res = await GET(req);
    expect([400, 401]).toContain(res.status);
    const body = await res.json();
    expect(body.success).toBe(false);
  });

  it("带参数无认证也返回 4xx", async () => {
    const { GET } = await getRoute();
    const req = new NextRequest(
      "http://localhost:3000/api/cases?keyword=test&page=1&page_size=20"
    );
    const res = await GET(req);
    expect([400, 401]).toContain(res.status);
  });
});
```

- [x] **Step 2: Run test to verify it fails**

```bash
pnpm test tests/integration/cases.test.ts
```

Expected: FAIL — `Cannot find module '@/app/api/cases/route'`

- [x] **Step 3: Add `CASES_API_BASE_URL` to `.env.example`**

Append to `.env.example`:

```
# Cases API (internal network)
CASES_API_BASE_URL=http://10.0.10.2:8080
```

- [x] **Step 4: Create `app/api/cases/route.ts`**

```ts
import { NextRequest } from "next/server";
import { requireSession } from "@/lib/api/guards";
import { unauthorizedResponse } from "@/lib/api/response";

const CASES_BASE = process.env.CASES_API_BASE_URL ?? "http://10.0.10.2:8080";

export async function GET(request: NextRequest) {
  try {
    await requireSession();
  } catch {
    return unauthorizedResponse();
  }

  const upstream = new URL(`${CASES_BASE}/api/cases`);
  for (const [key, value] of request.nextUrl.searchParams.entries()) {
    upstream.searchParams.set(key, value);
  }

  try {
    const upstreamRes = await fetch(upstream.toString(), {
      headers: { "Content-Type": "application/json" },
      next: { revalidate: 0 },
    });
    const data: unknown = await upstreamRes.json();
    return Response.json(data, { status: upstreamRes.status });
  } catch {
    return Response.json(
      { success: false, error: "Cases API unreachable" },
      { status: 503 }
    );
  }
}
```

- [x] **Step 5: Run test to verify it passes**

```bash
pnpm test tests/integration/cases.test.ts
```

Expected: PASS (2 tests)

- [x] **Step 6: Commit**

```bash
git add app/api/cases/route.ts tests/integration/cases.test.ts .env.example
git commit -m "feat: add /api/cases proxy route with auth guard"
```

---

### Task 2: useCases SWR hook

**Files:**
- Create: `lib/hooks/use-cases.ts`

- [x] **Step 1: Create `lib/hooks/use-cases.ts`**

```ts
"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import useSWR from "swr";

export interface Case {
  id: number;
  case_name: string;
  case_type: string;
  debtor_name: string;
  status: string;
  composite_score?: number;
  delta_score?: number;
  valuation_score?: number;
  deadline_score?: number;
  behavioral_score?: number;
}

interface CasesApiResponse {
  cases: Case[];
  total: number;
  page: number;
  page_size: number;
}

export interface UseCasesResult {
  cases: Case[];
  isLoading: boolean;
  error: unknown;
  total: number;
  page: number;
  setPage: (p: number) => void;
  keyword: string;
  setKeyword: (k: string) => void;
}

const fetcher = (url: string): Promise<CasesApiResponse> =>
  fetch(url).then((r) => {
    if (!r.ok) throw new Error("Failed to fetch cases");
    return r.json();
  });

export function useCases(): UseCasesResult {
  const [keyword, setKeywordState] = useState("");
  const [page, setPage] = useState(1);
  const [cases, setCases] = useState<Case[]>([]);
  const [total, setTotal] = useState(0);
  const pageRef = useRef(page);
  pageRef.current = page;

  const setKeyword = useCallback((k: string) => {
    setKeywordState(k);
    setPage(1);
  }, []);

  const params = new URLSearchParams({
    page: String(page),
    page_size: "20",
  });
  if (keyword) params.set("keyword", keyword);
  const url = `/api/cases?${params.toString()}`;

  const { data, isLoading, error } = useSWR<CasesApiResponse>(url, fetcher);

  useEffect(() => {
    if (!data) return;
    setTotal(data.total);
    setCases((prev) =>
      pageRef.current === 1 ? data.cases : [...prev, ...data.cases]
    );
  }, [data]);

  return {
    cases,
    isLoading,
    error,
    total,
    page,
    setPage,
    keyword,
    setKeyword,
  };
}
```

- [x] **Step 2: Verify TypeScript compiles**

```bash
pnpm build 2>&1 | grep -E "error|Error" | grep -v "node_modules" | head -20
```

Expected: no new errors from `lib/hooks/use-cases.ts`

- [x] **Step 3: Commit**

```bash
git add lib/hooks/use-cases.ts
git commit -m "feat: add useCases SWR hook with keyword search and load-more"
```

---

### Task 3: CaseList section in sidebar

**Files:**
- Modify: `components/layout/app-sidebar.tsx`

The current file has these imports on lines 1–39 and ends at line 366. The relevant structure in `AppSidebar`'s content JSX (lines 108–171):

```
<SidebarContent>
  {/* New conversation button */}
  <SidebarGroup ...>...</SidebarGroup>

  {/* Navigation */}
  <SidebarGroup ...>...</SidebarGroup>

  <SidebarSeparator />         ← line 157

  {/* Conversation list */}
  <SidebarGroup className="flex-1 overflow-hidden py-1">
    ...
  </SidebarGroup>
</SidebarContent>
```

The `CaseList` component will own its own `<SidebarSeparator />` on both sides and replaces the existing standalone one.

- [x] **Step 1: Add import for `useCases` and `Case` at the top of the file**

In `components/layout/app-sidebar.tsx`, add after the existing imports (after line 39, before line 41):

```ts
import { useCases, type Case } from "@/lib/hooks/use-cases";
```

- [x] **Step 2: Replace the existing `<SidebarSeparator />` in `AppSidebar` with `<CaseList />`**

Find (in `AppSidebar`'s JSX, around line 157–160):

```tsx
        <SidebarSeparator />

        {/* Conversation list */}
```

Replace with:

```tsx
        <CaseList />

        {/* Conversation list */}
```

`CaseList` renders its own `<SidebarSeparator />` before and after itself.

- [x] **Step 3: Add `ScoreBadge`, `StatusBadge`, and `CaseList` components at the end of the file (after `ConversationList`)**

Append to `components/layout/app-sidebar.tsx` before the final closing:

```tsx
function ScoreBadge({ score }: { score?: number }) {
  if (score === undefined || score === null) {
    return (
      <span className="shrink-0 rounded px-1 py-0.5 text-[9px] font-medium text-emerald-400 bg-emerald-400/10">
        —
      </span>
    );
  }
  const color =
    score >= 75
      ? "text-red-400 bg-red-400/10"
      : score >= 50
      ? "text-amber-400 bg-amber-400/10"
      : "text-emerald-400 bg-emerald-400/10";
  return (
    <span className={cn("shrink-0 rounded px-1 py-0.5 text-[9px] font-medium", color)}>
      {score}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className="shrink-0 rounded bg-sidebar-accent px-1 py-0.5 text-[9px] text-sidebar-foreground/60">
      {status}
    </span>
  );
}

function CaseList() {
  const router = useRouter();
  const { cases, isLoading, error, total, page, setPage, keyword, setKeyword } =
    useCases();
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [inputValue, setInputValue] = useState("");

  // 300ms debounce
  useEffect(() => {
    const t = setTimeout(() => setKeyword(inputValue), 300);
    return () => clearTimeout(t);
  }, [inputValue, setKeyword]);

  const handleCaseClick = (c: Case) => {
    const params = new URLSearchParams({
      case_id: String(c.id),
      case_name: c.case_name,
      debtor: c.debtor_name,
    });
    router.push(`/chat?${params.toString()}`);
  };

  const hasMore = cases.length < total;

  return (
    <>
      <SidebarSeparator />
      <SidebarGroup className="py-1">
        <SidebarGroupLabel className="flex items-center justify-between">
          <span>案件列表</span>
          <button
            type="button"
            onClick={() => {
              setIsSearchOpen((v) => !v);
              if (isSearchOpen) {
                setInputValue("");
                setKeyword("");
              }
            }}
            className={cn(
              "flex size-5 items-center justify-center rounded text-sidebar-foreground/50",
              "hover:bg-sidebar-accent hover:text-sidebar-foreground transition-colors",
              isSearchOpen && "bg-sidebar-accent text-sidebar-foreground"
            )}
            aria-label="搜索案件"
          >
            <Search className="h-3 w-3" />
          </button>
        </SidebarGroupLabel>

        {isSearchOpen && (
          <div className="px-2 pb-1">
            <input
              autoFocus
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setIsSearchOpen(false);
                  setInputValue("");
                  setKeyword("");
                }
              }}
              placeholder="搜索案件..."
              className="w-full rounded-md border border-sidebar-border bg-sidebar-accent/50 px-2.5 py-1 text-xs text-sidebar-foreground placeholder:text-sidebar-foreground/40 outline-none focus:border-sidebar-foreground/30"
            />
          </div>
        )}

        <SidebarGroupContent className="max-h-[240px] overflow-y-auto">
          {isLoading && cases.length === 0 && (
            <div className="flex justify-center py-4">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-sidebar-foreground/30" />
            </div>
          )}

          {!!error && (
            <div className="px-2 py-2 text-xs text-sidebar-foreground/40">
              加载失败
              <button
                type="button"
                className="ml-2 text-sidebar-foreground/60 underline hover:text-sidebar-foreground"
                onClick={() => setKeyword(keyword)}
              >
                重试
              </button>
            </div>
          )}

          {!isLoading && !error && cases.length === 0 && (
            <p className="px-2 py-2 text-xs text-sidebar-foreground/40">暂无案件</p>
          )}

          {cases.length > 0 && (
            <SidebarMenu>
              {cases.map((c) => (
                <SidebarMenuItem key={c.id}>
                  <SidebarMenuButton
                    onClick={() => handleCaseClick(c)}
                    className="h-auto flex-col items-start gap-0.5 py-2"
                  >
                    <div className="flex w-full items-center gap-1">
                      <span className="min-w-0 flex-1 truncate text-xs">{c.case_name}</span>
                      <ScoreBadge score={c.composite_score} />
                    </div>
                    <div className="flex w-full items-center gap-1">
                      <span className="min-w-0 flex-1 truncate text-[10px] text-sidebar-foreground/50">
                        {c.debtor_name}
                      </span>
                      <StatusBadge status={c.status} />
                    </div>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          )}

          {hasMore && (
            <button
              type="button"
              onClick={() => setPage(page + 1)}
              disabled={isLoading}
              className="mt-1 w-full rounded px-2 py-1.5 text-[10px] text-sidebar-foreground/50 hover:bg-sidebar-accent hover:text-sidebar-foreground transition-colors disabled:opacity-50"
            >
              {isLoading ? "加载中…" : "加载更多"}
            </button>
          )}
        </SidebarGroupContent>
      </SidebarGroup>
      <SidebarSeparator />
    </>
  );
}
```

- [x] **Step 4: Verify build**

```bash
pnpm build 2>&1 | grep -E "^.*error" | grep -v "node_modules" | head -20
```

Expected: no new TypeScript errors

- [x] **Step 5: Start dev server and verify visually**

```bash
pnpm dev
```

Open http://localhost:3000:
- Sidebar shows "案件列表" section between navigation and "最近对话"
- If `http://10.0.10.2:8080` is unreachable: section shows "加载失败" + retry button (no crash, no spinner loop)
- If reachable: cases render with name, debtor, colored score badge, status badge
- Search icon toggles input; typing filters after 300ms
- "加载更多" button appears when `cases.length < total`

- [x] **Step 6: Commit**

```bash
git add components/layout/app-sidebar.tsx
git commit -m "feat: add CaseList section to app sidebar with risk badges and search"
```

---

### Task 4 + 5: Chat page pre-fill from URL params

These two tasks are tightly coupled (Task 4 introduces a prop that Task 5 types), so they are implemented and committed together.

**Files:**
- Modify: `app/(main)/chat/page.tsx`
- Modify: `components/chat/chatgpt-thread.tsx`

#### chat/page.tsx changes

- [x] **Step 1: Add `useSearchParams` to imports in `app/(main)/chat/page.tsx`**

Current import on line 3:
```ts
import { useRouter } from "next/navigation";
```

Replace with:
```ts
import { useRouter, useSearchParams } from "next/navigation";
```

- [x] **Step 2: Read URL params and build `initialComposerValue`**

In `ChatPage`'s function body, after the existing `useState`/`useEffect` hooks, add:

```ts
const searchParams = useSearchParams();
const caseId = searchParams.get("case_id");
const caseName = searchParams.get("case_name");
const debtor = searchParams.get("debtor");

const initialComposerValue = caseId
  ? `分析案件 #${caseId}（${caseName}，债务人：${debtor}）：`
  : undefined;
```

- [x] **Step 3: Pass `initialComposerValue` to `ChatThread`**

Find:
```tsx
          <ChatThread suggestions={SUGGESTIONS[appType]} />
```

Replace with:
```tsx
          <ChatThread
            suggestions={SUGGESTIONS[appType]}
            initialComposerValue={initialComposerValue}
          />
```

#### chatgpt-thread.tsx changes

- [x] **Step 4: Add `useAui` to imports in `components/chat/chatgpt-thread.tsx`**

Current import (line 4–14):
```ts
import {
  ActionBarPrimitive,
  ActionBarMorePrimitive,
  AuiIf,
  BranchPickerPrimitive,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
} from "@assistant-ui/react";
```

Replace with:
```ts
import {
  ActionBarPrimitive,
  ActionBarMorePrimitive,
  AuiIf,
  BranchPickerPrimitive,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
  useAui,
} from "@assistant-ui/react";
```

- [x] **Step 5: Add `initialComposerValue` to `ChatThreadProps` and update `ChatThread` signature**

Find:
```ts
interface ChatThreadProps {
  suggestions?: string[];
  hasInitialMessages?: boolean;
}

export function ChatThread({ suggestions, hasInitialMessages }: ChatThreadProps) {
```

Replace with:
```ts
interface ChatThreadProps {
  suggestions?: string[];
  hasInitialMessages?: boolean;
  initialComposerValue?: string;
}

export function ChatThread({ suggestions, hasInitialMessages, initialComposerValue }: ChatThreadProps) {
```

- [x] **Step 6: Add `ComposerInitializer` component (anywhere in the file, before `ChatThread`)**

Add this component before the `ChatThread` function:

```tsx
function ComposerInitializer({ value }: { value: string }) {
  const aui = useAui();
  useEffect(() => {
    aui.composer().setText(value);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}
```

- [x] **Step 7: Render `ComposerInitializer` inside `ThreadPrimitive.Root`**

Find inside `ChatThread`'s return:
```tsx
    <ThreadPrimitive.Root
      className="aui-root aui-thread-root @container flex h-full flex-col bg-background"
      style={{
        ["--thread-max-width" as string]: "56rem",
        ["--composer-radius" as string]: "24px",
        ["--composer-padding" as string]: "10px",
      }}
    >
      <ThreadPrimitive.Viewport
```

Replace with:
```tsx
    <ThreadPrimitive.Root
      className="aui-root aui-thread-root @container flex h-full flex-col bg-background"
      style={{
        ["--thread-max-width" as string]: "56rem",
        ["--composer-radius" as string]: "24px",
        ["--composer-padding" as string]: "10px",
      }}
    >
      {initialComposerValue && <ComposerInitializer value={initialComposerValue} />}
      <ThreadPrimitive.Viewport
```

- [x] **Step 8: Run tests and verify build**

```bash
pnpm test
pnpm build 2>&1 | grep -E "^.*error" | grep -v "node_modules" | head -20
```

Expected: all existing tests pass; build succeeds

- [x] **Step 9: Test the full case-click → pre-fill flow**

```bash
pnpm dev
```

Navigate to: `http://localhost:3000/chat?case_id=42&case_name=合同纠纷案&debtor=李四`

Expected: chat composer is pre-filled with `分析案件 #42（合同纠纷案，债务人：李四）：`

If the internal API is available:
1. Open sidebar
2. Click a case item
3. Verify redirect to `/chat?case_id=...&case_name=...&debtor=...`
4. Verify composer is pre-filled
5. Type additional text and send — verify conversation starts normally

- [x] **Step 10: Commit**

```bash
git add app/\(main\)/chat/page.tsx components/chat/chatgpt-thread.tsx
git commit -m "feat: pre-fill chat composer with case context from URL params"
```

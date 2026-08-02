# 案件列表卷宗上传功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 替换案件列表页"添加材料"功能，接入卷宗上传体系（字典、覆盖情况、校验、上传四接口）

**Architecture:** 新增 4 个 Next.js API Route 代理外部接口，新增类型定义和 4 个 SWR hooks，重写 `AddMaterialDialog` 组件实现选择类别→展示覆盖网格→校验→上传的完整流程。

**Tech Stack:** Next.js 16, TypeScript, React, SWR, Tailwind CSS, shadcn/ui, Sonner toast

---

## 文件结构

| 文件 | 操作 | 说明 |
|---|---|---|
| `.env.example` | 修改 | 新增 `LANGGRAPH_API_BASE_URL` |
| `lib/types/doc-categories.ts` | 创建 | 卷宗相关 TypeScript 类型 |
| `lib/hooks/use-doc-categories.ts` | 创建 | 获取字典 hook (SWR) |
| `lib/hooks/use-case-doc-categories.ts` | 创建 | 获取案件覆盖情况 hook (SWR) |
| `lib/hooks/use-validate-doc-category.ts` | 创建 | 校验 hook (SWR mutation) |
| `lib/hooks/use-upload-ingest.ts` | 创建 | 上传 hook (SWR mutation) |
| `app/api/doc-categories/route.ts` | 创建 | 代理字典接口 |
| `app/api/cases/[caseId]/doc-categories/route.ts` | 创建 | 代理覆盖情况接口 |
| `app/api/ingest/validate-doc-category/route.ts` | 创建 | 代理校验接口 |
| `app/api/ingest/upload/route.ts` | 创建 | 代理上传接口 (multipart) |
| `components/cases/add-material-dialog.tsx` | 重写 | 卷宗上传对话框 |

---

## Task 1: 环境变量

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: 添加 LANGGRAPH_API_BASE_URL**

```bash
# 在 CASES_API_BASE_URL 下方添加

# LangGraph API (文件上传与摄入)
LANGGRAPH_API_BASE_URL=http://10.0.10.2:8081
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "chore: add LANGGRAPH_API_BASE_URL to env example"
```

---

## Task 2: 类型定义

**Files:**
- Create: `lib/types/doc-categories.ts`

- [ ] **Step 1: 创建类型文件**

```typescript
// lib/types/doc-categories.ts

// GET /api/ingest/doc-categories
export interface DocCategory {
  code: string;
  name: string;
  description: string;
  sort_order: number;
  enabled: boolean;
  fields: string[];
}

export interface DocCategoriesResp {
  categories: DocCategory[];
}

// GET /api/case/{case_id}/doc-categories
export interface CaseDocCategoryItem {
  code: string;
  name: string;
  uploaded: boolean;
  file_count: number;
  record_count: number;
  last_uploaded_at: string | null;
}

export interface CaseDocCategoriesResp {
  case_id: number;
  categories: CaseDocCategoryItem[];
  missing_categories: string[];
}

// POST /api/ingest/validate-doc-category
export interface ValidateDocCategoryReq {
  case_id: number;
  doc_category: string;
  filename: string;
  preview_text?: string;
}

export interface ValidateDocCategoryResp {
  ok: boolean;
  suspected_mismatch: boolean;
  suspected_duplicate: boolean;
  message: string;
}

// POST /files/upload-and-ingest
export interface UploadBatchSummary {
  material_event_id: string;
  material_event_type: string;
  material_event_status: string;
  upload_batch_id: string;
  batch_name: string;
  doc_category: string;
  operator_id: string;
  operator_name: string;
  file_count: number;
  new_file_count: number;
  duplicate_file_count: number;
  suspected_mismatch_file_count: number;
  status: string;
  stage: string;
  has_conclusion_changes: boolean;
  reconciliation_item_count: number;
  add_item_count: number;
  override_item_count: number;
  change_summary: string;
}

export interface DocCategoryValidation {
  ok: boolean;
  suspected_mismatch: boolean;
  suspected_duplicate: boolean;
  duplicate_files: string[];
  suspected_mismatch_files: string[];
  message: string;
}

export interface CaseDocCategoryStatus {
  case_id: number;
  categories: CaseDocCategoryItem[];
  missing_categories: string[];
}

export interface UploadAndIngestResponse {
  current_case_id: number;
  current_debtor_id: number;
  current_debtor_name: string;
  ingest_payload_ref: string;
  ingest_payload_summary: string;
  aggregated_text_ref: string;
  aggregated_text_length: number;
  aggregated_text_preview: string;
  doc_category: string;
  batch_name: string;
  upload_batch_id: string;
  upload_batch_detail_path: string;
  case_upload_batches_path: string;
  operator_id: string;
  operator_name: string;
  upload_batch_summary: UploadBatchSummary;
  has_conclusion_changes: boolean;
  reconciliation_item_count: number;
  add_item_count: number;
  override_item_count: number;
  change_summary: string;
  parse_summary: string;
  categories_found: string[];
  recognized_categories: string[];
  records_inserted: number;
  parse_document_result_ref: string;
  parse_document_result_keys: string[];
  doc_category_validation: DocCategoryValidation;
  case_doc_category_status: CaseDocCategoryStatus;
  missing_categories: string[];
  duplicate_files: string[];
  suspected_mismatch_files: string[];
  new_files: string[];
  uploaded_file_count: number;
  error: string | null;
}
```

- [ ] **Step 2: Commit**

```bash
git add lib/types/doc-categories.ts
git commit -m "feat: add doc category types"
```

---

## Task 3: API Route — 字典接口

**Files:**
- Create: `app/api/doc-categories/route.ts`

- [ ] **Step 1: 创建路由**

```typescript
import { NextRequest } from "next/server";
import { requireSession } from "@/lib/api/guards";
import { unauthorizedResponse, errorResponse } from "@/lib/api/response";

export async function GET(request: NextRequest) {
  try {
    await requireSession();
  } catch {
    return unauthorizedResponse();
  }

  const CASES_BASE = process.env.CASES_API_BASE_URL;
  if (!CASES_BASE) {
    return errorResponse("CASES_API_BASE_URL is not configured", 503);
  }

  const upstream = new URL(`${CASES_BASE}/api/ingest/doc-categories`);
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
    return errorResponse("Cases API unreachable", 503);
  }

  let data: unknown;
  try {
    data = await upstreamRes.json();
  } catch {
    return errorResponse("Cases API returned non-JSON response", 502);
  }

  return Response.json(data, { status: upstreamRes.status });
}
```

- [ ] **Step 2: Commit**

```bash
git add app/api/doc-categories/route.ts
git commit -m "feat: add doc categories proxy API route"
```

---

## Task 4: API Route — 案件覆盖情况接口

**Files:**
- Create: `app/api/cases/[caseId]/doc-categories/route.ts`

- [ ] **Step 1: 创建路由**

```typescript
import { NextRequest } from "next/server";
import { requireSession } from "@/lib/api/guards";
import { unauthorizedResponse, errorResponse } from "@/lib/api/response";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ caseId: string }> }
) {
  try {
    await requireSession();
  } catch {
    return unauthorizedResponse();
  }

  const { caseId } = await params;
  const caseIdNum = Number(caseId);
  if (!Number.isFinite(caseIdNum)) {
    return errorResponse("Invalid caseId", 422);
  }

  const CASES_BASE = process.env.CASES_API_BASE_URL;
  if (!CASES_BASE) {
    return errorResponse("CASES_API_BASE_URL is not configured", 503);
  }

  const upstream = new URL(`${CASES_BASE}/api/case/${caseIdNum}/doc-categories`);
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
    return errorResponse("Cases API unreachable", 503);
  }

  let data: unknown;
  try {
    data = await upstreamRes.json();
  } catch {
    return errorResponse("Cases API returned non-JSON response", 502);
  }

  return Response.json(data, { status: upstreamRes.status });
}
```

- [ ] **Step 2: Commit**

```bash
git add "app/api/cases/[caseId]/doc-categories/route.ts"
git commit -m "feat: add case doc categories proxy API route"
```

---

## Task 5: API Route — 校验接口

**Files:**
- Create: `app/api/ingest/validate-doc-category/route.ts`

- [ ] **Step 1: 创建路由**

```typescript
import { NextRequest } from "next/server";
import { requireSession } from "@/lib/api/guards";
import { unauthorizedResponse, errorResponse } from "@/lib/api/response";

export async function POST(request: NextRequest) {
  try {
    await requireSession();
  } catch {
    return unauthorizedResponse();
  }

  const CASES_BASE = process.env.CASES_API_BASE_URL;
  if (!CASES_BASE) {
    return errorResponse("CASES_API_BASE_URL is not configured", 503);
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return errorResponse("Invalid JSON body", 400);
  }

  let upstreamRes: Response;
  try {
    upstreamRes = await fetch(`${CASES_BASE}/api/ingest/validate-doc-category`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return errorResponse("Cases API unreachable", 503);
  }

  let data: unknown;
  try {
    data = await upstreamRes.json();
  } catch {
    return errorResponse("Cases API returned non-JSON response", 502);
  }

  return Response.json(data, { status: upstreamRes.status });
}
```

- [ ] **Step 2: Commit**

```bash
git add app/api/ingest/validate-doc-category/route.ts
git commit -m "feat: add validate doc category proxy API route"
```

---

## Task 6: API Route — 上传接口

**Files:**
- Create: `app/api/ingest/upload/route.ts`

- [ ] **Step 1: 创建路由**

```typescript
import { NextRequest } from "next/server";
import { requireSession } from "@/lib/api/guards";
import { unauthorizedResponse, errorResponse } from "@/lib/api/response";

export async function POST(request: NextRequest) {
  try {
    await requireSession();
  } catch {
    return unauthorizedResponse();
  }

  const LANGGRAPH_BASE = process.env.LANGGRAPH_API_BASE_URL;
  if (!LANGGRAPH_BASE) {
    return errorResponse("LANGGRAPH_API_BASE_URL is not configured", 503);
  }

  let formData: FormData;
  try {
    formData = await request.formData();
  } catch {
    return errorResponse("Invalid form data", 400);
  }

  // Validate required fields
  const files = formData.get("files");
  const caseId = formData.get("case_id");
  const docCategory = formData.get("doc_category");

  if (!files || !(files instanceof File)) {
    return errorResponse("Missing or invalid files field", 400);
  }
  if (!caseId || typeof caseId !== "string") {
    return errorResponse("Missing case_id", 400);
  }
  if (!docCategory || typeof docCategory !== "string") {
    return errorResponse("Missing doc_category", 400);
  }

  // Forward to LangGraph
  const upstreamForm = new FormData();
  upstreamForm.append("files", files);
  upstreamForm.append("case_id", caseId);
  upstreamForm.append("doc_category", docCategory);

  let upstreamRes: Response;
  try {
    upstreamRes = await fetch(`${LANGGRAPH_BASE}/files/upload-and-ingest`, {
      method: "POST",
      body: upstreamForm,
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

- [ ] **Step 2: Commit**

```bash
git add app/api/ingest/upload/route.ts
git commit -m "feat: add upload and ingest proxy API route"
```

---

## Task 7: Hooks

**Files:**
- Create: `lib/hooks/use-doc-categories.ts`
- Create: `lib/hooks/use-case-doc-categories.ts`
- Create: `lib/hooks/use-validate-doc-category.ts`
- Create: `lib/hooks/use-upload-ingest.ts`

- [ ] **Step 1: use-doc-categories**

```typescript
"use client";

import useSWR from "swr";
import type { DocCategoriesResp } from "@/lib/types/doc-categories";

const fetcher = (url: string): Promise<DocCategoriesResp> =>
  fetch(url).then((r) => {
    if (!r.ok) throw new Error("Failed to fetch doc categories");
    return r.json();
  });

export function useDocCategories() {
  const { data, error, isLoading } = useSWR<DocCategoriesResp>("/api/doc-categories", fetcher);
  return {
    categories: data?.categories ?? [],
    isLoading,
    error,
  };
}
```

- [ ] **Step 2: use-case-doc-categories**

```typescript
"use client";

import useSWR from "swr";
import type { CaseDocCategoriesResp } from "@/lib/types/doc-categories";

const fetcher = (url: string): Promise<CaseDocCategoriesResp> =>
  fetch(url).then((r) => {
    if (!r.ok) throw new Error("Failed to fetch case doc categories");
    return r.json();
  });

export function useCaseDocCategories(caseId: number | null) {
  const { data, error, isLoading } = useSWR<CaseDocCategoriesResp>(
    caseId !== null ? `/api/cases/${caseId}/doc-categories` : null,
    fetcher
  );
  return {
    caseDocCategories: data,
    isLoading,
    error,
  };
}
```

- [ ] **Step 3: use-validate-doc-category**

```typescript
"use client";

import { useCallback } from "react";
import type { ValidateDocCategoryReq, ValidateDocCategoryResp } from "@/lib/types/doc-categories";

export function useValidateDocCategory() {
  const validate = useCallback(async (req: ValidateDocCategoryReq): Promise<ValidateDocCategoryResp> => {
    const res = await fetch("/api/ingest/validate-doc-category", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Validation failed: ${res.status}`);
    }
    return res.json();
  }, []);

  return { validate };
}
```

- [ ] **Step 4: use-upload-ingest**

```typescript
"use client";

import { useCallback } from "react";
import type { UploadAndIngestResponse } from "@/lib/types/doc-categories";

interface UploadIngestReq {
  files: File;
  case_id: number;
  doc_category: string;
}

export function useUploadIngest() {
  const upload = useCallback(async (req: UploadIngestReq): Promise<UploadAndIngestResponse> => {
    const form = new FormData();
    form.append("files", req.files);
    form.append("case_id", String(req.case_id));
    form.append("doc_category", req.doc_category);

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

- [ ] **Step 5: Commit**

```bash
git add lib/hooks/use-doc-categories.ts lib/hooks/use-case-doc-categories.ts lib/hooks/use-validate-doc-category.ts lib/hooks/use-upload-ingest.ts
git commit -m "feat: add doc category upload hooks"
```

---

## Task 8: 重写 AddMaterialDialog 组件

**Files:**
- Modify: `components/cases/add-material-dialog.tsx`

- [ ] **Step 1: 重写组件**

```tsx
"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Upload,
  X,
  Loader2,
  FileText,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  ChevronDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Case } from "@/lib/hooks/use-cases";
import { useDocCategories } from "@/lib/hooks/use-doc-categories";
import { useCaseDocCategories } from "@/lib/hooks/use-case-doc-categories";
import { useValidateDocCategory } from "@/lib/hooks/use-validate-doc-category";
import { useUploadIngest } from "@/lib/hooks/use-upload-ingest";
import type { DocCategory, CaseDocCategoryItem } from "@/lib/types/doc-categories";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  caseItem: Case;
}

type Step = "select" | "validate" | "uploading";

export function AddMaterialDialog({ open, onOpenChange, caseItem }: Props) {
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [step, setStep] = useState<Step>("select");
  const [validationResult, setValidationResult] = useState<{
    ok: boolean;
    suspected_mismatch: boolean;
    suspected_duplicate: boolean;
    message: string;
  } | null>(null);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const { categories, isLoading: categoriesLoading } = useDocCategories();
  const { caseDocCategories, isLoading: caseDocCategoriesLoading } = useCaseDocCategories(
    open ? caseItem.case_id : null
  );
  const { validate } = useValidateDocCategory();
  const { upload } = useUploadIngest();

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!isDropdownOpen) return;
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [isDropdownOpen]);

  // Reset state when dialog opens
  useEffect(() => {
    if (open) {
      setSelectedCategory("");
      setFile(null);
      setStep("select");
      setValidationResult(null);
    }
  }, [open]);

  const categoryMap = new Map<string, CaseDocCategoryItem>();
  caseDocCategories?.categories.forEach((c) => categoryMap.set(c.code, c));

  const selectedCategoryData = categories.find((c) => c.code === selectedCategory);
  const selectedCaseCategory = selectedCategory ? categoryMap.get(selectedCategory) : null;

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setFile(f);
  }, []);

  const handleValidate = async () => {
    if (!selectedCategory || !file) return;
    setStep("validate");
    try {
      const result = await validate({
        case_id: caseItem.case_id,
        doc_category: selectedCategory,
        filename: file.name,
      });
      setValidationResult(result);
      if (result.ok && !result.suspected_mismatch && !result.suspected_duplicate) {
        // No warnings, proceed directly to upload
        await handleUpload(result);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "校验失败");
      setStep("select");
    }
  };

  const handleUpload = async (validation?: { ok: boolean; suspected_mismatch: boolean; suspected_duplicate: boolean; message: string }) => {
    if (!file || !selectedCategory) return;
    setStep("uploading");
    try {
      const result = await upload({
        files: file,
        case_id: caseItem.case_id,
        doc_category: selectedCategory,
      });
      if (result.error) {
        throw new Error(result.error);
      }
      toast.success("上传成功");
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "上传失败");
      setStep("select");
    }
  };

  const isLoading = categoriesLoading || caseDocCategoriesLoading;
  const canSubmit = selectedCategory && file && step === "select";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="text-base">上传卷宗</DialogTitle>
          <p className="text-xs text-muted-foreground">
            案件 <span className="font-mono">#{caseItem.case_id}</span>{" "}
            <span className="truncate">{caseItem.case_name}</span>
          </p>
        </DialogHeader>

        {/* Coverage Grid */}
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">卷宗覆盖情况</p>
          {isLoading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="size-4 animate-spin text-muted-foreground/30" />
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-2">
              {categories.map((cat) => {
                const caseCat = categoryMap.get(cat.code);
                const uploaded = caseCat?.uploaded ?? false;
                return (
                  <div
                    key={cat.code}
                    title={`${cat.name}\n文件数: ${caseCat?.file_count ?? 0}\n记录数: ${caseCat?.record_count ?? 0}`}
                    className={cn(
                      "flex flex-col items-center gap-1 rounded-lg border px-2 py-2 text-center",
                      uploaded
                        ? "border-emerald-200 bg-emerald-50"
                        : "border-border/40 bg-muted/30"
                    )}
                  >
                    {uploaded ? (
                      <CheckCircle2 className="size-4 text-emerald-500" />
                    ) : (
                      <div className="size-4 rounded-full border-2 border-muted-foreground/20" />
                    )}
                    <span className={cn("text-[10px] leading-tight", uploaded ? "text-emerald-700" : "text-muted-foreground/60")}>
                      {cat.name}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Category Select */}
        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground">卷宗类别</label>
          <div ref={dropdownRef} className="relative">
            <button
              type="button"
              onClick={() => setIsDropdownOpen((v) => !v)}
              disabled={categoriesLoading}
              className={cn(
                "flex w-full items-center justify-between rounded-md border border-border/50 bg-background px-3 py-2 text-sm outline-none transition-colors",
                "hover:border-border focus:border-border",
                categoriesLoading && "opacity-50 cursor-not-allowed"
              )}
            >
              <span className={selectedCategoryData ? "text-foreground" : "text-muted-foreground/50"}>
                {selectedCategoryData?.name ?? "选择卷宗类别"}
              </span>
              <ChevronDown className="size-4 text-muted-foreground/50" />
            </button>
            {isDropdownOpen && (
              <div className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-md border border-border/60 bg-popover py-1 shadow-lg">
                {categories.map((cat) => {
                  const caseCat = categoryMap.get(cat.code);
                  const uploaded = caseCat?.uploaded ?? false;
                  return (
                    <button
                      key={cat.code}
                      type="button"
                      onClick={() => {
                        setSelectedCategory(cat.code);
                        setIsDropdownOpen(false);
                      }}
                      className={cn(
                        "flex w-full items-center justify-between px-3 py-2 text-sm hover:bg-accent",
                        selectedCategory === cat.code && "bg-accent"
                      )}
                    >
                      <span>{cat.name}</span>
                      {uploaded && (
                        <CheckCircle2 className="size-3.5 text-emerald-500" />
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* File Upload */}
        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground">文件</label>
          {file ? (
            <div className="flex items-center gap-2.5 rounded-md bg-muted/40 px-3 py-2 text-xs">
              <FileText className="size-3.5 shrink-0 text-muted-foreground/50" />
              <span className="min-w-0 flex-1 truncate text-foreground/80">{file.name}</span>
              <button
                type="button"
                onClick={() => setFile(null)}
                className="shrink-0 text-muted-foreground/30 hover:text-muted-foreground/70"
              >
                <X className="size-3" />
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
              <p className="text-xs text-muted-foreground/60">点击选择文件</p>
              <input
                ref={inputRef}
                type="file"
                className="hidden"
                onChange={handleFileSelect}
              />
            </div>
          )}
        </div>

        {/* Validation Alert */}
        {validationResult && (
          <Alert
            variant={
              validationResult.suspected_duplicate
                ? "destructive"
                : validationResult.suspected_mismatch
                  ? "default"
                  : "default"
            }
            className={cn(
              validationResult.suspected_mismatch && !validationResult.suspected_duplicate && "border-amber-200 bg-amber-50 text-amber-900"
            )}
          >
            <AlertTriangle className="size-4" />
            <AlertDescription className="text-xs">
              {validationResult.message}
            </AlertDescription>
          </Alert>
        )}

        <DialogFooter>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={step === "uploading"}
          >
            取消
          </Button>
          {validationResult && !validationResult.ok ? (
            <Button
              size="sm"
              onClick={() => handleUpload(validationResult!)}
              disabled={step === "uploading"}
            >
              {step === "uploading" && <Loader2 className="mr-1 size-3 animate-spin" />}
              仍要上传
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={handleValidate}
              disabled={!canSubmit || step !== "select"}
            >
              {step === "validate" && <Loader2 className="mr-1 size-3 animate-spin" />}
              {step === "uploading" && <Loader2 className="mr-1 size-3 animate-spin" />}
              确认上传
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/cases/add-material-dialog.tsx
git commit -m "feat: rewrite AddMaterialDialog for doc category upload"
```

---

## Task 9: 验证与清理

**Files:**
- 所有新增/修改文件

- [ ] **Step 1: TypeScript 类型检查**

```bash
npx tsc --noEmit
```

- [ ] **Step 2: 运行单元测试**

```bash
pnpm test
```

- [ ] **Step 3: 构建检查**

```bash
pnpm build
```

- [ ] **Step 4: 最终 Commit（如有修复）**

```bash
git add -A
git commit -m "fix: type errors and build issues"
```

---

## Spec 覆盖检查

| Spec 需求 | 对应 Task |
|---|---|
| 环境变量 `LANGGRAPH_API_BASE_URL` | Task 1 |
| 类型定义（字典、覆盖、校验、上传） | Task 2 |
| API Route 代理四接口 | Task 3-6 |
| SWR hooks | Task 7 |
| 13类覆盖网格 | Task 8 |
| 下拉框选择类别 | Task 8 |
| 文件选择 | Task 8 |
| 校验 Alert 横幅 | Task 8 |
| 上传成功关闭/失败保持 | Task 8 |
| `files` 字段名透传 | Task 6 |

---

## Task 10: Alert 组件（如不存在）

**Files:**
- Create: `components/ui/alert.tsx`（如不存在）

- [ ] **Step 1: 检查 Alert 组件是否存在**

```bash
ls components/ui/alert.tsx
```

- [ ] **Step 2: 如不存在，创建标准 shadcn/ui Alert**

```tsx
import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const alertVariants = cva(
  "relative w-full rounded-lg border px-4 py-3 text-sm [&>svg+div]:translate-y-[-3px] [&>svg]:absolute [&>svg]:left-4 [&>svg]:top-4 [&>svg]:text-foreground [&>svg~*]:pl-7",
  {
    variants: {
      variant: {
        default: "bg-background text-foreground",
        destructive:
          "border-destructive/50 text-destructive dark:border-destructive [&>svg]:text-destructive",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

const Alert = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>
>(({ className, variant, ...props }, ref) => (
  <div
    ref={ref}
    role="alert"
    className={cn(alertVariants({ variant }), className)}
    {...props}
  />
))
Alert.displayName = "Alert"

const AlertDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("text-sm [&_p]:leading-relaxed", className)}
    {...props}
  />
))
AlertDescription.displayName = "AlertDescription"

export { Alert, AlertDescription }
```

- [ ] **Step 3: Commit（如创建）**

```bash
git add components/ui/alert.tsx
git commit -m "feat: add alert ui component"
```

---

## 已知限制

1. 上传接口仅支持单文件（与现有 `AddMaterialDialog` 行为一致）
2. 校验接口的 `preview_text` 未实现文件内容提取

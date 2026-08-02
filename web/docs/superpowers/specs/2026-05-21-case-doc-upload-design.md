# 案件列表卷宗上传功能设计

**日期**: 2026-05-21
**状态**: 待实现

---

## 1. 背景与目标

替换案件列表页现有的"添加材料"功能，接入后端卷宗上传体系。用户可在案件列表中直接上传卷宗文件，系统会：
1. 展示 13 类标准卷宗的覆盖情况
2. 上传前进行类别校验并给出提示
3. 最终上传文件到 LangGraph 进行 OCR、结构化入库

---

## 2. 外部接口清单

### 2.1 获取标准卷宗类别字典
- **上游**: `GET {CASES_API_BASE_URL}/api/ingest/doc-categories`
- **本地代理**: `GET /api/doc-categories`
- **说明**: 返回 13 类卷宗的标准字典，含 code、name、order、fields

### 2.2 查询案件卷宗覆盖情况
- **上游**: `GET {CASES_API_BASE_URL}/api/case/{case_id}/doc-categories`
- **本地代理**: `GET /api/cases/{caseId}/doc-categories`
- **说明**: 按案件返回每类卷宗是否已覆盖（file_count + record_count）

### 2.3 上传前校验卷宗类别
- **上游**: `POST {CASES_API_BASE_URL}/api/ingest/validate-doc-category`
- **本地代理**: `POST /api/ingest/validate-doc-category`
- **说明**: 轻量校验，不写入数据库，返回校验提示

### 2.4 上传文件并触发摄入
- **上游**: `POST {LANGGRAPH_API_BASE_URL}/files/upload-and-ingest`
- **本地代理**: `POST /api/ingest/upload`
- **说明**: multipart 文件上传，进入 LangGraph ingest 子图

---

## 3. 环境变量

```bash
# 已存在
CASES_API_BASE_URL=http://10.0.10.2:8080

# 新增
LANGGRAPH_API_BASE_URL=http://10.0.10.2:8081
```

---

## 4. 架构设计

### 4.1 API Route 代理层

所有外部调用均通过 Next.js API Route 代理，符合项目统一网关架构：

```
Browser
  └── fetch /api/*  (JSON / multipart)
        └── Next.js API Routes
              ├── /api/doc-categories  → Cases API (8080)
              ├── /api/cases/[id]/doc-categories  → Cases API (8080)
              ├── /api/ingest/validate-doc-category  → Cases API (8080)
              └── /api/ingest/upload  → LangGraph API (8081)
```

### 4.2 新增文件清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `app/api/doc-categories/route.ts` | API Route | 代理字典接口 |
| `app/api/cases/[caseId]/doc-categories/route.ts` | API Route | 代理覆盖情况接口 |
| `app/api/ingest/validate-doc-category/route.ts` | API Route | 代理校验接口 |
| `app/api/ingest/upload/route.ts` | API Route | 代理上传接口（multipart） |
| `lib/types/doc-categories.ts` | 类型定义 | 卷宗相关类型 |
| `lib/hooks/use-doc-categories.ts` | Hook | 获取字典（SWR 全局缓存） |
| `lib/hooks/use-case-doc-categories.ts` | Hook | 获取案件覆盖情况 |
| `lib/hooks/use-validate-doc-category.ts` | Hook | 校验 mutation |
| `lib/hooks/use-upload-ingest.ts` | Hook | 上传 mutation |
| `components/cases/add-material-dialog.tsx` | 组件 | **重写** 卷宗上传对话框 |

---

## 5. 数据类型

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

---

## 6. 前端交互设计

### 6.1 对话框布局

```
┌─────────────────────────────────────────────┐
│  上传卷宗  —  案件 #123 某某案                 │
├─────────────────────────────────────────────┤
│  【13类卷宗覆盖情况网格】                      │
│  ┌──────┐ ┌──────┐ ┌──────┐ ...             │
│  │  ✓   │ │  ✓   │ │      │                 │
│  │身份证明│ │合同文件│ │执行文书│              │
│  └──────┘ └──────┘ └──────┘                 │
├─────────────────────────────────────────────┤
│  卷宗类别： [下拉框 ▼]                        │
│  文件：     [拖拽区域 / 点击选择]              │
├─────────────────────────────────────────────┤
│  [Alert 横幅：校验提示（warning 级别）]        │
├─────────────────────────────────────────────┤
│  [取消]              [确认上传]               │
└─────────────────────────────────────────────┘
```

### 6.2 覆盖情况网格

- 13 个类别按 `sort_order` 排序，网格布局（每行 4-5 个）
- **已覆盖** (`uploaded: true`): 绿色背景 + 勾选图标 + 类别名
- **未覆盖** (`uploaded: false`): 灰色背景 + 空状态 + 类别名
- 鼠标悬停显示 `file_count` / `record_count` / `last_uploaded_at` 详情
- 下拉框选项也同步显示覆盖状态 badge

### 6.3 状态流转

```
打开对话框
  │
  ├── 并行加载：GET /api/doc-categories + GET /api/cases/{id}/doc-categories
  │     └── 展示网格 + 填充下拉框
  │
  ├── 用户选择类别 + 选择文件
  │
  ├── 点击"确认上传"
  │     └── 调用 POST /api/ingest/validate-doc-category
  │           ├── 有 warnings → Alert 横幅展示，用户可再次点击确认
  │           └── 无 warnings → 直接进入上传
  │
  └── 调用 POST /api/ingest/upload
        ├── 成功 → 关闭对话框，toast.success("上传成功")
        └── 失败 → 保持对话框，toast.error("上传失败：xxx")
```

### 6.4 校验提示规则

- 校验接口返回 `ok` / `suspected_mismatch` / `suspected_duplicate` / `message`
- 用 Alert 横幅展示 `message`
- `suspected_mismatch` 为 true 时：Alert 变黄色，提示"疑似选错类别"
- `suspected_duplicate` 为 true 时：Alert 变橙色，提示"存在重复上传风险"
- 用户看到提示后**仍可**点击"确认上传"继续

---

## 7. API Route 详细设计

### 7.1 GET /api/doc-categories

- 鉴权：`requireSession()`
- 代理到：`{CASES_API_BASE_URL}/api/ingest/doc-categories`
- 错误处理：503（未配置/不可达）、502（非 JSON）
- 响应：直接透传上游 JSON

### 7.2 GET /api/cases/[caseId]/doc-categories

- 鉴权：`requireSession()`
- 参数：`caseId`（path param，integer）
- 代理到：`{CASES_API_BASE_URL}/api/case/{case_id}/doc-categories`
- 错误处理：同上 + 422（参数校验）

### 7.3 POST /api/ingest/validate-doc-category

- 鉴权：`requireSession()`
- Body：JSON，`{ case_id, doc_category, filename, preview_text? }`
- 代理到：`{CASES_API_BASE_URL}/api/ingest/validate-doc-category`
- 错误处理：同上

### 7.4 POST /api/ingest/upload

- 鉴权：`requireSession()`
- Body：`multipart/form-data`，字段：
  - `files`: File（注意：上游字段名为 `files` 而非 `file`）
  - `case_id`: string (案件ID)
  - `doc_category`: string (卷宗类别 code)
- 代理到：`{LANGGRAPH_API_BASE_URL}/files/upload-and-ingest`
- 注意：需要将前端 multipart 透传给上游，保持 `Content-Type: multipart/form-data`
- 响应字段说明：
  - `upload_batch_summary.status`: processing / completed / failed
  - `upload_batch_summary.stage`: parse_fallback / parse_document / completed
  - `has_conclusion_changes`: 是否引发已落库结论变化
  - `change_summary`: 变化摘要（中文）
  - `new_files`: 本次新上传的文件名列表
  - `duplicate_files`: 重复文件列表
  - `error`: 错误信息（如有）
- 错误处理：同上

---

## 8. 错误处理

### 8.1 全局错误

| 场景 | 行为 |
|---|---|
| 环境变量未配置 | API Route 返回 503 |
| 上游不可达 | API Route 返回 503 |
| 上游返回非 JSON | API Route 返回 502 |
| 未登录 | 401，前端跳转登录 |

### 8.2 前端错误

| 场景 | 行为 |
|---|---|
| 字典加载失败 | 下拉框 disabled，显示"加载失败"提示 |
| 覆盖情况加载失败 | 网格显示"加载失败"，不影响其他功能 |
| 校验失败 | Alert 横幅显示错误信息 |
| 上传失败 | toast.error，对话框保持打开 |

---

## 9. 边界情况

1. **文件类型限制**: 上游支持 `txt/csv/md/pdf/doc/docx/xls/xlsx/xlsm` + 图片。前端不做限制，由上游返回错误。
2. **大文件**: 由上游控制大小限制，前端显示上传进度（浏览器原生）。
3. **并发上传**: 一次只允许选择一个文件，简化流程。
4. **preview_text**: 前端不主动提取文件内容，只传文件名。如需文本预览，后续可扩展。
5. **files 字段名**: LangGraph 上传接口的 multipart 字段名为 `files`（不是 `file`），代理时必须保持此字段名。
5. **case_id 类型**: `Case` 接口中 `case_id` 为 `number`，所有接口均使用 `number` 类型传递。

---

## 10. 后续扩展

- 支持批量上传（多文件）
- 上传进度条
- 上传历史记录
- 卷宗预览/下载

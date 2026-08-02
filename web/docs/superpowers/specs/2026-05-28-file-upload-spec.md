# 案件文件上传设计 Spec

**日期**: 2026-05-28
**状态**: 待实现
**基于真实接口测试数据**

---

## 1. 背景与目标

在案件详情页或案件列表提供完整的卷宗材料上传能力。上传是**异步流程**：先接收文件并返回批次 ID，后端在后台完成解析、分块、入库；前端通过轮询批次详情追踪处理状态。

**核心约束**:
- 文件必须关联到具体案件 (`case_id`)
- 上传时必须指定卷宗类别 (`doc_category`)，后端据此做校验和覆盖分析
- 上传后立即返回 202，不等待处理完成

---

## 2. 外部接口清单（已测试）

### 2.1 获取标准卷宗类别字典 ✅

- **接口**: `GET /api/ingest/doc-categories`
- **作用**: 获取系统支持的 13 类标准卷宗类别列表，用于上传表单的下拉选择
- **返回**（实测）:

```json
{
  "categories": [
    { "code": "basic_info",         "name": "基本信息" },
    { "code": "loan_contract",      "name": "贷款合同" },
    { "code": "guarantee_contract", "name": "担保合同" },
    { "code": "judgment",           "name": "判决书" },
    { "code": "financial_statement", "name": "财务报表" },
    { "code": "real_estate_cert",   "name": "不动产权证" },
    { "code": "mining_license",     "name": "采矿许可证" },
    { "code": "bank_statement",     "name": "银行流水" },
    { "code": "credit_report",      "name": "征信报告" },
    { "code": "asset_appraisal",    "name": "资产评估" },
    { "code": "executive_doc",      "name": "执行文书" },
    { "code": "other_contract",     "name": "其他合同" },
    { "code": "other_material",     "name": "其他材料" }
  ]
}
```

**使用时机**: 上传对话框打开时预加载，本地缓存，减少重复请求。

---

### 2.2 查询案件 13 类卷宗覆盖情况 ✅

- **接口**: `GET /api/case/{case_id}/doc-categories`
- **作用**: 查询该案件已有的卷宗类别覆盖情况，帮助用户判断缺少哪些类别
- **返回**（实测）:

```json
{
  "case_id": 1,
  "categories": [
    { "code": "loan_contract", "name": "贷款合同", "file_count": 2 },
    { "code": "judgment",      "name": "判决书",   "file_count": 1 }
  ],
  "missing_categories": [
    { "code": "guarantee_contract", "name": "担保合同" },
    { "code": "bank_statement",     "name": "银行流水" }
  ]
}
```

**使用时机**: 上传对话框打开时加载，展示"已覆盖 / 未覆盖"标签，引导用户补件。

---

### 2.3 上传前校验卷宗类别 ✅

- **接口**: `POST /api/ingest/validate-doc-category`
- **Content-Type**: `application/json`
- **作用**: 在上传前校验所选卷宗类别是否合法、是否与案件已有类别冲突（重复 / 疑似错配）
- **请求体**:

```json
{
  "case_id": 1,
  "doc_category": "loan_contract",
  "file_names": ["合同1.pdf", "合同2.pdf"]
}
```

- **返回**（实测）:

```json
{
  "ok": true,
  "suspected_mismatch": false,
  "suspected_duplicate": false,
  "duplicate_files": [],
  "suspected_mismatch_files": [],
  "message": "校验通过"
}
```

**异常返回示例**（重复文件）:

```json
{
  "ok": false,
  "suspected_mismatch": false,
  "suspected_duplicate": true,
  "duplicate_files": ["合同1.pdf"],
  "suspected_mismatch_files": [],
  "message": "检测到重复文件：合同1.pdf"
}
```

**使用时机**: 用户选择文件后、点击"确认上传"前调用。若返回警告，弹窗提示用户确认是否继续。

---

### 2.4 上传文件并异步触发摄入 ✅（核心接口）

- **接口**: `POST /files/upload-and-ingest`
- **Content-Type**: `multipart/form-data`
- **作用**: 实际上传文件，触发后端异步解析入库流程

**请求参数**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `case_id` | integer | 是 | 案件 ID |
| `files` | File[] | 是 | 文件数组，支持多文件同时上传 |
| `doc_category` | string | 是 | 卷宗类别代码（如 `loan_contract`） |
| `batch_name` | string | 否 | 批次名称，用户可自定义，默认空 |
| `operator_id` | string | 否 | 操作人 ID |
| `operator_name` | string | 否 | 操作人姓名 |

**返回 202**（实测）:

```json
{
  "accepted": true,
  "upload_batch_id": "local-2e27c6517eb5",
  "material_event_id": "material-event:local-2e27c6517eb5",
  "status": "processing",
  "stage": "stored",
  "upload_batch_detail_path": "/files/upload-batches/local-2e27c6517eb5",
  "material_event_detail_path": "/files/material-events/material-event:local-2e27c6517eb5",
  "case_upload_batches_path": "/files/cases/1/upload-batches",
  "doc_category": "basic_info",
  "batch_name": "",
  "operator_id": "",
  "operator_name": "",
  "uploaded_file_count": 1,
  "upload_batch_summary": {
    "material_event_id": "material-event:local-2e27c6517eb5",
    "material_event_type": "supplement_upload",
    "material_event_status": "processing",
    "upload_batch_id": "local-2e27c6517eb5",
    "batch_name": "",
    "doc_category": "basic_info",
    "operator_id": "",
    "operator_name": "",
    "file_count": 1,
    "new_file_count": 1,
    "duplicate_file_count": 0,
    "suspected_mismatch_file_count": 0,
    "status": "processing",
    "stage": "stored",
    "has_conclusion_changes": false,
    "reconciliation_item_count": 0,
    "add_item_count": 0,
    "override_item_count": 0,
    "change_summary": ""
  },
  "doc_category_validation": {
    "ok": false,
    "suspected_mismatch": false,
    "suspected_duplicate": false,
    "duplicate_files": [],
    "suspected_mismatch_files": [],
    "message": "doc_category 预校验暂不可用..."
  },
  "case_doc_category_status": {
    "case_id": 1,
    "categories": [],
    "missing_categories": []
  },
  "duplicate_files": [],
  "suspected_mismatch_files": [],
  "new_files": ["README.md"]
}
```

**关键字段说明**:

| 字段 | 说明 |
|------|------|
| `upload_batch_id` | 上传批次唯一 ID，后续轮询状态的凭据 |
| `material_event_id` | 材料事件 ID，关联到材料事件详情 |
| `status` | 批次状态：`processing` / `completed` / `failed` |
| `stage` | 处理阶段：`stored`（已接收）→ `processing`（解析中）→ `completed`（完成） |
| `upload_batch_detail_path` | 批次详情接口路径（可直接拼接 base URL 调用） |
| `new_files` | 实际被接受的新文件列表 |
| `duplicate_files` | 被判定为重复的文件列表 |
| `suspected_mismatch_files` | 疑似类别错配的文件列表 |

> **注意**: `doc_category_validation` 字段当前后端暂不可用（message 提示），上传前校验应使用 §2.3 的独立接口 `/api/ingest/validate-doc-category`。

---

### 2.5 查询上传批次详情 ✅（核心接口）

- **接口**: `GET /files/upload-batches/{upload_batch_id}`
- **作用**: 查询某个具体批次的处理详情，包括每個文件的状态、解析结果、持久化校验

**返回**（实测）:

```json
{
  "upload_batch_id": "local-9cf5337641f3",
  "case_id": 123,
  "debtor_id": 12,
  "batch_name": "",
  "doc_category": "loan_contract",
  "operator_id": "",
  "operator_name": "",
  "status": "completed",
  "file_count": 1,
  "new_file_count": 1,
  "duplicate_file_count": 0,
  "suspected_mismatch_file_count": 0,
  "records_inserted": 0,
  "metadata": {
    "stage": "completed",
    "new_files": ["test_faker_503.sh"],
    "parse_summary": "补充材料已入库。",
    "add_item_count": 0,
    "change_summary": "本次补件未引发已落库结论变化。",
    "chunk_batch_ref": "kg_chunk_batch:...",
    "duplicate_files": [],
    "material_event_id": "material-event:local-9cf5337641f3",
    "ingest_payload_ref": "ingest_payload:...",
    "aggregated_text_ref": "aggregated_text:...",
    "material_event_type": "supplement_upload",
    "override_item_count": 0,
    "material_event_status": "completed",
    "has_conclusion_changes": false,
    "suspected_mismatch_files": [],
    "parse_document_result_ref": "parse_document_result:...",
    "reconciliation_item_count": 0
  },
  "has_conclusion_changes": false,
  "reconciliation_item_count": 0,
  "add_item_count": 0,
  "override_item_count": 0,
  "change_summary": "本次补件未引发已落库结论变化。",
  "created_at": "2026-05-22T07:21:42.026365+00:00",
  "updated_at": "2026-05-22T07:21:45.780415+00:00",
  "files": [
    {
      "upload_batch_link_id": 6,
      "file_id": 37,
      "file_name": "test_faker_503.sh",
      "file_sha256": "985d92ed2c0924575e7c4ff8b6a3708a85446c54b7672fca5119bc56d16d3286",
      "duplicate_of": "",
      "file_type": "document",
      "content_type": "application/x-sh",
      "storage_provider": "",
      "storage_bucket": "",
      "storage_key": "",
      "storage_ref": "",
      "created_at": "2026-05-22T07:21:45.440129+00:00",
      "page_count": 0,
      "chunk_count": 0,
      "doc_categories": ["loan_contract"]
    }
  ],
  "persistence_checks": {
    "source_upload_batch_exists": true,
    "source_file_upload_batch_count": 1,
    "source_file_count_matches": true,
    "source_page_file_count": 0,
    "source_chunk_file_count": 0,
    "source_file_doc_category_count": 1,
    "all_files_have_chunks": false,
    "all_files_have_doc_category": true
  }
}
```

**关键字段说明**:

| 字段 | 说明 |
|------|------|
| `status` | `processing` / `completed` / `failed` |
| `stage` | `stored` / `processing` / `completed` |
| `files` | 文件列表，含 `file_id`、`file_name`、`content_type`、`page_count`、`chunk_count` 等 |
| `persistence_checks` | 持久化一致性校验，若 `all_files_have_chunks=false` 说明分块未完成 |
| `has_conclusion_changes` | 是否引发结论变更 |
| `change_summary` | 变更摘要文案 |

---

### 2.6 查询案件上传批次列表 ✅（核心接口）

- **接口**: `GET /files/cases/{case_id}/upload-batches`
- **作用**: 查询某案件的全部上传批次，用于案件详情页展示上传历史

**返回**（实测）:

```json
{
  "case_id": 1,
  "upload_batches": [
    {
      "upload_batch_id": "local-9cf5337641f3",
      "batch_name": "2025年合同批次",
      "doc_category": "loan_contract",
      "status": "completed",
      "file_count": 3,
      "new_file_count": 3,
      "duplicate_file_count": 0,
      "created_at": "2026-05-22T07:21:42.026365+00:00",
      "updated_at": "2026-05-22T07:21:45.780415+00:00"
    }
  ]
}
```

> 当前测试案件返回空数组 `[]`，结构以上述为准。

---

## 3. 上传完整流程设计

### 3.1 状态机

```
┌─────────────┐     打开对话框      ┌─────────────┐
│   初始态    │ ──────────────────→ │  选择文件   │
│  (idle)     │                     │ (selecting) │
└─────────────┘                     └──────┬──────┘
                                           │
          ┌────────────────────────────────┘
          │ 选择完成
          ▼
┌─────────────────┐    点击上传     ┌─────────────────┐
│   校验中        │ ──────────────→ │   上传中        │
│ (validating)    │                 │  (uploading)    │
│ 调用 validate   │                 │  multipart 上传 │
│ 接口预检        │                 │  返回 202       │
└─────────────────┘                 └────────┬────────┘
          │                                  │
          │ 校验警告                         │ 返回 batch_id
          ▼                                  ▼
┌─────────────────┐                 ┌─────────────────┐
│   确认覆盖      │                 │   处理中        │
│ (confirming)    │                 │ (processing)    │
│ 用户确认重复/   │                 │ 轮询批次详情    │
│ 错配后继续      │                 │ status/stage    │
└─────────────────┘                 └────────┬────────┘
          │                                  │
          └──────────────────────────────────┘
          │ 轮询到 completed / failed
          ▼
┌─────────────────┐                 ┌─────────────────┐
│   完成          │                 │   失败          │
│ (completed)     │                 │   (failed)      │
│ 展示结果摘要    │                 │ 展示错误信息    │
│ 刷新案件覆盖    │                 │ 提供重试入口    │
└─────────────────┘                 └─────────────────┘
```

### 3.2 时序图

```
用户          前端              后端（Next.js API Route）          LangGraph
 │             │                        │                             │
 │──打开上传──→│                        │                             │
 │             │──GET /api/ingest/doc-categories─────────────────────→│
 │             │←──返回 13 类字典──────────────────────────────────────│
 │             │                        │                             │
 │             │──GET /api/case/{id}/doc-categories──────────────────→│
 │             │←──返回已覆盖/缺失类别──────────────────────────────────│
 │             │                        │                             │
 │──选文件────→│                        │                             │
 │──选类别────→│                        │                             │
 │──点上传────→│                        │                             │
 │             │──POST /api/ingest/validate-doc-category─────────────→│
 │             │←──返回校验结果────────────────────────────────────────│
 │             │                        │                             │
 │◄─警告弹窗───│（若有重复/错配）        │                             │
 │──确认继续──→│                        │                             │
 │             │──POST /files/upload-and-ingest (multipart)──────────→│
 │             │←──返回 202 + batch_id + status="processing"──────────│
 │             │                        │                             │
 │◄─显示进度───│                        │                             │
 │             │──GET /files/upload-batches/{id} 轮询（每 3s）───────→│
 │             │←──返回 stage/status ──────────────────────────────────│
 │             │                        │                             │
 │             │  （循环直到 completed / failed / 超时 5min）          │
 │             │                        │                             │
 │◄─完成通知───│                        │                             │
 │             │──GET /files/cases/{id}/upload-batches（刷新列表）───→│
 │             │←──返回最新批次列表────────────────────────────────────│
 │             │                        │                             │
 │◄─展示结果───│（成功/失败文件列表、结论变更提示）                    │
```

### 3.3 轮询策略

| 阶段 | 轮询间隔 | 最大时长 | 行为 |
|------|----------|----------|------|
| `stored` → `processing` | 3s | 5min | 正常轮询 |
| `completed` | - | - | 停止轮询，展示结果 |
| `failed` | - | - | 停止轮询，展示错误 |
| 超时 | - | 5min | 停止轮询，提示"处理超时，请稍后刷新查看" |

---

## 4. 前端交互设计

### 4.1 上传对话框

```
┌─────────────────────────────────────────────┐
│  📁 上传卷宗材料                    [×]      │
├─────────────────────────────────────────────┤
│                                              │
│  案件：#123 某某债务纠纷案                    │
│                                              │
│  ┌─────────────────────────────────────┐    │
│  │ 卷宗类别 *                           │    │
│  │  [请选择 ▼]                         │    │
│  │   ├── 贷款合同 (已覆盖 2 份)         │    │
│  │   ├── 担保合同 ⚠️ 缺失               │    │
│  │   ├── 判决书 (已覆盖 1 份)           │    │
│  │   └── ...                           │    │
│  └─────────────────────────────────────┘    │
│                                              │
│  ┌─────────────────────────────────────┐    │
│  │ 批次名称                             │    │
│  │  [可选，如：2025年合同批次]          │    │
│  └─────────────────────────────────────┘    │
│                                              │
│  ┌─────────────────────────────────────┐    │
│  │ 📎 点击或拖拽文件到此处上传          │    │
│  │                                     │    │
│  │ 支持：PDF / Word / Excel / 图片     │    │
│  │ 单个文件 ≤ 50MB                     │    │
│  └─────────────────────────────────────┘    │
│                                              │
│  已选文件 (3):                               │
│  ├── 合同1.pdf          2.3MB    [删除]     │
│  ├── 合同2.pdf          1.8MB    [删除]     │
│  └── 财务报表.xlsx      5.1MB    [删除]     │
│                                              │
│  [──────────── 取消 ──── 确认上传 ─────────] │
│                                              │
└─────────────────────────────────────────────┘
```

### 4.2 上传中状态

```
┌─────────────────────────────────────────────┐
│  📁 上传卷宗材料                    [×]      │
├─────────────────────────────────────────────┤
│                                              │
│  正在处理上传批次 local-2e27c6517eb5...      │
│                                              │
│  ┌─────────────────────────────────────┐    │
│  │ ████████░░░░░░░░░░░░  存储中...     │    │
│  │                                     │    │
│  │  3 个文件已接收                     │    │
│  │  正在解析 / 分块 / 入库...          │    │
│  └─────────────────────────────────────┘    │
│                                              │
│  [──────────────── 后台运行 ────────────────] │
│                                              │
└─────────────────────────────────────────────┘
```

### 4.3 完成状态

```
┌─────────────────────────────────────────────┐
│  📁 上传结果                        [×]      │
├─────────────────────────────────────────────┤
│                                              │
│  ✅ 上传完成                                 │
│                                              │
│  批次 ID: local-2e27c6517eb5                 │
│  类别: 贷款合同                              │
│  时间: 2026-05-28 14:32                      │
│                                              │
│  ┌── 文件处理结果 ─────────────────────┐    │
│  │ ✅ 合同1.pdf      已入库            │    │
│  │ ✅ 合同2.pdf      已入库            │    │
│  │ ⚠️ 财务报表.xlsx  疑似类别错配      │    │
│  └─────────────────────────────────────┘    │
│                                              │
│  📌 结论变更: 无                             │
│                                              │
│  [────────────────── 确定 ──────────────────]│
│                                              │
└─────────────────────────────────────────────┘
```

### 4.4 案件详情页 — 上传历史列表

在案件详情页（或材料Tab）展示该案件的所有上传批次：

```
材料上传历史
─────────────────────────────────────────────
批次名称              类别        文件数   状态    时间
─────────────────────────────────────────────
2025年合同批次        贷款合同     3       ✅ 完成  5分钟前
初始材料              基本信息     5       ✅ 完成  2小时前
担保材料              担保合同     2       🔄 处理中 1分钟前
─────────────────────────────────────────────
```

点击某一行可展开查看该批次的文件详情（调用 §2.5 查询批次详情）。

---

## 5. 数据模型

### 5.1 前端状态

```typescript
interface UploadDialogState {
  // 选择阶段
  caseId: number;
  selectedCategory: string | null;
  batchName: string;
  files: File[];

  // 校验阶段
  validationResult: ValidationResult | null;
  isValidating: boolean;

  // 上传阶段
  uploadBatchId: string | null;
  materialEventId: string | null;
  status: "idle" | "uploading" | "processing" | "completed" | "failed";
  stage: "stored" | "processing" | "completed" | null;
  progress: {
    totalFiles: number;
    processedFiles: number;
    currentStage: string;
  };

  // 结果
  result: UploadBatchDetail | null;
  error: string | null;
}

interface ValidationResult {
  ok: boolean;
  suspectedMismatch: boolean;
  suspectedDuplicate: boolean;
  duplicateFiles: string[];
  suspectedMismatchFiles: string[];
  message: string;
}

interface DocCategory {
  code: string;
  name: string;
}

interface CaseDocCategoryStatus {
  caseId: number;
  categories: Array<{ code: string; name: string; fileCount: number }>;
  missingCategories: Array<{ code: string; name: string }>;
}

interface UploadBatchSummary {
  uploadBatchId: string;
  batchName: string;
  docCategory: string;
  status: "processing" | "completed" | "failed";
  fileCount: number;
  newFileCount: number;
  duplicateFileCount: number;
  createdAt: string;
  updatedAt: string;
}

interface UploadBatchDetail {
  uploadBatchId: string;
  caseId: number;
  batchName: string;
  docCategory: string;
  status: string;
  stage: string;
  fileCount: number;
  newFileCount: number;
  duplicateFileCount: number;
  suspectedMismatchFileCount: number;
  hasConclusionChanges: boolean;
  changeSummary: string;
  createdAt: string;
  updatedAt: string;
  files: Array<{
    fileId: number;
    fileName: string;
    fileType: string;
    contentType: string;
    pageCount: number;
    chunkCount: number;
    docCategories: string[];
    duplicateOf: string;
  }>;
  persistenceChecks: {
    sourceUploadBatchExists: boolean;
    sourceFileCountMatches: boolean;
    allFilesHaveChunks: boolean;
    allFilesHaveDocCategory: boolean;
  };
}
```

---

## 6. API Route 代理设计

前端不直接调用 LangGraph，全部通过 Next.js API Route 代理。

### 6.1 已存在的代理（可直接复用/对齐）

`app/api/ingest/upload/route.ts` 已代理 `POST /files/upload-and-ingest`，使用 `LANGGRAPH_API_BASE_URL` 环境变量。

### 6.2 建议新增的代理接口

| 前端调用 | 代理 Route | 转发目标 |
|----------|-----------|----------|
| `GET /api/ingest/doc-categories` | 已存在 | LangGraph `/api/ingest/doc-categories` |
| `GET /api/case/{id}/doc-categories` | 已存在 | LangGraph `/api/case/{id}/doc-categories` |
| `POST /api/ingest/validate-doc-category` | 已存在 | LangGraph `/api/ingest/validate-doc-category` |
| `POST /api/files/upload-and-ingest` | `app/api/ingest/upload/route.ts` | LangGraph `/files/upload-and-ingest` |
| `GET /api/files/upload-batches/{id}` | 新增 | LangGraph `/files/upload-batches/{id}` |
| `GET /api/files/cases/{id}/upload-batches` | 新增 | LangGraph `/files/cases/{id}/upload-batches` |

### 6.3 代理层统一处理

- **认证**: 使用 `LANGGRAPH_API_KEY`（如有）或内部网络白名单
- **case_id 注入**: 代理层校验用户对该 `case_id` 的访问权限
- **错误转换**: LangGraph 错误码映射为前端友好的错误消息
- **日志**: 记录上传批次 ID，便于问题追踪

---

## 7. 错误处理

### 7.1 上传阶段错误

| 场景 | 错误表现 | 前端处理 |
|------|----------|----------|
| 文件过大 (>50MB) | 前端拦截 | 选中时提示"单个文件不超过 50MB" |
| 文件类型不支持 | 前端拦截 | 提示"仅支持 PDF/Word/Excel/图片" |
| 校验接口返回重复 | `duplicate_files` 非空 | 弹窗提示"以下文件已存在，是否覆盖？" |
| 校验接口返回错配 | `suspected_mismatch_files` 非空 | 弹窗提示"以下文件类别疑似不匹配，是否继续？" |
| 上传接口 500 | 网络/服务端错误 | Toast 提示"上传失败，请重试"，保留文件选择 |
| 上传接口 413 | 请求体过大 | 提示"总文件大小超过限制，请分批上传" |

### 7.2 处理阶段错误

| 场景 | 错误表现 | 前端处理 |
|------|----------|----------|
| 轮询到 `status=failed` | 后端处理失败 | 展示错误信息，提供"重新上传"按钮 |
| 轮询超时 (5min) | 长时间未 completed | 提示"处理时间较长，已转入后台运行，请稍后刷新查看" |
| 批次详情 404 | batch_id 不存在 | 提示"批次信息不存在或已过期" |
| 持久化校验失败 | `persistence_checks` 异常 | 展示警告标签"部分文件处理异常"，引导联系管理员 |

### 7.3 网络中断恢复

- 上传过程中断网：展示"网络异常"，提供"继续上传"按钮（由于 multipart 上传不支持断点续传，需重新上传）
- 轮询过程中断网：静默重试 3 次，仍失败则提示"状态获取失败，请手动刷新"

---

## 8. 实现顺序

1. **Phase 1**: 基础代理层
   - 确认 `app/api/ingest/upload/route.ts` 可用，对齐请求/响应格式
   - 新增 `GET /api/files/upload-batches/[id]/route.ts`
   - 新增 `GET /api/files/cases/[id]/upload-batches/route.ts`

2. **Phase 2**: 上传对话框组件
   - 封装 `UploadMaterialDialog` 组件（基于现有 `AddMaterialDialog` 改造）
   - 集成类别选择（§2.1）、案件覆盖提示（§2.2）
   - 集成上传前校验（§2.3）

3. **Phase 3**: 上传流程与状态管理
   - 实现 multipart 上传逻辑
   - 实现轮询状态机（stored → processing → completed/failed）
   - 实现结果展示（成功/失败文件列表、结论变更提示）

4. **Phase 4**: 案件详情页上传历史
   - 调用 §2.6 查询案件上传批次列表
   - 展示批次列表，支持展开查看详情（§2.5）
   - 实时刷新：上传完成后自动刷新列表

5. **Phase 5**: 案件列表快捷上传
   - 保留案件列表的"添加材料"按钮
   - 点击直接打开上传对话框，预填充案件 ID

---

## 9. 与现有系统的对接

### 9.1 与案件列表页

案件列表页已有"添加材料"按钮（`app/(main)/cases/page.tsx`），点击后打开上传对话框。上传完成后**不自动跳转**分析页面（跳转逻辑已移除），仅刷新案件覆盖状态。

### 9.2 与对话系统

上传的文件通过 `upload_batch_id` 与对话关联。用户在对话中上传文件时：
1. 走本 spec 的上传流程，获得 `upload_batch_id`
2. 发送消息时，将 `upload_batch_id` 加入 `ChatRequest.uploaded_files`
3. LangGraph 在 `chat/invoke` 中引用该批次的材料进行回答

### 9.3 与材料事件系统

上传成功后返回的 `material_event_id` 可用于：
- 在案件详情页展示材料事件时间线（调用 `GET /files/material-events/{id}`，详见 LangGraph 设计 spec §12.1）
- 追踪结论演进（调用 `GET /files/cases/{id}/evolution-items`）

---

## 10. 附录：接口快速参考

### 10.1 接口汇总

| 接口 | 方法 | 路径 | 用途 |
|------|------|------|------|
| 获取标准卷宗类别 | GET | `/api/ingest/doc-categories` | 上传表单下拉选项 |
| 查询案件卷宗覆盖 | GET | `/api/case/{case_id}/doc-categories` | 展示缺失类别引导 |
| 上传前校验 | POST | `/api/ingest/validate-doc-category` | 预检重复/错配 |
| 上传并触发摄入 | POST | `/files/upload-and-ingest` | 核心上传接口 |
| 查询批次详情 | GET | `/files/upload-batches/{id}` | 轮询处理状态 |
| 查询案件批次列表 | GET | `/files/cases/{id}/upload-batches` | 展示上传历史 |

### 10.2 环境变量

```bash
# 已配置于 .env.example
LANGGRAPH_API_BASE_URL=http://10.0.10.2:8081  # 或实际部署地址
LANGGRAPH_API_KEY=                              # 如需认证
```

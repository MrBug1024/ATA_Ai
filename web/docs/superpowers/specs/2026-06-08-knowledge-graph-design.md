# 知识图谱与证据追溯 — 前端设计文档

**日期**: 2026-06-08  
**后端手册**: 前端调用手册-追溯与知识图谱  
**后端入口**: `http://10.0.10.2:8081`（通过 `LANGGRAPH_API_BASE_URL`）

---

## 1. 范围

本文档覆盖以下 9 个后端接口的前端实现：

| # | 接口 | 功能 |
|---|---|---|
| 1 | `POST /evidence/resolve` | citation → 证据抽屉 |
| 2 | `GET /files/page-anchors` | 单页 bbox + 页图 |
| 3 | `POST /graph/subgraph` | 实体 N 跳子图 |
| 4 | `POST /graph/relation-evidence` | relation → claim 证据链 |
| 5 | `GET /files/cases/{id}/evolution-items` | 结论演进时间线 |
| 6 | `GET /files/cases/{id}/unresolved-items` | 未决补件列表 |
| 7 | `GET /files/cases/{id}/material-events` | 材料事件时间线（hook 已有） |
| 8 | `POST /graph/demo-case-trace/validate` | 标杆案件发布前验收 |
| 9 | `POST /chat/invoke` | 已有，新增 trace_items 消费 |

**不覆盖**：后端架构、LLM prompt、数据库 DDL、权限系统。

---

## 2. 整体布局决策

**方案 C — 混合**：

- **证据抽屉**：在 `/chat/[id]` 页内嵌，右侧滑入 Sheet
- **知识图谱**：全屏 Modal，从多个入口触发，全局挂载
- **治理功能**：新建 `/cases/[id]` 页，面向操作员/管理员

### 路由变更

| 路由 | 状态 | 说明 |
|---|---|---|
| `/chat/[id]` | 修改 | 新增证据抽屉 + 图谱触发按钮 |
| `/cases` | 轻改 | 案件卡片加"治理 →"跳转链接 |
| `/cases/[id]` | **新建** | 案件治理中心 |

---

## 3. 组件清单

### 3.1 EvidenceDrawer

**位置**: `components/knowledge-graph/evidence-drawer.tsx`  
**触发**: 点击报告正文中的 `[1]` `[2]` 角标  
**接口**: `POST /evidence/resolve`, `GET /files/page-anchors`

#### 触发链路

```
markdown-text.tsx
  └── CitationButton（拦截 [N] 格式，onClick）
        └── 读取 EvidenceContext（caseId + reportRef）
              └── 更新 evidenceDrawerStore → EvidenceDrawer 展开
```

`reportRef` 和 `caseId` 通过 React context 下发。runtime 在 SSE `final` 事件时将 `final_report_ref` 存入消息 metadata，渲染层从 metadata 读取后注入 context。

#### 布局（右侧 Sheet，width=480px）

```
EvidenceDrawer
├── DrawerHeader
│     ├── claim_text（抽屉标题）
│     ├── confidence badge（0–1，颜色：≥0.8=绿，≥0.5=黄，<0.5=红）
│     └── ✕ 关闭
├── EvidenceList（width=160px，固定，竖向滚动）
│     └── EvidenceItem × N
│           file_name / page_no
│           quote_text（前40字，超出省略）
│           点击 → 更新 PageViewer
└── PageViewer（flex:1）
      ├── <img src={page_image_ref} style="width:100%" />
      ├── BboxOverlay（绝对定位层，pointer-events:none）
      │     └── 每个 bbox → 半透明蓝色 div + 蓝色 border
      └── PageNav（← 上一页 / 下一页 →）
            └── 调 usePageAnchors(fileId, pageNo)
```

#### BBox 坐标换算

```ts
left   = (bbox.x / page_width)  * imgElement.clientWidth
top    = (bbox.y / page_height) * imgElement.clientHeight
width  = (bbox.w / page_width)  * imgElement.clientWidth
height = (bbox.h / page_height) * imgElement.clientHeight
```

#### 状态

```ts
interface EvidenceDrawerState {
  open: boolean
  caseId: number
  reportRef: string
  citationId: string
  selectedEvidenceIndex: number   // 初始 = primary_evidence
  currentPage: PageState | null   // { fileId, pageNo, imageRef, anchors, pageWidth, pageHeight }
}
```

切换 `selectedEvidence` 时：同页只更新高亮框；跨页调 `usePageAnchors`。

#### 边界情况

- `primary_evidence = null`：显示"该角标暂无页图证据"空态，左侧列表仍可用
- `page_image_ref` 加载失败：显示文件名 + 页码文字占位
- `evidences.length > 20`：列表内部滚动，不截断

---

### 3.2 GraphModal

**位置**: `components/knowledge-graph/graph-modal.tsx`  
**挂载**: `app-shell.tsx` 全局层  
**图谱库**: Cytoscape.js + fcose 布局  
**接口**: `POST /graph/subgraph`, `POST /graph/relation-evidence`

#### 触发入口

| 位置 | 触发 | 初始参数 |
|---|---|---|
| `/chat/[id]` 顶部工具栏 | "🕸 图谱" 按钮 | `{ caseId }` |
| EvidenceDrawer 底部 | "在图谱中查看" 链接 | `{ caseId, centerEntityId }` |
| `/cases/[id]` 页头 | "查看图谱" 按钮 | `{ caseId }` |

通过 Zustand store `graphModalStore` 管理 `{ open, caseId, centerEntityId? }`。

#### 组件结构

```
GraphModal（Dialog，fullscreen，z-index:50）
├── GraphToolbar
│     ├── 深度选择器（1 / 2 / 3，默认 2）
│     ├── 关系类型多选（留空=全部）
│     ├── 中心实体 label（可编辑，搜索切换）
│     └── ✕ 关闭
├── CytoscapeCanvas（flex:1）
│     └── 渲染 useGraphSubgraph 返回的 nodes / edges
└── RelationDetailPanel（width=320px，初始 hidden，点击节点/边展开）
      ├── 节点模式
      │     ├── entity label / entity_type / risk_level badge
      │     └── "以此为中心" 按钮 → 重新拉子图
      └── 边模式
            ├── relation_type / relation_label / confidence
            ├── claim 列表（来自 useRelationEvidence）
            │     └── ClaimItem：claim_text + EvidenceItem 列表
            └── 点 EvidenceItem → 打开 EvidenceDrawer（在 Modal 上层，z-index:60）
```

#### 节点/边视觉映射

| 字段 | 视觉 |
|---|---|
| `entity_type: company` | 蓝色节点 `#1e3a5f` |
| `entity_type: person` | 绿色节点 `#1e3a1e` |
| `entity_type: mine_right` | 紫色节点 `#2a1e3a` |
| `entity_type: other` | 灰色节点 `#1e1e2e` |
| `risk_level: high` | 红色边框 `#ef4444` |
| `risk_level: medium` | 橙色边框 `#f97316` |
| `risk_level: low` | 无特殊边框 |
| `risk_level: unknown` | 灰色虚线边框 |
| `confidence` | 边透明度线性映射 0.5–1.0 |
| 中心节点 | 尺寸 1.5x，白色描边 |
| 选中节点/边 | 高亮描边 `#ffffff`，触发 RelationDetailPanel |

#### 深度/筛选更新

改变 `depth` 或 `relation_types` → 重新调 `useGraphSubgraph` → `cy.json({ elements })` 热更新，fcose 布局重算，动画过渡 300ms。

#### 边界情况

- `nodes.length > 80`：提示"节点过多，建议缩小深度或筛选关系类型"，不渲染图谱
- 无边数据：空图提示"该实体暂无关联关系"
- EvidenceDrawer 在 Modal 内打开：Sheet z-index=60，关闭 Sheet 回到 Modal（Modal 不关闭）

---

### 3.3 CaseDetailPage（`/cases/[id]`）

**位置**: `app/(main)/cases/[id]/page.tsx`  
**目标用户**: 操作员 / 管理员

#### 页面结构

```
CaseDetailPage
├── PageHeader
│     ├── 案件名称 / case_id / debtor_names
│     ├── "查看图谱" 按钮
│     └── DemoValidationGate（仅 reportRef 存在时显示）
└── Tabs（shadcn Tabs，默认激活"材料事件"）
      ├── Tab "材料事件"   → MaterialEventTimeline
      ├── Tab "结论演进"   → EvolutionTimeline
      └── Tab "未决补件"   → UnresolvedItemsPanel
```

Cases 列表页的案件卡片新增"治理 →"链接跳转到此页。

---

### 3.4 DemoValidationGate

**接口**: `POST /graph/demo-case-trace/validate`

```
DemoValidationGate
├── 未验收：灰色"验收"按钮
├── 验收中：loading spinner
├── ready=true：绿色"✓ 可发布" badge + "发布" 按钮激活
└── ready=false：红色"X 条角标失败" badge
      └── checks 列表（展开）
            └── CheckItem：citation_id / claim_text / ok=false / issues[]
```

`reportRef` 从案件关联的最新会话 `langgraphThreadId` 派生，由页面初始化时从 conversations API 拉取。

---

### 3.5 MaterialEventTimeline

**接口**: `GET /files/cases/{id}/material-events`（hook `useCaseMaterialEvents` 已有）

```
MaterialEventTimeline
└── EventCard × N（倒序 created_at）
      ├── 时间 dot（completed=绿 / processing=蓝动画 / failed=红 / received=灰）
      ├── batch_name / doc_category / operator_name
      ├── stage badge（stored / ocr_running / graph_running / completed / failed）
      ├── file_count · records_inserted
      ├── has_conclusion_changes=true → "↑ N条结论变化" 橙色 badge
      └── status=failed → error_message 展开按钮
```

---

### 3.6 EvolutionTimeline

**接口**: `GET /files/cases/{id}/evolution-items`

```
EvolutionTimeline
├── ActionFilter（全部 / 新增 / 替代，shadcn ToggleGroup）
└── EvolutionItem × N（倒序 created_at）
      ├── ADD
      │     ├── 绿色 "+" badge + new_claim_type
      │     ├── new_claim_text
      │     ├── batch_name / doc_category
      │     └── evidences → 折叠展开（复用 EvidenceItem 渲染）
      └── OVERRIDE
            ├── 橙色 "↺" badge
            ├── 双列对比
            │     ├── 左：superseded_claim_text（灰色，删除线）
            │     └── 右：new_claim_text（白色）
            ├── rationale（替代理由，超过60字折叠）
            └── evidences → 折叠展开
```

---

### 3.7 UnresolvedItemsPanel

**接口**: `GET /files/cases/{id}/unresolved-items?status=pending`

```
UnresolvedItemsPanel
├── 摘要行："N 条关系未决 · M 条断言未决"
│     空态：绿色 "✓ 全部依赖已补齐"
├── Section "未决关系"（unresolved_relation_count > 0 时显示）
│     └── UnresolvedRelationRow × N
│           relation_type badge / relation_label
│           reason（人类可读说明）
│           missing_dependencies → 红色 tag 列表
└── Section "未决断言"（unresolved_claim_count > 0 时显示）
      └── UnresolvedClaimRow × N
            claim_type badge / claim_text
            entity_name / relation_key
            missing_dependencies → 红色 tag 列表
```

---

## 4. 新增 SWR Hooks

| Hook | 文件 | 接口 |
|---|---|---|
| `useEvidenceResolve` | `lib/hooks/use-evidence-resolve.ts` | `POST /evidence/resolve` |
| `usePageAnchors` | `lib/hooks/use-page-anchors.ts` | `GET /files/page-anchors` |
| `useGraphSubgraph` | `lib/hooks/use-graph-subgraph.ts` | `POST /graph/subgraph` |
| `useRelationEvidence` | `lib/hooks/use-relation-evidence.ts` | `POST /graph/relation-evidence` |
| `useEvolutionItems` | `lib/hooks/use-evolution-items.ts` | `GET /files/cases/{id}/evolution-items` |
| `useUnresolvedItems` | `lib/hooks/use-unresolved-items.ts` | `GET /files/cases/{id}/unresolved-items` |
| `useDemoCaseValidate` | `lib/hooks/use-demo-case-validate.ts` | `POST /graph/demo-case-trace/validate` |

所有 POST 类 hook 使用 SWR mutation（`useSWRMutation`），GET 类使用标准 `useSWR`。

---

## 5. 新增 Zustand Stores

| Store | 文件 | 用途 |
|---|---|---|
| `evidenceDrawerStore` | `lib/stores/evidence-drawer.ts` | 抽屉 open 状态 + 当前参数 |
| `graphModalStore` | `lib/stores/graph-modal.ts` | Modal open 状态 + caseId + centerEntityId |

---

## 6. 类型定义

新增 `lib/types/knowledge-graph.ts`，包含：

- `EvidenceItem` — chunk_id / file_id / file_name / page_no / quote_text / bbox_list / page_image_ref
- `BBox` — x / y / w / h
- `GraphNode` — id / entity_id / label / entity_type / risk_level
- `GraphEdge` — id / relation_id / source / target / label / relation_type / confidence
- `TraceItem` — citation_id / claim_id / claim_type / claim_text / confidence / evidences
- `EvolutionItem` — action / new_claim_* / superseded_claim_* / rationale / evidences / ...
- `UnresolvedRelation` / `UnresolvedClaim`
- `MaterialEvent`（已有，确认对齐）
- `ValidationCheck` / `ValidationResult`

---

## 7. 文件结构

```
components/knowledge-graph/
  evidence-drawer.tsx
  citation-button.tsx
  page-viewer.tsx
  bbox-overlay.tsx
  graph-modal.tsx
  cytoscape-canvas.tsx
  relation-detail-panel.tsx
  evolution-timeline.tsx
  unresolved-items-panel.tsx
  material-event-timeline.tsx
  demo-validation-gate.tsx

lib/hooks/
  use-evidence-resolve.ts
  use-page-anchors.ts
  use-graph-subgraph.ts
  use-relation-evidence.ts
  use-evolution-items.ts
  use-unresolved-items.ts
  use-demo-case-validate.ts

lib/stores/
  evidence-drawer.ts
  graph-modal.ts

lib/types/
  knowledge-graph.ts

app/(main)/cases/[id]/
  page.tsx
```

---

## 8. 实现顺序（优先级）

1. **类型定义** — `lib/types/knowledge-graph.ts`
2. **SWR hooks** — 7 个，可并行
3. **EvidenceDrawer** — 最高频组件，优先交付
4. **CitationButton + EvidenceContext** — 打通 markdown → 抽屉链路
5. **GraphModal + CytoscapeCanvas** — 依赖 hooks 就绪
6. **RelationDetailPanel** — GraphModal 内部
7. **`/cases/[id]` 页** — 4 个治理组件
8. **集成测试** — 完整链路：报告 → 角标点击 → 抽屉 → 图谱

---

## 8.5 `/chat/[id]` 页集成增强

利用 `/chat/invoke` 响应里已有的图谱字段，无需额外接口调用：

| 字段 | 前端处理 |
|---|---|
| `trace_items` | 角标 hover tooltip：显示 claim_text + 前两条证据文件名 |
| `citation_coverage.coverage_ratio < 0.8` | 报告顶部橙色警告条："部分关键结论未挂证据（覆盖率 X%）" |
| `unresolved_relations` / `unresolved_claims` 非空 | 顶部工具栏 badge："待补件 N" 橙色，点击跳 `/cases/[id]` 治理页 |

`DemoValidationGate` 的 `reportRef` 通过查询案件关联的最新会话获取：  
`GET /api/conversations?caseId={id}` → 取最新一条的 `langgraphThreadId` 构建 `final_report:{threadId}`。  
若无关联会话则 DemoValidationGate 不显示。

---

## 9. 联调注意事项

- `citation_id` 是**字符串**（"1" "2"），不是 int
- `chunk_id` 是**字符串**，`file_id` / `entity_id` / `relation_id` 是 int
- `report_ref` 必须用响应里的 `final_report_ref`，不可自拼
- bbox 坐标系：`page_image_ref` 实际像素 = `page_width × page_height`
- `page_image_ref` / MinIO URL 直接用，无需 presigned
- `depth` 不超过 3，`nodes > 80` 时前端主动拦截
- EvidenceDrawer 在 GraphModal 内打开时 z-index 须高于 Modal（z-50 → z-60）

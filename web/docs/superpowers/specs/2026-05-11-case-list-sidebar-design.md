# 侧边栏案件列表设计文档

**日期**: 2026-05-11  
**状态**: 待实现

---

## 背景

AI Hunter 审计平台需要在侧边栏展示案件列表，方便用户快速定位案件并一键开启针对该案件的 AI 对话。

---

## 需求

1. 侧边栏新增"案件列表"区块，位于"对话/文件"导航下方、"最近对话"上方
2. 从 `GET http://10.0.10.2:8080/api/cases` 获取案件数据（通过 Next.js proxy）
3. 每条案件显示：案件名、债务人名、综合风险分（彩色）、状态
4. 支持关键词搜索（防抖后调 API）和加载更多分页
5. 点击案件 → 跳转 `/chat` 并在输入框预填案件上下文，用户补充问题后发送

---

## 不在范围内

- 案件详情页
- 案件筛选（case_type / status 过滤，仅关键词搜索）
- 案件创建/编辑
- Dify 配置变更

---

## 架构

### 数据流

```
侧边栏 CaseList
  └─ use-cases hook (SWR)
       └─ GET /api/cases (Next.js proxy, auth-guarded)
            └─ http://10.0.10.2:8080/api/cases
```

### 新对话预填流

```
点击案件条目
  └─ router.push('/chat?case_id=123&case_name=xxx&debtor=yyy')
       └─ /chat/page.tsx 读 useSearchParams
            └─ composer 初始值 = "分析案件 #123（案件名，债务人：xxx）："
```

---

## 详细设计

### 1. `app/api/cases/route.ts`（新建）

- `requireSession()` auth guard
- 透传 query 参数：`keyword`, `case_type`, `status`, `page`, `page_size`
- 转发到 `http://10.0.10.2:8080/api/cases`
- 原样返回响应 JSON

### 2. `lib/hooks/use-cases.ts`（新建）

```ts
interface Case {
  id: number
  case_name: string
  case_type: string
  debtor_name: string
  status: string
  composite_score?: number
  delta_score?: number
  valuation_score?: number
  deadline_score?: number
  behavioral_score?: number
}

interface UseCasesResult {
  cases: Case[]
  isLoading: boolean
  total: number
  page: number
  setPage: (p: number) => void
  keyword: string
  setKeyword: (k: string) => void
}
```

- SWR key 包含 `keyword` 和 `page`，关键词变化时 page 重置为 1
- 追加模式：page > 1 时 `cases` 为累积数组（加载更多）

### 3. `components/layout/app-sidebar.tsx`（修改）

新增内部组件 `CaseList`（与 `ConversationList` 同级）：

**每条案件显示：**
- 案件名（`text-xs truncate`）
- 债务人名（`text-[10px] text-sidebar-foreground/50 truncate`）
- 综合风险分 badge：
  - ≥ 75：`text-red-400 bg-red-400/10`
  - 50–74：`text-amber-400 bg-amber-400/10`
  - < 50 或无：`text-emerald-400 bg-emerald-400/10`
- 状态 badge：进行中 / 已结案 / 暂停（`text-[9px]`）

**区块结构：**
```
<SidebarSeparator />
<SidebarGroup>
  <SidebarGroupLabel>
    案件列表
    <button 搜索图标 />
  </SidebarGroupLabel>
  [搜索框，展开态]
  <SidebarGroupContent 溢出滚动>
    <CaseList />
    [加载更多按钮]
  </SidebarGroupContent>
</SidebarGroup>
<SidebarSeparator />
```

**交互：**
- 点击案件：`router.push('/chat?case_id=...')`
- 搜索图标：展开/收起输入框，300ms debounce 触发 `setKeyword`
- "加载更多"：`setPage(page + 1)` 追加

### 4. `app/(main)/chat/page.tsx`（修改）

```ts
const searchParams = useSearchParams()
const caseId = searchParams.get('case_id')
const caseName = searchParams.get('case_name')
const debtor = searchParams.get('debtor')

const initialComposerValue = caseId
  ? `分析案件 #${caseId}（${caseName}，债务人：${debtor}）：`
  : ''
```

- `initialComposerValue` 传给 `ChatThread`，内部通过 `useComposerRuntime().setText(initialComposerValue)` 在 mount 时设置初始文本（`@assistant-ui/react` 受控输入，不能用 `defaultValue`）
- 无参数时行为与现在完全相同

---

## 文件清单

| 操作 | 路径 |
|------|------|
| 新建 | `app/api/cases/route.ts` |
| 新建 | `lib/hooks/use-cases.ts` |
| 修改 | `components/layout/app-sidebar.tsx` |
| 修改 | `app/(main)/chat/page.tsx` |
| 修改 | `components/chat/chatgpt-thread.tsx`（接收 initialComposerValue prop） |

---

## 错误处理

- 请求失败：显示"加载失败"提示 + 重试按钮
- 空列表：显示"暂无案件"占位文字
- 内网不可达：同上，不影响其他功能

---

## 环境变量

新增（可选）：
```
CASES_API_BASE_URL=http://10.0.10.2:8080
```

默认值 fallback 到 `http://10.0.10.2:8080`，避免硬编码。

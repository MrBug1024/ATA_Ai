# AI Hunter 全面优化设计

**日期：** 2026-05-11  
**状态：** 已批准  
**推进策略：** 方案 A — 基础先行（架构 → 性能 → UI → 测试）

---

## 一、架构重构

### 目标

消除 `use-dify-runtime.ts` 与 `use-new-chat-runtime.ts` 之间约 70% 的重复代码，统一服务端与客户端的 think 标签处理，拆分职责单一的模块。

### 新增文件

| 文件 | 职责 |
|------|------|
| `lib/utils/think.ts` | `extractThink` + `stripThink`，服务端和客户端共用 |
| `lib/assistant-ui/sse.ts` | `parseSseStream` + `runStream`，SSE 解析与流式处理循环 |
| `lib/assistant-ui/use-thinking.ts` | `useThinking` hook，封装 `initThinking / updateThinking / completeThinking` 全套状态管理 |
| `lib/assistant-ui/convert-message.ts` | `convertDbMessage`，统一的消息格式转换函数 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `app/api/chat/route.ts` | 删除内联 `stripThink`，改为 import `lib/utils/think.ts` |
| `lib/assistant-ui/use-dify-runtime.ts` | 保留已有对话特有逻辑（`fetchMessages`、`handleReload`），其余 import 自新模块；预计从 757 行缩减至 ~200 行 |
| `lib/assistant-ui/use-new-chat-runtime.ts` | 保留新建对话特有逻辑（创建 conversation 后发消息），其余 import 自新模块；预计从 468 行缩减至 ~150 行 |

### 约束

- 重构过程中不改变任何外部行为，仅移动和合并代码
- 两个 runtime 的公共 interface（`DbMessage`、`AttachmentMeta`）提取到 `lib/assistant-ui/types.ts`

---

## 二、性能优化

### 数据请求层迁移

用 **SWR** 替换 `lib/hooks/` 下的手动 fetch 模式。

**改动范围：**

| 文件 | 改动 |
|------|------|
| `lib/hooks/use-conversations.ts` | 用 `useSWR` 重写，key 为 `/api/conversations` |
| `lib/hooks/use-files.ts` | 用 `useSWR` 重写，key 为 `/api/files` |

**收益：**
- 跨组件自动缓存，切换页面不重复请求
- 多处使用同一 key 自动去重
- 乐观更新（删除、重命名）通过 `mutate` 实现，无需手动维护本地数组
- 浏览器重新聚焦时自动重新验证

### 依赖清理

- 移除 `framer-motion`（代码中无任何使用）
- 移除 `@modelcontextprotocol/sdk`（代码中无任何使用）

---

## 三、UI 改进

### 3.1 侧边栏搜索

- 新建对话按钮旁新增搜索图标（`SearchIcon`）
- 点击后展开搜索输入框，覆盖侧边栏顶部区域
- 实时过滤已加载的对话列表（**客户端过滤**，无额外请求）
- 再次点击图标或输入框失焦时收起，清空搜索词
- 列表按时间倒序排列，无日期分组

### 3.2 对话重命名

- 侧边栏对话项 hover 时，在删除图标旁显示铅笔图标（`PencilIcon`）
- 点击铅笔图标后，该条目切换为 inline `<input>`，预填当前标题
- 回车或失焦：调用 `PATCH /api/conversations/[id]` 保存，通过 SWR `mutate` 更新缓存
- Esc：取消，恢复原标题
- **新增 API：** `PATCH /api/conversations/[id]`，接受 `{ title: string }`

### 3.3 文件预览面板

**布局：** 文件列表页分为左右两栏，点击文件后右侧面板滑出（占页面约 45% 宽度）。

**支持格式：**

| 类型 | 渲染方式 |
|------|---------|
| PDF | `<iframe src="/api/files/preview/[fileId]">` |
| 图片（JPG/PNG/GIF/WebP） | `<img src="/api/files/preview/[fileId]">` |
| 纯文本（TXT/CSV/MD 等） | `fetch` 内容后用 `<pre>` 展示 |
| 其他格式 | 显示文件信息 + 下载按钮，不预览 |

**面板内容：** 文件名、格式标识、下载按钮，点击列表中其他文件直接切换（面板保持打开）。

**复用现有接口：** 预览请求走已有的 `/api/files/preview/[fileId]` 代理，无需新增接口。

---

## 四、测试

### 框架选型

| 层级 | 框架 | 理由 |
|------|------|------|
| 单元 / 集成 | **Vitest** | 与 Next.js/TypeScript 无需额外配置，速度快 |
| E2E | **Playwright** | 项目已有 `.playwright-mcp/` 目录，已安装 |

### 覆盖范围

**单元测试（Vitest）：**
- `lib/utils/think.ts`：`extractThink`（嵌套标签、未闭合标签、无标签）、`stripThink`
- `lib/api/response.ts`：`successResponse`、`errorResponse`
- `lib/api/validate.ts`：schema 校验边界情况
- `lib/assistant-ui/convert-message.ts`：`convertDbMessage`（各种 attachment 来源）

**集成测试（Vitest + 真实 DB）：**
- `POST /api/conversations`：创建对话
- `GET /api/conversations`：列表返回正确数据
- `PATCH /api/conversations/[id]`：重命名（新增接口）
- `DELETE /api/conversations/[id]`：删除 + 级联校验
- `GET /api/conversations/[id]/messages`：消息含 serverAttachments

**E2E 测试（Playwright）：**
- 注册 / 登录流程
- 新建对话 → 发送消息 → 流式响应完成
- 上传文件 → 在对话中引用
- 文件页打开预览面板（PDF / 图片）
- 对话重命名
- 搜索过滤对话

### 目标覆盖率

核心工具函数和 API 路由达到 **80%+**，E2E 覆盖所有关键用户流程。

---

## 实施顺序

```
阶段 1：架构重构
  └─ 提取共享模块 → 精简两个 runtime → 无行为变化

阶段 2：性能优化
  └─ SWR 迁移 → 清理无用依赖

阶段 3：UI 改进
  ├─ 侧边栏搜索
  ├─ 对话重命名（含新 API）
  └─ 文件预览面板

阶段 4：测试
  ├─ 单元测试
  ├─ 集成测试
  └─ E2E 测试
```

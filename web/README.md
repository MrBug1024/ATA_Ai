# AI Hunter

AI 辅助文档分析与案件管理前端。Next.js 只负责页面渲染与静态资源，浏览器通过 `lib/backend/` 直连后端，不在 Web 应用内维护业务数据库或认证服务。

## 架构

```text
Browser (Next.js / React)
  └── lib/backend/* ─────────────> Unified API :8081
      ├── auth.ts                  /auth/*、/me
      ├── admin.ts                 /companies、/users、/roles、/tag-catalog
      ├── langgraph.ts
  │   ├── /chat/*                 对话与会话
  │   ├── /files/*                文件上传与摄入
  │   └── /graph/*、/cases/*      图谱、进度、复盘等
      └── cases.ts                 /api/* 案件、卷宗类别与领域引擎
```

前端不包含 PostgreSQL、Drizzle、Better Auth 或 Next.js API Routes。登录令牌由统一后端 `/auth/login` 签发，后续请求通过 `Authorization: Bearer <token>` 访问同一后端，身份通过 `GET /me` 校验。令牌保存在浏览器 `localStorage`，任何富文本或外部内容渲染都必须保持严格净化。

## 本地开发

前置要求：Node.js 20+、pnpm 10+。

```bash
pnpm install
cp .env.example .env.local
pnpm dev
```

开发服务默认运行在 [http://localhost:3000](http://localhost:3000)。后端必须允许浏览器来源跨域访问，并允许 `Authorization` 与 `Content-Type` 请求头。

### 环境变量

| 变量 | 说明 | 示例 |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | 统一认证、AI、案件、文件、图谱与领域 API；浏览器直连 | `http://10.0.10.2:8081` |

`NEXT_PUBLIC_*` 会进入浏览器 bundle，只能放公开地址，不能放密钥。Docker 构建时必须提供这些值，运行容器后再修改不会更新已经编译的前端代码。

## 常用命令

```bash
pnpm dev              # 启动开发服务
pnpm build            # 生产构建
pnpm start            # 启动生产服务
pnpm test             # Vitest 单元/集成测试
pnpm test:e2e         # Playwright E2E 测试
pnpm test:coverage    # 覆盖率检查
```

## Docker 部署

`docker-compose.yml` 只启动前端应用，不再创建数据库或运行迁移。

```bash
NEXT_PUBLIC_API_BASE_URL=http://10.0.10.2:8081 \
docker compose up -d --build
```

该公开地址作为 Docker build arg 编译进客户端。后端地址变化时需要重新构建镜像。

## 后端契约约束

`lib/backend/` 是唯一的后端契约模块。组件、hooks 和页面不得直接拼接后端 URL 或直接 `fetch` 后端。

```ts
import { getThreadDetail, getThreadTurns, deleteThread } from "@/lib/backend/langgraph";
import { createCase } from "@/lib/backend/cases";
```

- `lib/api/client.ts`：浏览器请求、鉴权头、401 处理和后端 URL builder。
- `lib/backend/http.ts`：统一 JSON/form 请求与 FastAPI 错误解析。
- `lib/backend/auth.ts`：登录、身份、登出与改密操作。
- `lib/backend/admin.ts`：公司、用户、标签、用户角色及角色权限操作。
- `lib/backend/langgraph.ts`：AI、会话、文件、图谱与治理操作。
- `lib/backend/cases.ts`：案件与卷宗类别操作；接口仍保持原 `/api/*` 路径。

SWR hooks 必须使用 backend 模块导出的 key builder，并调用对应命名操作。

## 管理后台

`/admin` 提供管理概览、公司、用户和角色权限页面。用户主档、用户角色和三个标签维度分别保存，避免多个写接口部分成功时误报为一次完整成功；后端 OpenAPI 未提供删除操作，因此前端也不展示伪删除入口。

当前后端的公司管理员接口尚未按租户收口，前端暂时只允许真实 `is_super_admin=true` 的身份进入管理后台；认证关闭时仅允许后端明确返回的 `__system__` 身份用于本地预览。前端守卫只负责导航与展示，所有授权仍必须由后端执行。后端租户隔离问题见 [NpaLang #16](https://github.com/jonymonkey089-wq/NpaLang/issues/16)。

## SSE 事件

`POST /chat/invoke` 返回原始 SSE，前端由 `lib/assistant-ui/sse.ts` 解析：

```text
event: start       data: {"thread_id":"...","query":"..."}
event: node        data: {"node":"agent","summary":"步骤说明","payload":{}}
event: text_chunk  data: {"text":"增量 token"}
event: final       data: {"final_report":"完整回答","final_report_ref":"..."}
event: done        data: {}
event: error       data: {"message":"..."}
```

消费方按 `LangGraphSseEvent` 的 `type` 分支处理。`final_report` 不覆盖已经累积的 `text_chunk`，只保存 `final_report_ref` 用于证据追溯。

## 关键目录

```text
app/                         Next.js 页面（无服务端 API Routes）
components/                  页面与 UI 组件
lib/api/client.ts            浏览器 API 客户端与鉴权
lib/backend/                 唯一后端契约层
lib/assistant-ui/            对话 runtime、SSE、附件处理
lib/hooks/                   SWR 与 mutation hooks
lib/upload/                  卷宗上传状态机
tests/unit/                  单元测试
tests/e2e/                   Playwright 测试
```

## 技术栈

Next.js 16、React 19、TypeScript、Tailwind CSS v4、shadcn/ui、`@assistant-ui/react`、SWR、Zustand、Vitest 和 Playwright。

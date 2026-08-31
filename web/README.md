# 年度审计智能体前端

Next.js 前端保留原平台的 AI 对话使用方式，并通过同一个后端完成登录、年度审计项目选择、资料上传、证据追溯、关系图谱、报告草稿和工作底稿产物、人工复核。

## 配置与启动

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080
```

```powershell
pnpm install
pnpm dev
```

访问 <http://localhost:3000>。前端不维护数据库或服务端业务 API，浏览器请求统一由 `lib/backend/` 发往 `8080`。

## 常用命令

```powershell
pnpm test
pnpm build
pnpm test:e2e
```

## 目录

```text
app/                 页面与路由
components/          对话、项目、资料、图谱和管理组件
lib/backend/         年度审计后端契约
lib/assistant-ui/    对话运行时与 SSE
lib/hooks/           数据查询和变更 hooks
tests/               Vitest 与 Playwright 测试
```

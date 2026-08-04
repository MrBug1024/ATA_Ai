# AI 会计师年度审计智能体

本仓库是面向年度财务报表审计的 AI 智能体平台。平台提供 AI 对话、会话记忆、文件摄入、证据追溯、关系图谱、报告生成、权限与管理后台；运行时只提供年度审计业务。

## 目录

```text
backend/   FastAPI + LangGraph 年度审计后端
web/       Next.js 对话式年度审计前端
new_docs/  客户原始资料与年度审计逻辑资料
deploy/    本地独立 PostgreSQL、MySQL、Redis、MinIO
scripts/   本地环境管理脚本
```

## 本地数据隔离

年度审计使用独立的本地存储：

- PostgreSQL：`127.0.0.1:55432/ata_agent_platform`
- MySQL：`127.0.0.1:53306/ata_ai`
- Redis：`127.0.0.1:56379`
- MinIO API：`127.0.0.1:61000`

这些存储由 `deploy/annual-audit` 管理，不连接历史项目数据库。

## 启动

```powershell
.\scripts\annual-audit-local.ps1 up

cd backend
python -m ai_hunter

cd ..\web
pnpm install
pnpm dev
```

前端只配置一个后端地址：

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080
```

访问地址：

- 前端：<http://localhost:3000>
- 后端文档：<http://localhost:8080/docs>

本地最高权限账号由年度审计种子初始化：`superadmin`。

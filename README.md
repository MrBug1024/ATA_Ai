# AI 会计师年度审计智能体

本仓库是面向年度财务报表审计的 AI 智能体平台。平台提供 AI 对话、会话记忆、文件摄入、证据追溯、关系图谱、报告草稿和工作底稿产物、人工复核、权限与管理后台；运行时只提供年度审计业务。

## 目录

```text
backend/   FastAPI + LangGraph 年度审计后端
web/       Next.js 对话式年度审计前端
new_docs/  客户原始资料与年度审计逻辑资料
deploy/    部署参考配置
scripts/   运维辅助脚本
```

## 存储配置

年度审计运行时配置只读取 `backend/.env`，字段示例见 `backend/.env.example`。所有开发与生产环境均使用外置服务：

- PostgreSQL：承载全部关系型业务与平台数据，统一使用 `POSTGRESQL_DATABASE=ata_ai`。
- Redis：缓存和 Celery broker，使用 `REDIS_HOST`、`REDIS_PORT`、`REDIS_PASSWORD`、`REDIS_NAMESPACE`。
- MinIO：线上对象存储，保存原始资料、派生预览、模板和交付成果。

不要为历史项目数据库、缓存或对象桶配置回退连接。

PostgreSQL 服务器必须预先创建 `ata_ai` 数据库，并提供 `pgcrypto` 和 `vector`（pgvector）扩展包；执行迁移的账号需要能够在该数据库创建扩展。首次部署先运行 `python -m ai_hunter.annual_audit.storage.migrate`，成功后再启动服务。

## 启动

```powershell
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

开发环境最高权限账号由年度审计权限种子初始化：`superadmin`。不要执行会创建空演示项目或客户数据的种子操作。

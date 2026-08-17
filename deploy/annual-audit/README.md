# 年审项目本地隔离数据库

该目录为年审项目提供完全独立的本地开发存储：

- PostgreSQL + pgvector：`127.0.0.1:55432/ata_agent_platform`，承载会话、权限、LangGraph、heavy payload、证据和知识图谱能力。
- MySQL：`127.0.0.1:53306/ata_ai`，只承载年审项目和结构化财务明细、分析、底稿、报告版本。
- Redis：`127.0.0.1:56379`，作为可选热点缓存；持久化事实仍在 PostgreSQL/MySQL。
- MinIO：API `127.0.0.1:61000`、控制台 `127.0.0.1:61001`，独立保存原始资料、派生文件和报告附件。

实际本地密码位于被 Git 忽略的 `.env.local`。仓库只提交 `.env.example`。

## 常用命令

在仓库根目录执行：

```powershell
# 启动或等待全部容器健康
powershell -ExecutionPolicy Bypass -File scripts/annual-audit-local.ps1 up

# 验证四类存储及数据库隔离
powershell -ExecutionPolicy Bypass -File scripts/annual-audit-local.ps1 verify

# 对既有具名卷应用幂等 MySQL 迁移
powershell -ExecutionPolicy Bypass -File scripts/annual-audit-local.ps1 migrate

# 仅初始化年审权限与 superadmin，不创建演示项目或客户数据
powershell -ExecutionPolicy Bypass -File scripts/annual-audit-local.ps1 auth-seed

# 初始化权限后额外创建空演示项目（仅用于开发验证，可重复执行）
powershell -ExecutionPolicy Bypass -File scripts/annual-audit-local.ps1 seed

# 在唯一的 8080 端口启动年度审计后端
powershell -ExecutionPolicy Bypass -File scripts/annual-audit-local.ps1 backend

# 查看状态
powershell -ExecutionPolicy Bypass -File scripts/annual-audit-local.ps1 status

# 停止容器但保留数据卷
powershell -ExecutionPolicy Bypass -File scripts/annual-audit-local.ps1 down
```

启动年审后端后可访问 `http://127.0.0.1:8080/health`。前端统一使用 `NEXT_PUBLIC_API_BASE_URL=http://localhost:8080`，所有年度审计业务继续从 `/chat` 发起。

不要把 `ANNUAL_POSTGRES_DSN` 指向其他项目数据库。验证脚本会检查年审 PostgreSQL 中不存在 `public.cases`，发现非年度审计案件表时直接失败。

## 数据卷

- `ata-annual-postgres-data`
- `ata-annual-mysql-data`
- `ata-annual-redis-data`
- `ata-annual-minio-data`

`down` 不删除数据卷。删除卷会永久清空本地年审数据，必须在确认备份和目标卷名后单独执行。

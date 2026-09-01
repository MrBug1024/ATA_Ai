# 年度审计统一后端

该服务以一个 FastAPI 进程提供年度审计项目、AI 对话、文件摄入、证据追溯、关系图谱、报告、权限与管理接口。业务域固定为 `annual_audit`，默认且唯一开发端口为 `8080`。

## 启动

```powershell
python -m pip install -e ".[dev]"
python -m ai_hunter
```

容器构建使用 `requirements-runtime.lock` 和 `requirements-build.lock` 的固定版本与 SHA-256，不会从开发机的已安装包生成依赖。更新 `pyproject.toml` 后必须在干净的 Python 3.13 环境重新解析锁文件，并在提交前用 `pip install --require-hashes -r requirements-runtime.lock` 验证。

Windows 上请始终通过上述入口启动；该入口会为 psycopg 异步连接配置兼容的 Selector 事件循环。

## 数据源

运行参数只读取 `backend/.env`，字段和值的示例见 `backend/.env.example`：

- PostgreSQL：全部关系型业务与平台数据，包括会话、权限、项目、账套、证据、图谱、报告和任务。项目数据库固定为 `POSTGRESQL_DATABASE=ata_ai`。
- Redis：大对象缓存、短期状态和 Celery broker，不保存业务真相。
- MinIO：线上原始资料、解析产物、模板、预览和报告文件。

服务不应为历史项目数据库、缓存或对象桶提供回退连接。

四个 `ANNUAL_MINIO_BUCKET_*` 桶必须由对象存储管理员预先创建；应用只检查和使用它们，不会自动创建线上桶。

目标 PostgreSQL 必须预先创建 `ata_ai`，并安装 `pgcrypto` 和 `vector`（pgvector）扩展包；迁移账号需要在该数据库创建扩展。首次部署或升级后先执行：

```powershell
python -m ai_hunter.annual_audit.storage.migrate
python -m ai_hunter.app.scripts.check_storage_readiness
```

## 核心接口

- `POST /auth/login`：登录
- `POST /chat/invoke`：年度审计 AI 对话（SSE）
- `POST /chat/upload-files`：对话内上传资料
- `GET/POST /api/cases`：年度审计项目
- `POST /api/audit/get_full_context`：年度审计完整上下文
- `POST /files/upload-and-ingest`：资料摄入
- `POST /evidence/resolve`：证据回溯
- `/graph/*`：关系图谱

## 验证

```powershell
python -m pytest -q
python -m compileall ai_hunter
```

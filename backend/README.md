# 年度审计统一后端

该服务以一个 FastAPI 进程提供年度审计项目、AI 对话、文件摄入、证据追溯、关系图谱、报告、权限与管理接口。业务域固定为 `annual_audit`，默认且唯一开发端口为 `8080`。

## 启动

```powershell
python -m pip install -e ".[dev]"
python -m ai_hunter
```

Windows 上请始终通过上述入口启动；该入口会为 psycopg 异步连接配置兼容的 Selector 事件循环。

## 数据源

运行参数优先读取仓库根目录 `deploy/annual-audit/.env.local`。默认本地数据源为：

- PostgreSQL：会话、LangGraph checkpoint、权限、证据与知识图谱
- MySQL `ata_ai`：年度审计项目、科目余额、凭证、应收、银行流水、底稿和报告
- Redis：大对象缓存与任务状态
- MinIO：原始资料、解析产物和报告文件

服务会拒绝连接名称为空或属于历史项目的 MySQL 业务库，避免误连其他项目。

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

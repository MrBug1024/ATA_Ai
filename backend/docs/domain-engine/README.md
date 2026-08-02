# NPA 领域引擎

原 `NpaDemo-main/fastapi_server` 已作为 `ai_hunter.domain_engine` 合入统一后端，不再单独启动 8080 服务。

## 运行入口

```powershell
python -m ai_hunter
```

默认监听 `0.0.0.0:8081`。统一入口位于 `ai_hunter/app/main.py`，领域路由注册桥位于 `ai_hunter/domain_engine/integration.py`。

## 保持兼容的能力

- 案件建档、列表、画像、参与方与成员管理；
- 文档分类、分类校验、解析和结构化入库；
- 轧差审计、估值挤水、司法时效和行为扫描；
- 白手套、资金流、裁判文书和企业信息；
- 完整上下文聚合；
- 任务批量创建与管理；
- 原 `/api/...`、`/health` 请求路径和 Pydantic 契约。

领域代码使用统一日志和 CORS 配置；原 API 审计日志中间件继续记录领域接口调用。数据库仍使用现有业务库，不执行迁移、不改变表结构。

## 配置

统一配置文件为 `backend/.env`。领域引擎优先使用其中的 `POSTGRES_DSN`、模型及 CPWS 配置。升级现场遗留但尚未并入 `.env` 的本地密钥可暂存于 `.env.domain.local`；该文件被版本控制忽略。

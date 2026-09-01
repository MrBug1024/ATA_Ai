# 年审运行时 Compose

此 Compose 只提供可选的应用与附件渲染运行时：`annual-api`、`attachment-worker`、`attachment-beat`、Gotenberg 和 ClamAV。它不创建、代理或初始化 PostgreSQL、Redis、MinIO 或其他关系型数据库。

所有持久化与缓存连接均从 [backend/.env](../../backend/.env) 读取。开发前先在该文件配置外置 `POSTGRESQL_*`、`REDIS_*` 与 `ANNUAL_MINIO_*`；项目数据库为 `ata_ai`，MinIO 保持已配置的线上端点和项目桶。

外置 PostgreSQL 需由 DBA 预先创建 `ata_ai`，并提供 `pgcrypto` 与 `vector`（pgvector）扩展包。运行迁移的账号必须有在 `ata_ai` 创建扩展和 DDL 的权限；迁移器会在写入前检查数据库名、最低 PostgreSQL 版本和扩展包可用性。

`ANNUAL_MINIO_BUCKET_RAW`、`ANNUAL_MINIO_BUCKET_DERIVED`、`ANNUAL_MINIO_BUCKET_ARTIFACTS` 和 `ANNUAL_MINIO_BUCKET_TEMPLATES` 也必须预先创建。Compose 和应用运行时均不会创建这些线上桶。

运行时会将 Gotenberg 和 ClamAV 的服务地址注入容器，其余存储配置不会被 Compose 覆写。API、worker 和 beat 使用可访问外部服务的 `annual_runtime` 网络；不要将它改为内部网络。

## 启动

```powershell
# 先确认 backend/.env 已配置外置 PostgreSQL、Redis 和 MinIO
docker compose -f deploy/annual-audit/docker-compose.yml --profile runtime build

# 首次连接目标 PostgreSQL 或更新基线后，先执行幂等迁移
docker compose -f deploy/annual-audit/docker-compose.yml --profile runtime run --rm --no-deps attachment-worker python -m ai_hunter.annual_audit.storage.migrate

# 迁移和外部存储检查成功后，再启动应用运行时
docker compose -f deploy/annual-audit/docker-compose.yml --profile runtime up -d
```

`annual-api` 默认暴露 `8080`，Gotenberg 默认暴露 `63000`，ClamAV 默认暴露 `63310`。这些端口可通过 `backend/.env` 中的 `ANNUAL_BACKEND_PORT`、`ATTACHMENT_GOTENBERG_PORT` 与 `ATTACHMENT_CLAMAV_PORT` 调整。

## 运行时安全

Gotenberg 保留固定镜像、Chromium deny list、临时文件系统和最小权限设置。ClamAV 保留签名新鲜度健康检查与独立数据卷；持续不健康时检查其出网条件和容器日志，不要移除签名检查。

API 与附件 worker 健康检查会验证 PostgreSQL 迁移记录、Redis、四个线上 MinIO 桶和附件运行时。迁移成功后再提交附件任务；对象存储的数据保留与实际删除由外置 MinIO 策略和应用账本控制，Compose 不管理这些数据。

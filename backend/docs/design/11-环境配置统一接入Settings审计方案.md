# 环境配置统一接入 Settings 审计方案

## 目标

统一 `.env`、`.env.example` 与 `ai_hunter.app.settings.Settings` 的配置契约。常驻业务代码不得直接读取固定环境变量，避免配置存在但被 `SettingsConfigDict(extra="ignore")` 静默忽略。

## 审计结论

1. `DEADLINE_RED_DAYS`、`DEADLINE_YELLOW_DAYS` 已在两份 env 中声明，但 `Settings` 缺字段，`deadline_board.py` 直接使用 `os.getenv`。
2. `REPORT_SECTION_PROVIDER_1..8` 已在两份 env 中声明，但 `Settings` 缺字段，`generate_sections.py` 直接使用 `os.getenv`。
3. `kimi_endpoint_probe.py` 直接读取 `KIMI_API_KEY`，与已有 `Settings.kimi_api_key` 重复。
4. `.env` 中 6 个本地认证参数在 `.env.example` 仅以注释形式出现；Settings 的 8 个 JWT/项目权限参数也仅以注释形式出现，部署模板无法被工具识别为完整键集合。
5. `init_local_admin.py` 支持 seed 中任意 `password_env` 名称。该值是一次性 CLI 的秘密输入，不是固定应用配置，保留为唯一直接环境变量读取例外。

## 实施范围

- `Settings` 新增 deadline 阈值和 8 个报告段 provider 字段，负责默认值、归一化和合法性校验。
- `deadline_board.py`、`generate_sections.py`、`kimi_endpoint_probe.py` 改为只通过 `get_settings()` 获取固定配置。
- `.env.example` 将认证与权限配置键改为可识别的显式模板项，保持空 secret 和安全默认值。
- 增加配置键集合测试，确保 `.env.example` 中的应用配置均能映射到 `Settings`；显式白名单仅保留动态管理员密码输入。

## 验收标准

1. `ai_hunter/app` 常驻业务代码不存在固定配置的 `os.getenv/os.environ`。
2. `.env.example` 中所有非例外键均在 `Settings.model_fields` 中存在。
3. deadline/provider 配置通过 Settings 单元测试，完整 pytest 套件通过。
4. 服务重启后 OpenAPI、full-audit 报告段 provider 与时效看板行为不回归。

## 回滚点

- 代码回滚：恢复各调用点原有环境变量读取，并移除新增 Settings 字段。
- 配置回滚：`.env` 不做自动写入；`.env.example` 仅为模板，可恢复本次新增显式键。
- 本改造不执行 DDL、不删除数据库数据。

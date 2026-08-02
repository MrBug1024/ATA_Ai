-- 权限网关 v2-A · 私有化本地用户 / 公司 / 角色迁移
-- 说明：
-- 1. 本文件包含 v2-A 私有化用户管理所需 DDL 与存量 app_user 回填。
-- 2. 执行会修改真实数据库结构与部分存量数据，必须经用户授权。
-- 3. 所有新增表与新增列均带 COMMENT，满足数据库变更注释规范。
-- 4. 本阶段只覆盖 AUTH_IDENTITY_MODE=private 的身份底座；
--    case_member / thread metadata / RLS / license_state 后续单独 DDL。
-- 5. v2-A 代码实现必须同步落实以下业务约束：
--    - 私有化普通用户 / 公司管理员必须绑定非空 company_id；空字符串默认值仅保留给内部超级管理员或迁移异常排查。
--    - is_super_admin=true 的登录、授权、跨公司访问、角色/权限变更必须写 auth_audit_log。
--    - 密码复杂度、历史密码、定期更换、登录锁定等策略由应用层 user_service 实现。
--    - app_user_role.company_id 后续如需强外键，需要先处理 super_admin 空 company_id 的例外建模。
--    - RLS / 连接池上下文污染防护放到 v2-B/C，checkpointer 必须使用独立 engine 方案评审。
-- 6. 存量数据策略：
--    - 存量 app_user 统一归属公司：国金中恒企业管理(海南)有限公司。
--    - company_id 使用确定性短码：co_f1824b82e2116701。
--    - company_id 不承载展示语义；展示名称必须通过 app_company.company_name 反查。

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. 私有化公司 / 机构目录
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.app_company (
    company_id        TEXT PRIMARY KEY,
    company_name      TEXT NOT NULL DEFAULT '',
    company_name_norm TEXT NOT NULL DEFAULT '',
    company_type      TEXT NOT NULL DEFAULT 'customer',
    status            TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),
    notes             TEXT NOT NULL DEFAULT '',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.app_company IS
'私有化模式公司/机构目录；AUTH_IDENTITY_MODE=private 时作为用户 company_id 和租户隔离来源。';
COMMENT ON COLUMN public.app_company.company_id IS '公司/机构唯一标识；使用稳定短码，不承载展示语义，展示名称通过 company_name 反查。';
COMMENT ON COLUMN public.app_company.company_name IS '公司/机构展示名称；当前存量公司为国金中恒企业管理(海南)有限公司。';
COMMENT ON COLUMN public.app_company.company_name_norm IS '标准化后的公司/机构名称，用于唯一约束；建议由应用层按统一规则生成。';
COMMENT ON COLUMN public.app_company.company_type IS '公司/机构类型；默认 customer，后续可扩展 internal、partner 等。';
COMMENT ON COLUMN public.app_company.status IS '公司/机构状态：active=启用，disabled=停用。';
COMMENT ON COLUMN public.app_company.notes IS '公司/机构备注。';
COMMENT ON COLUMN public.app_company.created_at IS '公司/机构记录创建时间。';
COMMENT ON COLUMN public.app_company.updated_at IS '公司/机构记录最近更新时间。';

CREATE UNIQUE INDEX IF NOT EXISTS ux_app_company_company_name_norm
    ON public.app_company(company_name_norm);

INSERT INTO public.app_company (
    company_id,
    company_name,
    company_name_norm,
    company_type,
    status,
    notes
) VALUES (
    'co_f1824b82e2116701',
    '国金中恒企业管理(海南)有限公司',
    '国金中恒企业管理(海南)有限公司',
    'customer',
    'active',
    'v2-A 存量数据默认归属公司；company_id 由公司标准名 sha256 前 16 位生成。'
)
ON CONFLICT (company_id) DO UPDATE SET
    company_name = EXCLUDED.company_name,
    company_name_norm = EXCLUDED.company_name_norm,
    company_type = EXCLUDED.company_type,
    status = EXCLUDED.status,
    notes = EXCLUDED.notes,
    updated_at = now();

-- 1.1 角色目录兼容升级：role_code 改为英文稳定码，中文展示名放 role_name
ALTER TABLE public.app_role_permission
    ADD COLUMN IF NOT EXISTS role_name TEXT NOT NULL DEFAULT '';

COMMENT ON COLUMN public.app_role_permission.role_code IS
'英文稳定角色码，只允许小写字母、数字、下划线，且必须以字母开头；中文名称放 role_name。';
COMMENT ON COLUMN public.app_role_permission.role_name IS
'角色展示名，可为中文；不得用于权限判断。英文 role_code 约束由 auth_tables.sql 或 auth_role_code_standardization.sql 添加。';


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. 扩展 app_user：从“用户投影”升级为“本地用户主档 + 外部身份投影”
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE public.app_user
    ADD COLUMN IF NOT EXISTS company_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS auth_source TEXT NOT NULL DEFAULT 'local'
        CHECK (auth_source IN ('local', 'platform', 'sso')),
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled', 'locked')),
    ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;

COMMENT ON TABLE public.app_user IS
'v2 用户主档/外部身份投影；私有化模式保存本地用户主档，平台模式保存用户中心投影，company_id 用于租户隔离。';
COMMENT ON COLUMN public.app_user.company_id IS
'用户所属公司/机构 id；私有化模式来自 app_company，平台模式来自用户中心 company claim；存量用户统一回填为 co_f1824b82e2116701，私有化非超级管理员必须由应用层校验为非空。';
COMMENT ON COLUMN public.app_user.auth_source IS
'用户身份来源：local=本项目本地用户，platform=平台用户中心，sso=客户自有 SSO 映射。';
COMMENT ON COLUMN public.app_user.status IS
'用户状态：active=启用，disabled=禁用，locked=锁定。';
COMMENT ON COLUMN public.app_user.is_super_admin IS
'是否内部超级管理员；true 时可跨公司，所有登录、授权、跨公司访问、角色/权限变更必须写 auth_audit_log。';
COMMENT ON COLUMN public.app_user.last_login_at IS
'用户最近一次成功登录时间。';

CREATE INDEX IF NOT EXISTS idx_app_user_company_id ON public.app_user(company_id);
CREATE INDEX IF NOT EXISTS idx_app_user_status ON public.app_user(status);

UPDATE public.app_user
SET company_id = 'co_f1824b82e2116701',
    updated_at = now()
WHERE company_id = '';


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. 私有化本地登录凭证
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.local_user_credential (
    user_id               TEXT PRIMARY KEY REFERENCES public.app_user(user_id) ON DELETE CASCADE,
    login_identifier      TEXT NOT NULL,
    login_identifier_norm TEXT NOT NULL,
    password_hash         TEXT NOT NULL DEFAULT '',
    password_algo         TEXT NOT NULL DEFAULT 'argon2id',
    password_updated_at   TIMESTAMPTZ,
    failed_login_count    INT NOT NULL DEFAULT 0,
    locked_until          TIMESTAMPTZ,
    mfa_enabled           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (login_identifier_norm)
);

COMMENT ON TABLE public.local_user_credential IS
'私有化模式本地登录凭证；只保存密码哈希和登录状态，不保存明文密码；密码复杂度、历史密码、定期更换等策略由应用层实现。';
COMMENT ON COLUMN public.local_user_credential.user_id IS '关联 app_user.user_id 的用户标识。';
COMMENT ON COLUMN public.local_user_credential.login_identifier IS '登录标识原文；可为用户名、手机号或邮箱，具体口径待业务确认。';
COMMENT ON COLUMN public.local_user_credential.login_identifier_norm IS '标准化后的登录标识，用于唯一约束和登录查询。';
COMMENT ON COLUMN public.local_user_credential.password_hash IS '密码哈希；不得保存明文密码。';
COMMENT ON COLUMN public.local_user_credential.password_algo IS '密码哈希算法标识；默认 argon2id，若依赖未安装可评审后改 bcrypt/pbkdf2。';
COMMENT ON COLUMN public.local_user_credential.password_updated_at IS '密码最近更新时间。';
COMMENT ON COLUMN public.local_user_credential.failed_login_count IS '连续失败登录次数，用于锁定策略。';
COMMENT ON COLUMN public.local_user_credential.locked_until IS '账号锁定截止时间；为空表示未锁定。';
COMMENT ON COLUMN public.local_user_credential.mfa_enabled IS '是否启用多因素认证；当前预留。';
COMMENT ON COLUMN public.local_user_credential.created_at IS '凭证记录创建时间。';
COMMENT ON COLUMN public.local_user_credential.updated_at IS '凭证记录最近更新时间。';

CREATE INDEX IF NOT EXISTS idx_local_user_credential_login_norm
    ON public.local_user_credential(login_identifier_norm);


-- ─────────────────────────────────────────────────────────────────────────────
-- 4. 用户 → 本项目角色
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.app_user_role (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES public.app_user(user_id) ON DELETE CASCADE,
    company_id  TEXT NOT NULL DEFAULT '',
    role_code   TEXT NOT NULL REFERENCES public.app_role_permission(role_code) ON DELETE RESTRICT,
    assigned_by TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id, user_id, role_code)
);

COMMENT ON TABLE public.app_user_role IS
'用户到本项目角色的多对多关系；v2 后 Identity.roles 从本表加载，不再信任 JWT roles。';
COMMENT ON COLUMN public.app_user_role.id IS '用户角色关系主键。';
COMMENT ON COLUMN public.app_user_role.user_id IS '用户 id，关联 app_user.user_id。';
COMMENT ON COLUMN public.app_user_role.company_id IS
'角色归属公司/机构 id；普通角色必须绑定公司；后续可在存量数据策略确认后增加 REFERENCES app_company(company_id)。';
COMMENT ON COLUMN public.app_user_role.role_code IS '本项目英文稳定角色码，关联 app_role_permission.role_code；中文展示名来自 app_role_permission.role_name。';
COMMENT ON COLUMN public.app_user_role.assigned_by IS '分配该角色的操作人 user_id。';
COMMENT ON COLUMN public.app_user_role.created_at IS '用户角色关系创建时间。';
COMMENT ON COLUMN public.app_user_role.updated_at IS '用户角色关系最近更新时间。';

CREATE INDEX IF NOT EXISTS idx_app_user_role_user ON public.app_user_role(user_id);
CREATE INDEX IF NOT EXISTS idx_app_user_role_company ON public.app_user_role(company_id);
CREATE INDEX IF NOT EXISTS idx_app_user_role_role ON public.app_user_role(role_code);


-- 角色权限初始化数据统一维护在 config/auth_private_seed.json，并通过
-- python3 -m ai_hunter.app.scripts.init_local_admin 写入，避免 SQL 与 seed 双处维护冲突。

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. 权限 / 登录审计日志
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.auth_audit_log (
    id          BIGSERIAL PRIMARY KEY,
    event_type  TEXT NOT NULL,
    actor_id    TEXT NOT NULL DEFAULT '',
    company_id  TEXT NOT NULL DEFAULT '',
    target_type TEXT NOT NULL DEFAULT '',
    target_id   TEXT NOT NULL DEFAULT '',
    action      TEXT NOT NULL DEFAULT '',
    decision    TEXT NOT NULL DEFAULT '',
    request_id  TEXT NOT NULL DEFAULT '',
    ip_address  TEXT NOT NULL DEFAULT '',
    user_agent  TEXT NOT NULL DEFAULT '',
    detail      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.auth_audit_log IS
'权限网关审计日志；记录登录、角色变更、权限变更、越权拒绝、license 变更等安全事件。';
COMMENT ON COLUMN public.auth_audit_log.id IS '审计日志主键。';
COMMENT ON COLUMN public.auth_audit_log.event_type IS '事件类型，如 login_success/login_failed/role_changed/access_denied/license_changed。';
COMMENT ON COLUMN public.auth_audit_log.actor_id IS '触发事件的用户 id；系统事件可为空字符串。';
COMMENT ON COLUMN public.auth_audit_log.company_id IS '事件所属公司/机构 id。';
COMMENT ON COLUMN public.auth_audit_log.target_type IS '被操作对象类型，如 user/role/case/thread/license。';
COMMENT ON COLUMN public.auth_audit_log.target_id IS '被操作对象 id。';
COMMENT ON COLUMN public.auth_audit_log.action IS '动作名称，如 create/update/delete/login/access。';
COMMENT ON COLUMN public.auth_audit_log.decision IS '处理结果，如 allow/deny/success/failed。';
COMMENT ON COLUMN public.auth_audit_log.request_id IS '请求 id，用于串联应用日志。';
COMMENT ON COLUMN public.auth_audit_log.ip_address IS '客户端 IP；按部署代理链路取可信值。';
COMMENT ON COLUMN public.auth_audit_log.user_agent IS '客户端 User-Agent 摘要。';
COMMENT ON COLUMN public.auth_audit_log.detail IS '事件详情 JSON；不得写入密码、token、报告正文等敏感明文。';
COMMENT ON COLUMN public.auth_audit_log.created_at IS '审计事件发生时间。';

CREATE INDEX IF NOT EXISTS idx_auth_audit_log_actor ON public.auth_audit_log(actor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_audit_log_company ON public.auth_audit_log(company_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_audit_log_event ON public.auth_audit_log(event_type, created_at DESC);

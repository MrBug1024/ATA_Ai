-- 审计报告段落权限矩阵
-- 说明：
-- 1. 本文件新增报告段落目录与角色-段落授权关系。
-- 2. 执行会修改真实数据库结构，必须经用户授权。
-- 3. 所有新增表与字段均带 COMMENT，满足数据库变更注释规范。
-- 4. 初始化数据统一维护在 config/auth_private_seed.json，并通过
--    python3 -m ai_hunter.app.scripts.init_local_admin 写入，避免 SQL 与 seed 双处维护冲突。

CREATE TABLE IF NOT EXISTS public.app_report_section (
    section_code TEXT PRIMARY KEY,
    section_id   TEXT NOT NULL,
    title        TEXT NOT NULL DEFAULT '',
    audience     TEXT NOT NULL DEFAULT 'field'
        CHECK (audience IN ('field','expert','management')),
    sort_order   INT NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','disabled')),
    description  TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (section_id)
);

COMMENT ON TABLE public.app_report_section IS
'审计报告段落目录；section_code 是稳定业务码，section_id 兼容现有 1-8 段头，供前端配置和后端过滤使用。';
COMMENT ON COLUMN public.app_report_section.section_code IS
'审计报告段落稳定业务码；用于权限配置、接口返回和审计追溯，不使用纯数字作为权限主键。';
COMMENT ON COLUMN public.app_report_section.section_id IS
'现有报告段落编号，兼容 final_report 中的 1-8 段头和 SSE section_id。';
COMMENT ON COLUMN public.app_report_section.title IS
'审计报告段落展示标题，供前端配置页面和权限审计展示。';
COMMENT ON COLUMN public.app_report_section.audience IS
'兼容旧版 field/expert/management 分层；新权限以 section_code 精确授权为准。';
COMMENT ON COLUMN public.app_report_section.sort_order IS
'段落展示顺序；通常与 section_id 数字顺序一致。';
COMMENT ON COLUMN public.app_report_section.status IS
'段落状态：active=启用，disabled=停用。停用段不应出现在前端可配置列表。';
COMMENT ON COLUMN public.app_report_section.description IS
'段落业务说明。';
COMMENT ON COLUMN public.app_report_section.created_at IS '段落目录记录创建时间。';
COMMENT ON COLUMN public.app_report_section.updated_at IS '段落目录记录最近更新时间。';

CREATE INDEX IF NOT EXISTS idx_app_report_section_status_order
    ON public.app_report_section(status, sort_order);

CREATE TABLE IF NOT EXISTS public.app_role_report_section (
    id           BIGSERIAL PRIMARY KEY,
    role_code    TEXT NOT NULL REFERENCES public.app_role_permission(role_code) ON DELETE CASCADE,
    section_code TEXT NOT NULL REFERENCES public.app_report_section(section_code) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (role_code, section_code)
);

COMMENT ON TABLE public.app_role_report_section IS
'角色到审计报告段落的授权关系；用于实现不同角色看到不同报告段落，前端权限配置页面可维护。';
COMMENT ON COLUMN public.app_role_report_section.id IS '角色段落授权关系主键。';
COMMENT ON COLUMN public.app_role_report_section.role_code IS
'本项目英文稳定角色码，关联 app_role_permission.role_code。';
COMMENT ON COLUMN public.app_role_report_section.section_code IS
'审计报告段落稳定业务码，关联 app_report_section.section_code。';
COMMENT ON COLUMN public.app_role_report_section.created_at IS '角色段落授权关系创建时间。';
COMMENT ON COLUMN public.app_role_report_section.updated_at IS '角色段落授权关系最近更新时间。';

CREATE INDEX IF NOT EXISTS idx_app_role_report_section_role
    ON public.app_role_report_section(role_code);
CREATE INDEX IF NOT EXISTS idx_app_role_report_section_section
    ON public.app_role_report_section(section_code);

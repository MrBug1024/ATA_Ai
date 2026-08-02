-- 权限网关 · 人员标签体系（Tier 3）
-- 标签归不良资产本地（用户中心未上线前在本项目维护；上线后改从用户中心同步，表结构不变）。
-- 认证走用户中心 JWT，本表只存「用户投影 + 五维人员画像标签」，用于分权与人岗匹配。

-- 用户投影（user_id 来自用户中心 JWT 的 sub）
CREATE TABLE IF NOT EXISTS public.app_user (
    user_id     TEXT PRIMARY KEY,
    username    TEXT NOT NULL DEFAULT '',
    company     TEXT NOT NULL DEFAULT '',          -- 所属公司名（五维之一，单值放主表）
    region      TEXT NOT NULL DEFAULT '',          -- 常住地域 省-市-县（区）
    note        TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.app_user IS '用户投影（身份来自用户中心 JWT）；company/region 为单值人员画像维度。';

-- 多选标签（项目角色 / 专业职称 / 专业专长）：一用户一维度多值 → 多行
CREATE TABLE IF NOT EXISTS public.app_user_tag (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES public.app_user(user_id) ON DELETE CASCADE,
    dimension   TEXT NOT NULL,                     -- project_role / title / expertise
    tag_value   TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, dimension, tag_value)
);
COMMENT ON TABLE public.app_user_tag IS '用户多选标签（项目角色/专业职称/专业专长）。';
COMMENT ON COLUMN public.app_user_tag.id IS '用户标签关系主键。';
COMMENT ON COLUMN public.app_user_tag.user_id IS '用户 id，关联 app_user.user_id。';
COMMENT ON COLUMN public.app_user_tag.dimension IS '标签维度：project_role=项目角色，title=专业职称，expertise=专业专长。';
COMMENT ON COLUMN public.app_user_tag.tag_value IS '标签值；应来自 app_tag_catalog 对应 dimension 的 tag_value。';
COMMENT ON COLUMN public.app_user_tag.created_at IS '用户标签关系创建时间。';
CREATE INDEX IF NOT EXISTS idx_app_user_tag_user ON public.app_user_tag(user_id);

-- 角色 → 权限映射（前端/运营可配；授权层 DB 优先读取，回退 env/代码默认）
CREATE TABLE IF NOT EXISTS public.app_role_permission (
    role_code   TEXT PRIMARY KEY,                  -- 英文稳定角色码
    role_name   TEXT NOT NULL DEFAULT '',          -- 中文展示名
    tier        TEXT NOT NULL DEFAULT 'field'      -- 最高可见报告段落层级
        CHECK (tier IN ('field','expert','management')),
    modules     JSONB NOT NULL DEFAULT '[]'::jsonb,-- 可访问模块码数组；["*"]=全部
    description TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_app_role_permission_role_code_ascii
        CHECK (role_code ~ '^[a-z][a-z0-9_]*$')
);
COMMENT ON TABLE public.app_role_permission IS
'角色→权限映射（本项目自管，前端可配）：tier=可见报告段落层级，modules=可访问模块(["*"]=全部)。';
COMMENT ON COLUMN public.app_role_permission.role_code IS
'英文稳定角色码，只允许小写字母、数字、下划线，且必须以字母开头；中文名称放 role_name。';
COMMENT ON COLUMN public.app_role_permission.role_name IS
'角色展示名，可为中文；不得用于权限判断。';
COMMENT ON COLUMN public.app_role_permission.modules IS
'模块码数组：report/drilldown/review/progress/corrections/deadline/graph/admin；["*"]=全部。';

-- 标签目录（预设可选项，供前端下拉；expertise 带分组）
CREATE TABLE IF NOT EXISTS public.app_tag_catalog (
    id          BIGSERIAL PRIMARY KEY,
    dimension   TEXT NOT NULL,                     -- project_role / title / expertise
    tag_value   TEXT NOT NULL,
    tag_group   TEXT NOT NULL DEFAULT '',          -- expertise 分组：通用综合/法律司法/风控侦查
    sort_order  INT NOT NULL DEFAULT 0,
    UNIQUE (dimension, tag_value)
);
COMMENT ON TABLE public.app_tag_catalog IS '人员标签预设目录（项目角色/专业职称/专业专长，expertise 带分组）。';
COMMENT ON COLUMN public.app_tag_catalog.id IS '标签目录主键。';
COMMENT ON COLUMN public.app_tag_catalog.dimension IS '标签维度：project_role=项目角色，title=专业职称，expertise=专业专长。';
COMMENT ON COLUMN public.app_tag_catalog.tag_value IS '标签展示值。';
COMMENT ON COLUMN public.app_tag_catalog.tag_group IS '标签分组；当前主要用于 expertise 维度。';
COMMENT ON COLUMN public.app_tag_catalog.sort_order IS '同一维度内的排序值，数值越小越靠前。';

-- 初始化数据统一维护在 config/auth_private_seed.json，并通过
-- python3 -m ai_hunter.app.scripts.init_local_admin 写入，避免 SQL 与 seed 双处维护冲突。

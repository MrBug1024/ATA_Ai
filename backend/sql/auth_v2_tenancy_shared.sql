-- ============================================================================
-- 权限网关 v2-B：案件与会话租户隔离共享契约
-- ============================================================================
--
-- 说明：
-- - 本脚本是 ai_hunter 与上游 NpaDemo 共用真实数据库的共享 DDL。
-- - 已获授权并在共享真实库执行；保留 IF NOT EXISTS 以支持部署环境幂等初始化。
-- - 执行真实库前必须单独获得数据库修改授权。
-- - 存量默认公司：
--   company_name = 国金中恒企业管理(海南)有限公司
--   company_id   = co_f1824b82e2116701
--
-- 设计边界：
-- - public.cases 是案件主数据与案件租户隔离的权威来源。
-- - public.case_member 是案件成员关系的权威来源。
-- - public.thread_metadata 是 LangGraph 会话权限入口。
-- - case_member.company_id 与 cases.company_id 的一致性先由应用层校验；
--   后续如启用触发器 / RLS，再单独评审。
-- ============================================================================

ALTER TABLE public.cases
    ADD COLUMN IF NOT EXISTS company_id TEXT NOT NULL DEFAULT 'co_f1824b82e2116701';

ALTER TABLE public.cases
    ADD COLUMN IF NOT EXISTS owner_id TEXT NOT NULL DEFAULT '';

ALTER TABLE public.cases
    ADD COLUMN IF NOT EXISTS created_by TEXT NOT NULL DEFAULT '';

COMMENT ON COLUMN public.cases.company_id IS '案件所属公司/机构ID，用于多租户公司硬隔离；存量数据默认归属国金中恒企业管理(海南)有限公司。';
COMMENT ON COLUMN public.cases.owner_id IS '案件负责人/owner的用户ID；普通用户可访问自己负责的案件。存量无法反推时为空字符串，仅公司管理员/全局超管可见。';
COMMENT ON COLUMN public.cases.created_by IS '案件创建人用户ID；可与owner_id不同。存量无法反推时为空字符串。';

CREATE INDEX IF NOT EXISTS idx_cases_company_id
    ON public.cases(company_id);

CREATE INDEX IF NOT EXISTS idx_cases_company_owner
    ON public.cases(company_id, owner_id);

CREATE TABLE IF NOT EXISTS public.case_member (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL REFERENCES public.cases(case_id) ON DELETE CASCADE,
    company_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    member_role TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    added_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_case_member_case_user UNIQUE (case_id, user_id)
);

COMMENT ON TABLE public.case_member IS '案件成员关系表：记录用户参与的案件，用于普通成员按owner/member访问案件。';
COMMENT ON COLUMN public.case_member.id IS '案件成员关系自增主键。';
COMMENT ON COLUMN public.case_member.case_id IS '案件ID，关联public.cases(case_id)。';
COMMENT ON COLUMN public.case_member.company_id IS '成员关系所属公司/机构ID，必须与对应cases.company_id一致；当前由应用层校验。';
COMMENT ON COLUMN public.case_member.user_id IS '案件成员用户ID。';
COMMENT ON COLUMN public.case_member.member_role IS '案件内角色编码或描述；可为空字符串，必要时复用项目角色编码。';
COMMENT ON COLUMN public.case_member.status IS '成员状态：active=有效，disabled=禁用。';
COMMENT ON COLUMN public.case_member.added_by IS '添加该成员的操作人用户ID。';
COMMENT ON COLUMN public.case_member.created_at IS '成员关系创建时间。';
COMMENT ON COLUMN public.case_member.updated_at IS '成员关系最近更新时间。';

CREATE INDEX IF NOT EXISTS idx_case_member_company_user
    ON public.case_member(company_id, user_id);

CREATE INDEX IF NOT EXISTS idx_case_member_case_status
    ON public.case_member(case_id, status);

CREATE TABLE IF NOT EXISTS public.thread_metadata (
    thread_id TEXT PRIMARY KEY,
    case_id BIGINT REFERENCES public.cases(case_id),
    company_id TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    last_intent TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT chk_thread_metadata_case_id_positive CHECK (case_id IS NULL OR case_id > 0)
);

COMMENT ON TABLE public.thread_metadata IS 'LangGraph会话元信息表：作为读取checkpointer和conversation_messages前的权限入口。';
COMMENT ON COLUMN public.thread_metadata.thread_id IS 'LangGraph thread_id，会话唯一标识。';
COMMENT ON COLUMN public.thread_metadata.case_id IS '会话绑定的案件ID；无案件会话为NULL，是否允许无案件会话由应用层策略控制。';
COMMENT ON COLUMN public.thread_metadata.company_id IS '会话所属公司/机构ID，用于公司硬隔离。';
COMMENT ON COLUMN public.thread_metadata.created_by IS '会话创建人用户ID；存量无法反推时为空字符串。';
COMMENT ON COLUMN public.thread_metadata.last_intent IS '最近一次识别到的业务意图，用于列表展示和排查。';
COMMENT ON COLUMN public.thread_metadata.title IS '会话标题缓存，用于列表展示。';
COMMENT ON COLUMN public.thread_metadata.status IS '会话状态：active=有效，deleted=软删除。';
COMMENT ON COLUMN public.thread_metadata.created_at IS '会话创建时间。';
COMMENT ON COLUMN public.thread_metadata.updated_at IS '会话最近更新时间。';
COMMENT ON COLUMN public.thread_metadata.deleted_at IS '会话软删除时间；未删除时为NULL。';

CREATE INDEX IF NOT EXISTS idx_thread_metadata_company_created
    ON public.thread_metadata(company_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_thread_metadata_company_user
    ON public.thread_metadata(company_id, created_by);

CREATE INDEX IF NOT EXISTS idx_thread_metadata_case
    ON public.thread_metadata(case_id);

-- ============================================================================
-- 案件参与方角色模型：债务人 / 资产购买方 / 债权人 / 保证人 / 管理人等
-- ============================================================================
--
-- 权威边界：
-- - public.debtors 继续作为债务人专项画像及现有 debtor_id 外键的权威来源。
-- - public.case_party 作为案件参与方角色索引；debtor 角色必须关联 debtors。
-- - 本脚本只从 debtors 回填确定角色，不从卷宗或债权 JSON 猜测其他参与方。
-- - 执行真实库前必须单独获得数据库修改授权。
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.case_party (
    party_id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL REFERENCES public.cases(case_id) ON DELETE CASCADE,
    debtor_id BIGINT REFERENCES public.debtors(debtor_id) ON DELETE CASCADE,
    party_name TEXT NOT NULL,
    party_role TEXT NOT NULL CHECK (
        party_role IN (
            'debtor',
            'asset_purchaser',
            'creditor',
            'guarantor',
            'administrator',
            'other'
        )
    ),
    uscc VARCHAR(32),
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    source_type TEXT NOT NULL DEFAULT 'manual',
    extra_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_case_party_case_name_role UNIQUE (case_id, party_name, party_role),
    CONSTRAINT chk_case_party_debtor_link CHECK (
        (party_role = 'debtor' AND debtor_id IS NOT NULL)
        OR (party_role <> 'debtor' AND debtor_id IS NULL)
    )
);

COMMENT ON TABLE public.case_party IS '案件参与方角色表：统一记录债务人、资产购买方、债权人、保证人、管理人等案件角色。';
COMMENT ON COLUMN public.case_party.party_id IS '案件参与方记录自增主键。';
COMMENT ON COLUMN public.case_party.case_id IS '所属案件ID，关联public.cases(case_id)。';
COMMENT ON COLUMN public.case_party.debtor_id IS '债务人专项记录ID；仅debtor角色允许使用，并关联public.debtors(debtor_id)。';
COMMENT ON COLUMN public.case_party.party_name IS '参与方名称；债务人名称读取仍以public.debtors.entity_name为权威。';
COMMENT ON COLUMN public.case_party.party_role IS '参与方角色编码：debtor/asset_purchaser/creditor/guarantor/administrator/other。';
COMMENT ON COLUMN public.case_party.uscc IS '参与方统一社会信用代码；未知时为空。';
COMMENT ON COLUMN public.case_party.is_primary IS '是否为该案件同角色下的主要参与方。';
COMMENT ON COLUMN public.case_party.status IS '参与方状态：active=有效，disabled=软禁用。';
COMMENT ON COLUMN public.case_party.source_type IS '角色来源，如case_creation/manual/migration；不得用作核心角色判断。';
COMMENT ON COLUMN public.case_party.extra_fields IS '参与方角色扩展信息；核心名称和角色不得只存于此字段。';
COMMENT ON COLUMN public.case_party.created_by IS '创建或登记该参与方的用户ID；迁移数据可为空字符串。';
COMMENT ON COLUMN public.case_party.created_at IS '参与方记录创建时间。';
COMMENT ON COLUMN public.case_party.updated_at IS '参与方记录最近更新时间。';

CREATE UNIQUE INDEX IF NOT EXISTS uq_case_party_debtor_id
    ON public.case_party(debtor_id)
    WHERE debtor_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_case_party_case_role_status
    ON public.case_party(case_id, party_role, status);

CREATE INDEX IF NOT EXISTS idx_case_party_case_name
    ON public.case_party(case_id, party_name);

INSERT INTO public.case_party (
    case_id,
    debtor_id,
    party_name,
    party_role,
    uscc,
    is_primary,
    status,
    source_type
)
SELECT
    d.case_id,
    d.debtor_id,
    d.entity_name,
    'debtor',
    d.uscc,
    TRUE,
    'active',
    'migration'
FROM public.debtors d
WHERE NULLIF(BTRIM(d.entity_name), '') IS NOT NULL
ON CONFLICT (debtor_id) WHERE debtor_id IS NOT NULL
DO UPDATE SET
    case_id = EXCLUDED.case_id,
    party_name = EXCLUDED.party_name,
    uscc = COALESCE(EXCLUDED.uscc, public.case_party.uscc),
    status = 'active',
    updated_at = now();

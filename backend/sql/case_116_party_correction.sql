-- ============================================================================
-- 案件 116 角色主数据修正
-- 执行顺序：先执行 case_party.sql，再执行本脚本。
-- ============================================================================
--
-- 业务确认：
-- - 债务人：钟山区老鹰山镇晨光煤矿（保留 debtor_id=76）。
-- - 资产购买方：中国中信金融资产管理股份有限公司。
-- - 不修改卷宗原文、债权人 JSON、历史会话和 API 审计日志。
-- ============================================================================

BEGIN;

UPDATE public.debtors
SET entity_name = '钟山区老鹰山镇晨光煤矿',
    updated_at = now()
WHERE debtor_id = 76
  AND case_id = 116
  AND entity_name = '中国中信金融资产管理股份有限公司';

UPDATE public.cases
SET case_name = '钟山区老鹰山镇晨光煤矿 — 自动采集',
    updated_at = now()
WHERE case_id = 116
  AND case_name = '中国中信金融资产管理股份有限公司 — 自动采集';

UPDATE public.data_source_checklist
SET target_name = '钟山区老鹰山镇晨光煤矿',
    updated_at = now()
WHERE case_id = 116
  AND target_type = '债务人'
  AND target_name = '中国中信金融资产管理股份有限公司';

UPDATE public.related_persons
SET related_to = '钟山区老鹰山镇晨光煤矿'
WHERE case_id = 116
  AND related_to = '中国中信金融资产管理股份有限公司';

DELETE FROM public.engine_results_cache
WHERE case_id = 116;

INSERT INTO public.case_party (
    case_id,
    party_name,
    party_role,
    is_primary,
    status,
    source_type,
    created_by
)
SELECT
    c.case_id,
    '中国中信金融资产管理股份有限公司',
    'asset_purchaser',
    TRUE,
    'active',
    'manual',
    COALESCE(c.owner_id, '')
FROM public.cases c
WHERE c.case_id = 116
ON CONFLICT (case_id, party_name, party_role)
DO UPDATE SET
    is_primary = TRUE,
    status = 'active',
    source_type = 'manual',
    created_by = CASE
        WHEN EXCLUDED.created_by <> '' THEN EXCLUDED.created_by
        ELSE public.case_party.created_by
    END,
    updated_at = now();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.debtors
        WHERE case_id = 116
          AND debtor_id = 76
          AND entity_name = '钟山区老鹰山镇晨光煤矿'
    ) THEN
        RAISE EXCEPTION '案件116债务人主数据校验失败';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.case_party
        WHERE case_id = 116
          AND debtor_id = 76
          AND party_name = '钟山区老鹰山镇晨光煤矿'
          AND party_role = 'debtor'
          AND status = 'active'
    ) THEN
        RAISE EXCEPTION '案件116 debtor参与方校验失败';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.case_party
        WHERE case_id = 116
          AND debtor_id IS NULL
          AND party_name = '中国中信金融资产管理股份有限公司'
          AND party_role = 'asset_purchaser'
          AND status = 'active'
    ) THEN
        RAISE EXCEPTION '案件116 asset_purchaser参与方校验失败';
    END IF;
END
$$;

COMMIT;

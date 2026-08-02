-- ============================================================================
-- P0 多债务人解析验收夹具
-- ============================================================================
--
-- 目的：为真实 HTTP 验收提供一个稳定的双债务人案件，不依赖 OCR 或卷宗数据。
-- 边界：只新增/维护明确标记的测试案件、两个债务人和对应 debtor 参与方；不删除数据。
-- 重放：通过 cases.notes.fixture 定位同一案件，重复执行不会创建第二套夹具。
-- ============================================================================

BEGIN;

DO $fixture$
DECLARE
    v_case_id BIGINT;
    v_debtor_a_id BIGINT;
    v_debtor_b_id BIGINT;
BEGIN
    SELECT case_id
    INTO v_case_id
    FROM public.cases
    WHERE company_id = 'co_f1824b82e2116701'
      AND notes ->> 'fixture' = 'p0_multi_debtor_resolution'
    ORDER BY case_id
    LIMIT 1;

    IF v_case_id IS NULL THEN
        INSERT INTO public.cases (
            case_name,
            case_type,
            status,
            notes,
            company_id,
            owner_id,
            created_by
        ) VALUES (
            'P0多债务人解析验收案件',
            '单户',
            '进行中',
            jsonb_build_object(
                'fixture', 'p0_multi_debtor_resolution',
                'purpose', '验证多债务人案件必须显式选择debtor_id',
                'managed_by', 'ai_hunter'
            ),
            'co_f1824b82e2116701',
            'default_company_admin',
            'default_company_admin'
        )
        RETURNING case_id INTO v_case_id;
    ELSE
        UPDATE public.cases
        SET case_name = 'P0多债务人解析验收案件',
            case_type = '单户',
            status = '进行中',
            notes = COALESCE(notes, '{}'::jsonb) || jsonb_build_object(
                'fixture', 'p0_multi_debtor_resolution',
                'purpose', '验证多债务人案件必须显式选择debtor_id',
                'managed_by', 'ai_hunter'
            ),
            company_id = 'co_f1824b82e2116701',
            owner_id = 'default_company_admin',
            created_by = 'default_company_admin',
            updated_at = now()
        WHERE case_id = v_case_id;
    END IF;

    SELECT MIN(debtor_id)
    INTO v_debtor_a_id
    FROM public.debtors
    WHERE case_id = v_case_id
      AND entity_name = 'P0测试债务人甲有限公司';

    IF v_debtor_a_id IS NULL THEN
        INSERT INTO public.debtors (
            case_id,
            entity_name,
            operating_status,
            data_source,
            raw_api_response
        ) VALUES (
            v_case_id,
            'P0测试债务人甲有限公司',
            '测试',
            'p0_multi_debtor_fixture',
            jsonb_build_object('fixture', 'p0_multi_debtor_resolution')
        )
        RETURNING debtor_id INTO v_debtor_a_id;
    END IF;

    SELECT MIN(debtor_id)
    INTO v_debtor_b_id
    FROM public.debtors
    WHERE case_id = v_case_id
      AND entity_name = 'P0测试债务人乙有限公司';

    IF v_debtor_b_id IS NULL THEN
        INSERT INTO public.debtors (
            case_id,
            entity_name,
            operating_status,
            data_source,
            raw_api_response
        ) VALUES (
            v_case_id,
            'P0测试债务人乙有限公司',
            '测试',
            'p0_multi_debtor_fixture',
            jsonb_build_object('fixture', 'p0_multi_debtor_resolution')
        )
        RETURNING debtor_id INTO v_debtor_b_id;
    END IF;

    INSERT INTO public.case_party (
        case_id,
        debtor_id,
        party_name,
        party_role,
        is_primary,
        status,
        source_type,
        extra_fields,
        created_by
    ) VALUES
        (
            v_case_id,
            v_debtor_a_id,
            'P0测试债务人甲有限公司',
            'debtor',
            TRUE,
            'active',
            'test_fixture',
            jsonb_build_object('fixture', 'p0_multi_debtor_resolution'),
            'default_company_admin'
        ),
        (
            v_case_id,
            v_debtor_b_id,
            'P0测试债务人乙有限公司',
            'debtor',
            FALSE,
            'active',
            'test_fixture',
            jsonb_build_object('fixture', 'p0_multi_debtor_resolution'),
            'default_company_admin'
        )
    ON CONFLICT (debtor_id) WHERE debtor_id IS NOT NULL
    DO UPDATE SET
        case_id = EXCLUDED.case_id,
        party_name = EXCLUDED.party_name,
        party_role = 'debtor',
        is_primary = EXCLUDED.is_primary,
        status = 'active',
        source_type = 'test_fixture',
        extra_fields = public.case_party.extra_fields || EXCLUDED.extra_fields,
        created_by = 'default_company_admin',
        updated_at = now();

    IF (SELECT COUNT(*) FROM public.debtors WHERE case_id = v_case_id) <> 2 THEN
        RAISE EXCEPTION 'P0多债务人夹具校验失败：案件债务人数量不是2';
    END IF;

    IF (
        SELECT COUNT(*)
        FROM public.case_party
        WHERE case_id = v_case_id
          AND debtor_id IN (v_debtor_a_id, v_debtor_b_id)
          AND party_role = 'debtor'
          AND status = 'active'
    ) <> 2 THEN
        RAISE EXCEPTION 'P0多债务人夹具校验失败：有效debtor参与方数量不是2';
    END IF;
END
$fixture$;

SELECT
    c.case_id,
    c.case_name,
    c.company_id,
    c.owner_id,
    d.debtor_id,
    d.entity_name,
    p.party_id,
    p.party_role,
    p.is_primary,
    p.status
FROM public.cases c
JOIN public.debtors d ON d.case_id = c.case_id
JOIN public.case_party p ON p.debtor_id = d.debtor_id
WHERE c.notes ->> 'fixture' = 'p0_multi_debtor_resolution'
ORDER BY d.debtor_id;

COMMIT;

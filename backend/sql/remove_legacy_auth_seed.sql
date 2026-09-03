-- A clean annual-audit deployment must not inherit the v2-A migration's
-- historic tenant record. Leave an existing deployment untouched whenever any
-- public table still references it, or an operator has renamed the record.
DO $$
DECLARE
    legacy_company_id CONSTANT TEXT := 'co_f1824b82e2116701';
    referenced_table RECORD;
    has_reference BOOLEAN := FALSE;
BEGIN
    FOR referenced_table IN
        SELECT table_schema, table_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND column_name = 'company_id'
          AND table_name <> 'app_company'
    LOOP
        EXECUTE format(
            'SELECT EXISTS (SELECT 1 FROM %I.%I WHERE company_id = $1)',
            referenced_table.table_schema,
            referenced_table.table_name
        )
        INTO has_reference
        USING legacy_company_id;
        EXIT WHEN has_reference;
    END LOOP;

    IF NOT has_reference THEN
        DELETE FROM public.app_company AS legacy_company
        WHERE legacy_company.company_id = legacy_company_id
          AND legacy_company.company_name = '国金中恒企业管理(海南)有限公司'
          AND legacy_company.company_name_norm = '国金中恒企业管理(海南)有限公司';
    END IF;
END
$$;

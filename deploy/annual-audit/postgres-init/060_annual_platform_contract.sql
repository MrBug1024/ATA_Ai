-- Annual-audit platform compatibility tables.
-- `case_id` remains the public API compatibility name, but represents the
-- MySQL audit_engagement.id. No PostgreSQL project master table is required.

BEGIN;

CREATE TABLE IF NOT EXISTS public.thread_metadata (
    thread_id TEXT PRIMARY KEY,
    case_id BIGINT,
    company_id TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    last_intent TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT chk_annual_thread_case_id_positive CHECK (case_id IS NULL OR case_id > 0)
);

COMMENT ON TABLE public.thread_metadata IS
'年审 LangGraph 会话权限入口；case_id 表示 MySQL audit_engagement.id。';
COMMENT ON COLUMN public.thread_metadata.case_id IS
'年审项目兼容 ID，权威项目与成员关系存储于 MySQL ata_ai。';

CREATE INDEX IF NOT EXISTS idx_thread_metadata_company_created
    ON public.thread_metadata(company_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_thread_metadata_company_user
    ON public.thread_metadata(company_id, created_by);
CREATE INDEX IF NOT EXISTS idx_thread_metadata_case
    ON public.thread_metadata(case_id);

CREATE TABLE IF NOT EXISTS public.doc_category_catalog (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    sort_order INTEGER NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.doc_category_catalog IS
'年审资料类别目录；只包含财务报表审计资料。';

CREATE TABLE IF NOT EXISTS public.source_file_doc_category (
    id BIGSERIAL PRIMARY KEY,
    file_id BIGINT NOT NULL REFERENCES public.source_file(id) ON DELETE CASCADE,
    case_id BIGINT NOT NULL,
    category_code TEXT NOT NULL REFERENCES public.doc_category_catalog(code),
    match_source TEXT NOT NULL DEFAULT 'manual',
    confidence NUMERIC(5,4),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_annual_source_file_doc_category UNIQUE (file_id, category_code)
);

CREATE TABLE IF NOT EXISTS public.source_upload_batch (
    upload_batch_id TEXT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    entity_id BIGINT NOT NULL DEFAULT 0,
    batch_name TEXT NOT NULL DEFAULT '',
    doc_category TEXT REFERENCES public.doc_category_catalog(code),
    operator_id TEXT NOT NULL DEFAULT '',
    operator_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'received',
    file_count INTEGER NOT NULL DEFAULT 0,
    new_file_count INTEGER NOT NULL DEFAULT 0,
    duplicate_file_count INTEGER NOT NULL DEFAULT 0,
    suspected_mismatch_file_count INTEGER NOT NULL DEFAULT 0,
    records_inserted INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.source_file_upload_batch (
    id BIGSERIAL PRIMARY KEY,
    upload_batch_id TEXT NOT NULL REFERENCES public.source_upload_batch(upload_batch_id) ON DELETE CASCADE,
    file_id BIGINT NOT NULL REFERENCES public.source_file(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL DEFAULT '',
    file_sha256 CHAR(64) NOT NULL,
    duplicate_of TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_annual_source_file_upload_batch UNIQUE (upload_batch_id, file_id)
);

CREATE TABLE IF NOT EXISTS public.material_event (
    material_event_id TEXT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    entity_id BIGINT NOT NULL DEFAULT 0,
    upload_batch_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL DEFAULT 'supplement_upload',
    status TEXT NOT NULL DEFAULT 'received',
    batch_name TEXT NOT NULL DEFAULT '',
    doc_category TEXT NOT NULL DEFAULT '',
    operator_id TEXT NOT NULL DEFAULT '',
    operator_name TEXT NOT NULL DEFAULT '',
    file_count INTEGER NOT NULL DEFAULT 0,
    records_inserted INTEGER NOT NULL DEFAULT 0,
    event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT NOT NULL DEFAULT '',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.kg_unresolved_item (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL,
    extraction_run_id BIGINT NOT NULL REFERENCES public.kg_extraction_run(id) ON DELETE CASCADE,
    upload_batch_id TEXT NOT NULL DEFAULT '',
    material_event_id TEXT NOT NULL DEFAULT '',
    item_type TEXT NOT NULL,
    entity_name TEXT NOT NULL DEFAULT '',
    entity_key TEXT NOT NULL DEFAULT '',
    relation_key TEXT NOT NULL DEFAULT '',
    entity_temp_id TEXT NOT NULL DEFAULT '',
    relation_temp_id TEXT NOT NULL DEFAULT '',
    claim_type TEXT NOT NULL DEFAULT '',
    claim_text TEXT NOT NULL DEFAULT '',
    relation_type TEXT NOT NULL DEFAULT '',
    relation_label TEXT NOT NULL DEFAULT '',
    missing_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    resolved_entity_id BIGINT REFERENCES public.kg_entity(id) ON DELETE SET NULL,
    resolved_relation_id BIGINT REFERENCES public.kg_relation(id) ON DELETE SET NULL,
    resolved_claim_id BIGINT REFERENCES public.kg_claim(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_annual_doc_category_sort
    ON public.doc_category_catalog(sort_order, enabled);
CREATE INDEX IF NOT EXISTS idx_annual_source_file_category_case
    ON public.source_file_doc_category(case_id, category_code);
CREATE INDEX IF NOT EXISTS idx_annual_source_upload_batch_case
    ON public.source_upload_batch(case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_annual_material_event_case
    ON public.material_event(case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_annual_material_event_batch
    ON public.material_event(upload_batch_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_annual_kg_unresolved_case_status
    ON public.kg_unresolved_item(case_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_annual_kg_unresolved_batch
    ON public.kg_unresolved_item(upload_batch_id, created_at DESC);

INSERT INTO public.doc_category_catalog (
    code, name, description, sort_order, enabled, fields
) VALUES
    ('financial_statements', '财务报表及附注', '资产负债表、利润表、现金流量表、所有者权益变动表及附注', 1, TRUE, '["entity_name","period_end","statement_type"]'::jsonb),
    ('trial_balance', '科目余额表', '期初、本期发生及期末科目余额', 2, TRUE, '["account_code","account_name","opening_balance","period_debit","period_credit","closing_balance"]'::jsonb),
    ('journal_entries', '序时账及凭证明细', '总账、明细账、序时账和记账凭证行', 3, TRUE, '["voucher_date","voucher_no","account_code","account_name","debit_amount","credit_amount"]'::jsonb),
    ('receivables', '应收账款及往来明细', '客户余额、发生日、到期日、账龄及关联方标识', 4, TRUE, '["customer_name","document_no","occurrence_date","due_date","balance","is_related_party"]'::jsonb),
    ('bank_statements', '银行流水及对账单', '银行账户流水、银行对账单和余额调节表', 5, TRUE, '["bank_account","transaction_date","amount","direction","counterparty","running_balance"]'::jsonb),
    ('revenue_support', '收入支持性资料', '销售合同、订单、发票、出库、签收和验收资料', 6, TRUE, '["customer_name","contract_no","invoice_no","delivery_date","acceptance_date","amount"]'::jsonb),
    ('confirmations', '函证及回函', '银行函证、往来询证函及回函差异', 7, TRUE, '["confirmation_type","counterparty","sent_date","reply_date","confirmed_amount","difference"]'::jsonb),
    ('tax_materials', '纳税申报及税务资料', '增值税、企业所得税等申报表及税务支持材料', 8, TRUE, '["tax_type","tax_period","declared_amount"]'::jsonb),
    ('audit_workpapers', '历史审计底稿', '客户提供的历史工作底稿、审计程序和复核记录', 9, TRUE, '["workpaper_code","workpaper_name","period"]'::jsonb),
    ('other', '其他年审资料', '不能归入以上类别的其他财务报表审计资料', 99, TRUE, '[]'::jsonb)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    sort_order = EXCLUDED.sort_order,
    enabled = EXCLUDED.enabled,
    fields = EXCLUDED.fields,
    updated_at = now();

COMMIT;

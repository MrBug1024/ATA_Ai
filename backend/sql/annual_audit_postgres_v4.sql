-- Compatibility repair for early PostgreSQL v3 baselines.
-- Fresh installs receive these columns from v3; existing installs get them
-- through this idempotent follow-up migration.

ALTER TABLE public.audit_engagement
    ADD COLUMN IF NOT EXISTS engagement_type varchar(64)
        NOT NULL DEFAULT 'annual_financial_statement_audit',
    ADD COLUMN IF NOT EXISTS entity_uscc varchar(64),
    ADD COLUMN IF NOT EXISTS company_id varchar(128) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS owner_user_id varchar(128) NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_audit_engagement_company
    ON public.audit_engagement (company_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_audit_engagement_owner
    ON public.audit_engagement (owner_user_id, deleted_at);

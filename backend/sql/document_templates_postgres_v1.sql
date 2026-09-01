-- Platform-level immutable document template governance.
-- This migration intentionally uses document_template_* names and never
-- reuses the removed annual_audit_template_* tables.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.document_template_family (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_type VARCHAR(64) NOT NULL,
    scope_type VARCHAR(32) NOT NULL DEFAULT 'system',
    scope_key VARCHAR(128) NOT NULL DEFAULT 'system',
    active_version_id UUID NULL,
    next_version_no INTEGER NOT NULL DEFAULT 1 CHECK (next_version_no > 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_by VARCHAR(128) NOT NULL,
    updated_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uk_document_template_family_scope
        UNIQUE (scope_type, scope_key, business_type)
);

CREATE TABLE IF NOT EXISTS public.document_template_version (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES public.document_template_family(id),
    version_no INTEGER NOT NULL CHECK (version_no > 0),
    version_label VARCHAR(32) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    contract_version VARCHAR(32) NOT NULL DEFAULT '1.0',
    manifest_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_sha256 CHAR(64) NULL,
    validation_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_by VARCHAR(128) NOT NULL,
    updated_by VARCHAR(128) NOT NULL,
    activated_by VARCHAR(128) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at TIMESTAMPTZ NULL,
    archived_at TIMESTAMPTZ NULL,
    CONSTRAINT uk_document_template_version_no UNIQUE (family_id, version_no),
    CONSTRAINT ck_document_template_version_label
        CHECK (version_label = ('v' || version_no::text)),
    CONSTRAINT ck_document_template_version_status
        CHECK (status IN ('draft', 'validating', 'ready', 'active', 'retired', 'archived'))
);

CREATE TABLE IF NOT EXISTS public.document_template_file (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_version_id UUID NOT NULL
        REFERENCES public.document_template_version(id) ON DELETE CASCADE,
    document_code VARCHAR(128) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    source_file_name VARCHAR(512) NOT NULL,
    extension VARCHAR(16) NOT NULL,
    content_type VARCHAR(255) NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    source_object_ref VARCHAR(2048) NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    compiled_object_ref VARCHAR(2048) NULL,
    compiled_sha256 CHAR(64) NULL,
    renderer_profile VARCHAR(64) NULL,
    binding_manifest_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    inspection_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    preview_object_ref VARCHAR(2048) NULL,
    preview_sha256 CHAR(64) NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
    sort_order INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_by VARCHAR(128) NOT NULL,
    updated_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uk_document_template_file_code
        UNIQUE (template_version_id, document_code),
    CONSTRAINT ck_document_template_file_extension
        CHECK (extension IN ('.docx', '.xlsx', '.md', '.pdf')),
    CONSTRAINT ck_document_template_file_status
        CHECK (status IN ('uploaded', 'scanning', 'mapping', 'ready', 'invalid', 'archived'))
);

CREATE TABLE IF NOT EXISTS public.document_template_audit_event (
    id BIGSERIAL PRIMARY KEY,
    family_id UUID NULL REFERENCES public.document_template_family(id),
    version_id UUID NULL REFERENCES public.document_template_version(id) ON DELETE SET NULL,
    file_id UUID NULL REFERENCES public.document_template_file(id) ON DELETE SET NULL,
    event_type VARCHAR(64) NOT NULL,
    before_json JSONB NULL,
    after_json JSONB NULL,
    actor_user_id VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_template_version_status
    ON public.document_template_version (family_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_document_template_file_version
    ON public.document_template_file (template_version_id, sort_order, created_at);
CREATE INDEX IF NOT EXISTS idx_document_template_audit_version
    ON public.document_template_audit_event (version_id, created_at DESC);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_document_template_family_active_version'
    ) THEN
        ALTER TABLE public.document_template_family
            ADD CONSTRAINT fk_document_template_family_active_version
            FOREIGN KEY (active_version_id)
            REFERENCES public.document_template_version(id)
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
END $$;

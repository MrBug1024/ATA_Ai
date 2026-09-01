-- Conservative object-reference ledger for governed document templates.
--
-- Existing objects are deliberately classified as legacy_unknown.  They may
-- have consumers outside this database, so losing their last local reference
-- is not sufficient proof that the object can be deleted.

CREATE TABLE IF NOT EXISTS public.document_template_storage_object (
    storage_ref_hash CHAR(64) PRIMARY KEY,
    storage_ref TEXT NOT NULL,
    object_kind VARCHAR(32) NOT NULL,
    content_sha256 CHAR(64) NULL,
    management_scope VARCHAR(32) NOT NULL DEFAULT 'legacy_unknown',
    retention_state VARCHAR(32) NOT NULL DEFAULT 'active',
    retention_until TIMESTAMPTZ NULL,
    unreferenced_at TIMESTAMPTZ NULL,
    first_registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (storage_ref_hash ~ '^[0-9a-f]{64}$'),
    CHECK (object_kind IN ('source', 'compiled', 'preview')),
    CHECK (management_scope IN ('legacy_unknown', 'managed_exclusive')),
    CHECK (retention_state IN ('active', 'retained', 'reclaim_candidate', 'legal_hold'))
);

CREATE TABLE IF NOT EXISTS public.document_template_storage_reference (
    storage_ref_hash CHAR(64) NOT NULL REFERENCES public.document_template_storage_object(storage_ref_hash),
    owner_type VARCHAR(32) NOT NULL,
    owner_id UUID NOT NULL,
    owner_field VARCHAR(32) NOT NULL,
    acquired_by VARCHAR(128) NOT NULL DEFAULT 'migration',
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_by VARCHAR(128) NULL,
    release_reason VARCHAR(128) NULL,
    released_at TIMESTAMPTZ NULL,
    PRIMARY KEY (storage_ref_hash, owner_type, owner_id, owner_field),
    CHECK (owner_type = 'template_file'),
    CHECK (owner_field IN ('source', 'compiled', 'preview'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_document_template_storage_reference_active_owner
    ON public.document_template_storage_reference(owner_type, owner_id, owner_field)
    WHERE released_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_document_template_storage_object_reclamation
    ON public.document_template_storage_object(management_scope, retention_state, retention_until);

CREATE INDEX IF NOT EXISTS idx_document_template_storage_reference_owner
    ON public.document_template_storage_reference(owner_type, owner_id, released_at);

INSERT INTO public.document_template_storage_object (
    storage_ref_hash, storage_ref, object_kind, content_sha256,
    management_scope, retention_state
)
SELECT encode(digest(tf.source_object_ref, 'sha256'), 'hex'),
       tf.source_object_ref, 'source', MIN(tf.source_sha256),
       'legacy_unknown', 'active'
FROM public.document_template_file tf
WHERE tf.source_object_ref IS NOT NULL AND tf.source_object_ref <> ''
GROUP BY tf.source_object_ref
ON CONFLICT (storage_ref_hash) DO UPDATE
SET last_seen_at = now(),
    retention_state = CASE
      WHEN public.document_template_storage_object.retention_state = 'legal_hold'
      THEN 'legal_hold' ELSE 'active'
    END,
    retention_until = CASE
      WHEN public.document_template_storage_object.retention_state = 'legal_hold'
      THEN public.document_template_storage_object.retention_until ELSE NULL
    END,
    unreferenced_at = CASE
      WHEN public.document_template_storage_object.retention_state = 'legal_hold'
      THEN public.document_template_storage_object.unreferenced_at ELSE NULL
    END;

INSERT INTO public.document_template_storage_object (
    storage_ref_hash, storage_ref, object_kind, content_sha256,
    management_scope, retention_state
)
SELECT encode(digest(tf.compiled_object_ref, 'sha256'), 'hex'),
       tf.compiled_object_ref, 'compiled', MIN(tf.compiled_sha256),
       'legacy_unknown', 'active'
FROM public.document_template_file tf
WHERE tf.compiled_object_ref IS NOT NULL AND tf.compiled_object_ref <> ''
GROUP BY tf.compiled_object_ref
ON CONFLICT (storage_ref_hash) DO UPDATE
SET last_seen_at = now(),
    retention_state = CASE
      WHEN public.document_template_storage_object.retention_state = 'legal_hold'
      THEN 'legal_hold' ELSE 'active'
    END,
    retention_until = CASE
      WHEN public.document_template_storage_object.retention_state = 'legal_hold'
      THEN public.document_template_storage_object.retention_until ELSE NULL
    END,
    unreferenced_at = CASE
      WHEN public.document_template_storage_object.retention_state = 'legal_hold'
      THEN public.document_template_storage_object.unreferenced_at ELSE NULL
    END;

INSERT INTO public.document_template_storage_object (
    storage_ref_hash, storage_ref, object_kind, content_sha256,
    management_scope, retention_state
)
SELECT encode(digest(tf.preview_object_ref, 'sha256'), 'hex'),
       tf.preview_object_ref, 'preview', MIN(tf.preview_sha256),
       'legacy_unknown', 'active'
FROM public.document_template_file tf
WHERE tf.preview_object_ref IS NOT NULL AND tf.preview_object_ref <> ''
GROUP BY tf.preview_object_ref
ON CONFLICT (storage_ref_hash) DO UPDATE
SET last_seen_at = now(),
    retention_state = CASE
      WHEN public.document_template_storage_object.retention_state = 'legal_hold'
      THEN 'legal_hold' ELSE 'active'
    END,
    retention_until = CASE
      WHEN public.document_template_storage_object.retention_state = 'legal_hold'
      THEN public.document_template_storage_object.retention_until ELSE NULL
    END,
    unreferenced_at = CASE
      WHEN public.document_template_storage_object.retention_state = 'legal_hold'
      THEN public.document_template_storage_object.unreferenced_at ELSE NULL
    END;

INSERT INTO public.document_template_storage_reference (
    storage_ref_hash, owner_type, owner_id, owner_field, acquired_by
)
SELECT encode(digest(tf.source_object_ref, 'sha256'), 'hex'),
       'template_file', tf.id, 'source', 'migration'
FROM public.document_template_file tf
WHERE tf.source_object_ref IS NOT NULL AND tf.source_object_ref <> ''
ON CONFLICT (storage_ref_hash, owner_type, owner_id, owner_field) DO UPDATE
SET released_by = NULL, release_reason = NULL, released_at = NULL;

INSERT INTO public.document_template_storage_reference (
    storage_ref_hash, owner_type, owner_id, owner_field, acquired_by
)
SELECT encode(digest(tf.compiled_object_ref, 'sha256'), 'hex'),
       'template_file', tf.id, 'compiled', 'migration'
FROM public.document_template_file tf
WHERE tf.compiled_object_ref IS NOT NULL AND tf.compiled_object_ref <> ''
ON CONFLICT (storage_ref_hash, owner_type, owner_id, owner_field) DO UPDATE
SET released_by = NULL, release_reason = NULL, released_at = NULL;

INSERT INTO public.document_template_storage_reference (
    storage_ref_hash, owner_type, owner_id, owner_field, acquired_by
)
SELECT encode(digest(tf.preview_object_ref, 'sha256'), 'hex'),
       'template_file', tf.id, 'preview', 'migration'
FROM public.document_template_file tf
WHERE tf.preview_object_ref IS NOT NULL AND tf.preview_object_ref <> ''
ON CONFLICT (storage_ref_hash, owner_type, owner_id, owner_field) DO UPDATE
SET released_by = NULL, release_reason = NULL, released_at = NULL;

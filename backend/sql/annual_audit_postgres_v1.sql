DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'source_file' AND column_name = 'debtor_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'source_file' AND column_name = 'entity_id'
    ) THEN
        ALTER TABLE public.source_file RENAME COLUMN debtor_id TO entity_id;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'source_upload_batch' AND column_name = 'debtor_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'source_upload_batch' AND column_name = 'entity_id'
    ) THEN
        ALTER TABLE public.source_upload_batch RENAME COLUMN debtor_id TO entity_id;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'material_event' AND column_name = 'debtor_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'material_event' AND column_name = 'entity_id'
    ) THEN
        ALTER TABLE public.material_event RENAME COLUMN debtor_id TO entity_id;
    END IF;
END $$;

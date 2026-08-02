-- Clean duplicate conversation_log for a specific thread during testing.
-- This deletes all checkpoints and blobs for the given thread_id,
-- effectively resetting the thread to a clean state.

-- IMPORTANT: Use only in testing/development. In production, consider
-- soft-deletion or more surgical cleanup.

-- Example: reset thread 268540b6-afbd-4bbf-be4e-11d6077833eb
-- DELETE FROM public.checkpoint_blobs WHERE thread_id = '268540b6-afbd-4bbf-be4e-11d6077833eb' AND checkpoint_ns = '';
-- DELETE FROM public.checkpoints WHERE thread_id = '268540b6-afbd-4bbf-be4e-11d6077833eb' AND checkpoint_ns = '';

-- Generic parameterized version (run with psql variable substitution):
-- \set thread_id '268540b6-afbd-4bbf-be4e-11d6077833eb'

BEGIN;

DELETE FROM public.checkpoint_blobs
WHERE thread_id = :'thread_id'
  AND checkpoint_ns = '';

DELETE FROM public.checkpoints
WHERE thread_id = :'thread_id'
  AND checkpoint_ns = '';

COMMIT;

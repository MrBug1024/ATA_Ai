-- 为 checkpoints 表添加软删除支持
-- 用途：支持会话历史的软删除，保留数据用于审计和恢复

BEGIN;

-- 添加 deleted_at 字段
ALTER TABLE public.checkpoints 
ADD COLUMN IF NOT EXISTS deleted_at timestamp with time zone DEFAULT NULL;

COMMENT ON COLUMN public.checkpoints.deleted_at IS '软删除时间戳。NULL 表示未删除，非 NULL 表示已删除。';

-- 更新迁移版本
INSERT INTO public.checkpoint_migrations (v)
SELECT 1
WHERE NOT EXISTS (
    SELECT 1 FROM public.checkpoint_migrations WHERE v = 1
);

COMMIT;

-- 创建索引以加速查询未删除的记录（必须在事务外执行）
CREATE INDEX CONCURRENTLY IF NOT EXISTS checkpoints_deleted_at_idx
    ON public.checkpoints(deleted_at)
    WHERE deleted_at IS NULL;

COMMENT ON INDEX public.checkpoints_deleted_at_idx IS '加速查询未删除的 checkpoint 记录（部分索引）。';

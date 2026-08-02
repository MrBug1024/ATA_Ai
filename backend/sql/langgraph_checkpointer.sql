-- LangGraph PostgreSQL Checkpointer 初始化脚本
-- 用途：
-- 1. 为 LangGraph 多轮对话 / graph state 持久化创建专用表
-- 2. 不影响现有业务表，不删除任何对象
-- 3. 表与字段均补充中文注释，便于后续运维与审计

BEGIN;

CREATE TABLE IF NOT EXISTS public.checkpoint_migrations (
    v integer PRIMARY KEY
);

COMMENT ON TABLE public.checkpoint_migrations IS 'LangGraph checkpointer 迁移版本表，用于记录已执行的 checkpoint 数据库迁移版本。';
COMMENT ON COLUMN public.checkpoint_migrations.v IS '迁移版本号。';

CREATE TABLE IF NOT EXISTS public.checkpoints (
    thread_id text NOT NULL,
    checkpoint_ns text NOT NULL DEFAULT '',
    checkpoint_id text NOT NULL,
    parent_checkpoint_id text,
    type text,
    checkpoint jsonb NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

COMMENT ON TABLE public.checkpoints IS 'LangGraph 主 checkpoint 表，用于按 thread_id 保存每次图执行后的状态快照与元数据。';
COMMENT ON COLUMN public.checkpoints.thread_id IS '线程 ID，对应一次多轮对话或图执行主线。';
COMMENT ON COLUMN public.checkpoints.checkpoint_ns IS 'checkpoint 命名空间，LangGraph 内部用于区分不同作用域。';
COMMENT ON COLUMN public.checkpoints.checkpoint_id IS '本次 checkpoint 的唯一标识。';
COMMENT ON COLUMN public.checkpoints.parent_checkpoint_id IS '父 checkpoint ID，用于回溯状态链。';
COMMENT ON COLUMN public.checkpoints.type IS 'checkpoint 类型，LangGraph 内部保留字段。';
COMMENT ON COLUMN public.checkpoints.checkpoint IS 'checkpoint 主体内容，包含轻量状态快照。';
COMMENT ON COLUMN public.checkpoints.metadata IS 'checkpoint 元数据，记录写入来源、step 等辅助信息。';

CREATE TABLE IF NOT EXISTS public.checkpoint_blobs (
    thread_id text NOT NULL,
    checkpoint_ns text NOT NULL DEFAULT '',
    channel text NOT NULL,
    version text NOT NULL,
    type text NOT NULL,
    blob bytea,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

COMMENT ON TABLE public.checkpoint_blobs IS 'LangGraph 大字段分离存储表，用于保存 checkpoint 中不适合直接内联的通道二进制内容。';
COMMENT ON COLUMN public.checkpoint_blobs.thread_id IS '线程 ID。';
COMMENT ON COLUMN public.checkpoint_blobs.checkpoint_ns IS 'checkpoint 命名空间。';
COMMENT ON COLUMN public.checkpoint_blobs.channel IS '状态通道名。';
COMMENT ON COLUMN public.checkpoint_blobs.version IS '该通道内容的版本号。';
COMMENT ON COLUMN public.checkpoint_blobs.type IS 'blob 内容类型。';
COMMENT ON COLUMN public.checkpoint_blobs.blob IS '序列化后的二进制内容。';

CREATE TABLE IF NOT EXISTS public.checkpoint_writes (
    thread_id text NOT NULL,
    checkpoint_ns text NOT NULL DEFAULT '',
    checkpoint_id text NOT NULL,
    task_id text NOT NULL,
    idx integer NOT NULL,
    channel text NOT NULL,
    type text,
    blob bytea NOT NULL,
    task_path text NOT NULL DEFAULT '',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

COMMENT ON TABLE public.checkpoint_writes IS 'LangGraph 节点写入明细表，用于记录单个任务/节点对状态通道的写入内容。';
COMMENT ON COLUMN public.checkpoint_writes.thread_id IS '线程 ID。';
COMMENT ON COLUMN public.checkpoint_writes.checkpoint_ns IS 'checkpoint 命名空间。';
COMMENT ON COLUMN public.checkpoint_writes.checkpoint_id IS '关联的 checkpoint ID。';
COMMENT ON COLUMN public.checkpoint_writes.task_id IS 'LangGraph 节点任务 ID。';
COMMENT ON COLUMN public.checkpoint_writes.idx IS '同一任务的写入顺序号。';
COMMENT ON COLUMN public.checkpoint_writes.channel IS '被写入的状态通道名。';
COMMENT ON COLUMN public.checkpoint_writes.type IS '写入内容类型。';
COMMENT ON COLUMN public.checkpoint_writes.blob IS '序列化后的写入内容。';
COMMENT ON COLUMN public.checkpoint_writes.task_path IS '任务路径，LangGraph 内部用于标识执行路径。';

INSERT INTO public.checkpoint_migrations (v)
SELECT 0
WHERE NOT EXISTS (
    SELECT 1 FROM public.checkpoint_migrations WHERE v = 0
);

COMMIT;

CREATE INDEX CONCURRENTLY IF NOT EXISTS checkpoints_thread_id_idx
    ON public.checkpoints(thread_id);

COMMENT ON INDEX public.checkpoints_thread_id_idx IS '按 thread_id 查询 LangGraph checkpoint 的加速索引。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS checkpoint_blobs_thread_id_idx
    ON public.checkpoint_blobs(thread_id);

COMMENT ON INDEX public.checkpoint_blobs_thread_id_idx IS '按 thread_id 查询 LangGraph blob 内容的加速索引。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS checkpoint_writes_thread_id_idx
    ON public.checkpoint_writes(thread_id);

COMMENT ON INDEX public.checkpoint_writes_thread_id_idx IS '按 thread_id 查询 LangGraph 写入明细的加速索引。';

-- heavy_payload_store 初始化脚本
-- 用途：
-- 1. 为 AI Hunter 的大 payload 提供 PostgreSQL 持久化存储
-- 2. 配合 Redis 作为热缓存，实现 redis + pgsql 双层恢复
-- 3. 不影响现有业务表，不删除任何对象

BEGIN;

CREATE TABLE IF NOT EXISTS public.heavy_payload_store (
    payload_key text PRIMARY KEY,
    payload_type text NOT NULL,
    payload_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT NOW(),
    updated_at timestamptz NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.heavy_payload_store IS 'AI Hunter 大 payload 持久化表，用于保存不适合直接放入 LangGraph checkpoint 的重型 JSON 内容。';
COMMENT ON COLUMN public.heavy_payload_store.payload_key IS '大 payload 的唯一引用键，写入 state 的 ref 即来自该字段。';
COMMENT ON COLUMN public.heavy_payload_store.payload_type IS '大 payload 类型，例如 full_context、ingest_payload、parse_document_result。';
COMMENT ON COLUMN public.heavy_payload_store.payload_json IS '大 payload 的 JSON 主体内容。';
COMMENT ON COLUMN public.heavy_payload_store.created_at IS '记录创建时间。';
COMMENT ON COLUMN public.heavy_payload_store.updated_at IS '记录最近更新时间。';

COMMIT;

CREATE INDEX CONCURRENTLY IF NOT EXISTS heavy_payload_store_type_idx
    ON public.heavy_payload_store(payload_type);

COMMENT ON INDEX public.heavy_payload_store_type_idx IS '按 payload_type 查询大 payload 的加速索引。';

-- get_full_context 结果缓存表（compute/fetch 分离）
-- 默认读缓存命中即秒回，跳过 4 引擎重算+写库；ingest 写库后失效；recompute=true 强制重算。
-- 与 ai_hunter 共用同一库，首次部署需执行本文件。
CREATE TABLE IF NOT EXISTS engine_results_cache (
    case_id     BIGINT PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
    payload     JSONB NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE engine_results_cache IS
'get_full_context 结果缓存：命中即秒回，ingest 失效，recompute=true 强制重算。payload 为整份 get_full_context 响应快照';
COMMENT ON COLUMN engine_results_cache.case_id IS '案件 ID（PK，随 cases 级联删除）';
COMMENT ON COLUMN engine_results_cache.payload IS '整份 get_full_context 响应 JSON 快照';
COMMENT ON COLUMN engine_results_cache.computed_at IS '本次重算时间，配合 FULL_CONTEXT_CACHE_TTL_SECONDS 判定新鲜度';

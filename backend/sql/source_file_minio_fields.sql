-- AI Hunter source_file 表 MinIO 存储字段增量脚本
-- 用途：
-- 1. 为 source_file 增加结构化对象存储字段
-- 2. 支持原始卷宗存 MinIO，数据库只保存对象引用与校验信息
-- 3. 不删除任何现有字段，仅增量补充

BEGIN;

ALTER TABLE public.source_file
    ADD COLUMN IF NOT EXISTS storage_provider TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS storage_bucket TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS storage_key TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS storage_etag TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS storage_version TEXT NOT NULL DEFAULT '';

COMMENT ON COLUMN public.source_file.storage_provider IS '对象存储提供方；当前建议写 minio，用于区分本地路径、MinIO 或其他对象存储。';
COMMENT ON COLUMN public.source_file.storage_bucket IS '对象所在 bucket 名；例如 ai-hunter-raw、ai-hunter-derived、ai-hunter-artifacts。';
COMMENT ON COLUMN public.source_file.storage_key IS '对象在 bucket 中的唯一 key；通常按 case_id/文件类别/文件名 组织。';
COMMENT ON COLUMN public.source_file.storage_etag IS '对象 ETag；用于校验上传结果和后续对象一致性检查。';
COMMENT ON COLUMN public.source_file.storage_version IS '对象版本号；若 MinIO 开启版本控制，可记录 version_id。';

COMMIT;

CREATE INDEX CONCURRENTLY IF NOT EXISTS source_file_storage_bucket_key_idx
    ON public.source_file(storage_bucket, storage_key);

COMMENT ON INDEX public.source_file_storage_bucket_key_idx IS '按 MinIO bucket + object key 查询原始卷宗引用的加速索引。';

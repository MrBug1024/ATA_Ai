-- 重整方案派生 claim 的幂等化（F1）+ 清偿率数值列（F3）
-- 配合 main.py ingest_structured_fields 的「按类型 upsert」：重整方案/职工债权/税款债权
-- 各 (case_id, debtor_id) 仅一行，重复入库变为覆盖而非累积。
-- 与 ai_hunter 共用同一库，首次部署执行本文件。

-- F3: 清偿率数值列（不再塞进 guarantee_type 文本）
ALTER TABLE claims ADD COLUMN IF NOT EXISTS proposed_recovery_rate NUMERIC(7,4);
COMMENT ON COLUMN claims.proposed_recovery_rate IS '重整方案清偿率(百分数，如 22.38 表示 22.38%)，从重整方案文书提取';

-- F1: 部分唯一索引，作为「按类型 upsert」的冲突键。
-- 仅约束重整方案派生的三类合成 claim，不影响贷款合同等可重复 guarantee_type 的 claim。
-- 注意：已存在污染数据（重复行）的库，需先做下方一次性清洗再建索引，否则建索引会因唯一冲突失败。
CREATE UNIQUE INDEX IF NOT EXISTS uq_claims_restructuring_type
    ON claims (case_id, debtor_id, guarantee_type)
    WHERE guarantee_type IN ('重整方案', '职工债权', '税款债权');

-- ────────────────────────────────────────────────────────────────────────
-- 一次性清洗（仅对历史已污染库执行，全新库无需）：F3 回填 + F2-b 去重
-- 顺序：先回填规范化，再去重，最后建上面的唯一索引。
-- ────────────────────────────────────────────────────────────────────────
-- 1) F3 回填：从旧 guarantee_type 文本 '重整方案(清偿率X%)' 提取清偿率到数值列，
--    并把 guarantee_type 收敛为稳定值 '重整方案'。
--    （注意：清偿率提取与 guarantee_type 覆盖应分两步，先 SELECT 校验再 UPDATE，避免覆盖丢失。）
-- UPDATE claims
--   SET proposed_recovery_rate = NULLIF(substring(guarantee_type from '清偿率([0-9.]+)%'), '')::numeric
--   WHERE guarantee_type LIKE '重整方案(%';
-- UPDATE claims SET guarantee_type = '重整方案' WHERE guarantee_type LIKE '重整方案%';
--
-- 2) F2-b 去重：每 (case_id, debtor_id, guarantee_type) 保留最完整一条（非空 total/优先/普通/清偿率优先，
--    平手取最新 claim_id），删其余。
-- DELETE FROM claims WHERE claim_id IN (
--   SELECT claim_id FROM (
--     SELECT claim_id, ROW_NUMBER() OVER (
--       PARTITION BY case_id, debtor_id, guarantee_type
--       ORDER BY (total_claim IS NOT NULL)::int DESC, (priority_amount IS NOT NULL)::int DESC,
--                (general_amount IS NOT NULL)::int DESC, (proposed_recovery_rate IS NOT NULL)::int DESC,
--                claim_id DESC) AS rn
--     FROM claims WHERE guarantee_type IN ('重整方案','职工债权','税款债权')
--   ) t WHERE t.rn > 1);

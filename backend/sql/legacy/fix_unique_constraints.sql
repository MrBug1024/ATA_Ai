-- ============================================================================
-- 修复：为financial_snapshots和mining_evaluations表添加UNIQUE约束
-- 解决ON CONFLICT冲突错误
-- ============================================================================

-- 1. financial_snapshots表：添加(case_id, debtor_id, report_period, report_type)的唯一约束
ALTER TABLE financial_snapshots 
ADD CONSTRAINT uq_fs_period_type UNIQUE (case_id, debtor_id, report_period, report_type);

-- 2. mining_evaluations表：添加(case_id, mine_name)的唯一约束
ALTER TABLE mining_evaluations 
ADD CONSTRAINT uq_me_case_mine UNIQUE (case_id, mine_name);

-- 验证约束已创建
\d financial_snapshots
\d mining_evaluations

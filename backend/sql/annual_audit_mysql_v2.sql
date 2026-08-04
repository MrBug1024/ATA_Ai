-- Annual engagement fields required by the unchanged case API contract.
-- Applied once and recorded as migration 002 by the migration runner.
USE `ata_agent`;

ALTER TABLE `audit_engagement`
  ADD COLUMN `engagement_type` VARCHAR(64) NOT NULL DEFAULT 'annual_financial_statement_audit' AFTER `name`,
  ADD COLUMN `entity_uscc` VARCHAR(32) NULL AFTER `entity_name`,
  ADD COLUMN `company_id` VARCHAR(128) NOT NULL DEFAULT '' AFTER `status`,
  ADD COLUMN `owner_user_id` VARCHAR(128) NOT NULL DEFAULT '' AFTER `company_id`;

CREATE INDEX `idx_audit_engagement_tenant`
  ON `audit_engagement` (`company_id`, `owner_user_id`, `deleted_at`);

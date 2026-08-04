-- Bind annual structured rows to the shared platform evidence chain.
-- These IDs reference the isolated annual PostgreSQL source_file/page/chunk
-- records created by the upload ingest graph.  They are intentionally
-- nullable so legacy rows can be backfilled without changing their facts.
ALTER TABLE `annual_account_balance`
  ADD COLUMN `source_file_id` BIGINT UNSIGNED NULL,
  ADD COLUMN `source_page_id` BIGINT UNSIGNED NULL,
  ADD COLUMN `source_chunk_id` CHAR(64) NULL,
  ADD COLUMN `locator_kind` VARCHAR(32) NOT NULL DEFAULT 'sheet_row';

ALTER TABLE `annual_journal_entry_line`
  ADD COLUMN `source_file_id` BIGINT UNSIGNED NULL,
  ADD COLUMN `source_page_id` BIGINT UNSIGNED NULL,
  ADD COLUMN `source_chunk_id` CHAR(64) NULL,
  ADD COLUMN `locator_kind` VARCHAR(32) NOT NULL DEFAULT 'sheet_row';

ALTER TABLE `annual_receivable_item`
  ADD COLUMN `source_file_id` BIGINT UNSIGNED NULL,
  ADD COLUMN `source_page_id` BIGINT UNSIGNED NULL,
  ADD COLUMN `source_chunk_id` CHAR(64) NULL,
  ADD COLUMN `locator_kind` VARCHAR(32) NOT NULL DEFAULT 'sheet_row';

ALTER TABLE `annual_bank_transaction`
  ADD COLUMN `source_file_id` BIGINT UNSIGNED NULL,
  ADD COLUMN `source_page_id` BIGINT UNSIGNED NULL,
  ADD COLUMN `source_chunk_id` CHAR(64) NULL,
  ADD COLUMN `locator_kind` VARCHAR(32) NOT NULL DEFAULT 'sheet_row';

INSERT INTO `ata_schema_migration` (`version`, `description`)
VALUES ('007', 'bind annual structured rows to platform evidence anchors')
ON DUPLICATE KEY UPDATE `description` = VALUES(`description`);

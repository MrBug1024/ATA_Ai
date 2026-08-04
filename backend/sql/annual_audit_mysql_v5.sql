-- Structured annual-audit domain data for the first sales/receivables and
-- cash/bank demonstration cycles. Raw files and evidence anchors stay in the
-- isolated platform PostgreSQL/MinIO stores and are referenced by source_ref.
USE `ata_agent`;

CREATE TABLE IF NOT EXISTS `annual_import_batch` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `source_ref` VARCHAR(1024) NOT NULL,
  `source_type` VARCHAR(64) NOT NULL,
  `source_sha256` CHAR(64) NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'pending',
  `row_count` INT UNSIGNED NOT NULL DEFAULT 0,
  `metadata_json` JSON NULL,
  `error_message` TEXT NULL,
  `created_by` VARCHAR(128) NOT NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `completed_at` DATETIME(6) NULL,
  PRIMARY KEY (`id`),
  KEY `idx_annual_import_engagement` (`engagement_id`, `source_type`, `status`),
  CONSTRAINT `fk_annual_import_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `annual_account_balance` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `import_batch_id` BIGINT UNSIGNED NOT NULL,
  `period_end` DATE NOT NULL,
  `account_code` VARCHAR(64) NOT NULL,
  `account_name` VARCHAR(255) NOT NULL,
  `opening_debit` DECIMAL(20,2) NOT NULL DEFAULT 0,
  `opening_credit` DECIMAL(20,2) NOT NULL DEFAULT 0,
  `period_debit` DECIMAL(20,2) NOT NULL DEFAULT 0,
  `period_credit` DECIMAL(20,2) NOT NULL DEFAULT 0,
  `closing_debit` DECIMAL(20,2) NOT NULL DEFAULT 0,
  `closing_credit` DECIMAL(20,2) NOT NULL DEFAULT 0,
  `currency` CHAR(3) NOT NULL DEFAULT 'CNY',
  `source_locator_json` JSON NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_annual_account_balance` (`import_batch_id`, `account_code`, `period_end`),
  KEY `idx_annual_account_engagement` (`engagement_id`, `account_code`, `period_end`),
  CONSTRAINT `fk_annual_account_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`),
  CONSTRAINT `fk_annual_account_batch`
    FOREIGN KEY (`import_batch_id`) REFERENCES `annual_import_batch` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `annual_journal_entry_line` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `import_batch_id` BIGINT UNSIGNED NOT NULL,
  `voucher_date` DATE NOT NULL,
  `voucher_no` VARCHAR(128) NOT NULL,
  `line_no` INT UNSIGNED NOT NULL,
  `account_code` VARCHAR(64) NOT NULL,
  `account_name` VARCHAR(255) NOT NULL,
  `debit_amount` DECIMAL(20,2) NOT NULL DEFAULT 0,
  `credit_amount` DECIMAL(20,2) NOT NULL DEFAULT 0,
  `counterparty` VARCHAR(255) NULL,
  `description` VARCHAR(1024) NULL,
  `source_locator_json` JSON NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_annual_journal_line` (`import_batch_id`, `voucher_no`, `line_no`),
  KEY `idx_annual_journal_engagement_date` (`engagement_id`, `voucher_date`),
  KEY `idx_annual_journal_voucher` (`engagement_id`, `voucher_no`),
  CONSTRAINT `fk_annual_journal_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`),
  CONSTRAINT `fk_annual_journal_batch`
    FOREIGN KEY (`import_batch_id`) REFERENCES `annual_import_batch` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `annual_receivable_item` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `import_batch_id` BIGINT UNSIGNED NOT NULL,
  `customer_name` VARCHAR(255) NOT NULL,
  `document_no` VARCHAR(128) NULL,
  `occurrence_date` DATE NULL,
  `due_date` DATE NULL,
  `balance` DECIMAL(20,2) NOT NULL,
  `currency` CHAR(3) NOT NULL DEFAULT 'CNY',
  `is_related_party` BOOLEAN NOT NULL DEFAULT FALSE,
  `source_locator_json` JSON NULL,
  PRIMARY KEY (`id`),
  KEY `idx_annual_receivable_engagement` (`engagement_id`, `customer_name`),
  KEY `idx_annual_receivable_due` (`engagement_id`, `due_date`),
  CONSTRAINT `fk_annual_receivable_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`),
  CONSTRAINT `fk_annual_receivable_batch`
    FOREIGN KEY (`import_batch_id`) REFERENCES `annual_import_batch` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `annual_bank_transaction` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `import_batch_id` BIGINT UNSIGNED NOT NULL,
  `bank_account` VARCHAR(128) NOT NULL,
  `transaction_date` DATE NOT NULL,
  `amount` DECIMAL(20,2) NOT NULL,
  `direction` VARCHAR(16) NOT NULL,
  `counterparty` VARCHAR(255) NULL,
  `transaction_ref` VARCHAR(255) NULL,
  `description` VARCHAR(1024) NULL,
  `running_balance` DECIMAL(20,2) NULL,
  `source_locator_json` JSON NULL,
  PRIMARY KEY (`id`),
  KEY `idx_annual_bank_engagement_date` (`engagement_id`, `transaction_date`),
  KEY `idx_annual_bank_counterparty` (`engagement_id`, `counterparty`),
  KEY `idx_annual_bank_amount` (`engagement_id`, `amount`),
  CONSTRAINT `fk_annual_bank_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`),
  CONSTRAINT `fk_annual_bank_batch`
    FOREIGN KEY (`import_batch_id`) REFERENCES `annual_import_batch` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `annual_analysis_run` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `analysis_type` VARCHAR(64) NOT NULL,
  `input_version` VARCHAR(128) NOT NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'running',
  `parameters_json` JSON NOT NULL,
  `result_json` JSON NULL,
  `created_by` VARCHAR(128) NOT NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `completed_at` DATETIME(6) NULL,
  PRIMARY KEY (`id`),
  KEY `idx_annual_analysis_engagement` (`engagement_id`, `analysis_type`, `created_at`),
  CONSTRAINT `fk_annual_analysis_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `annual_finding` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `analysis_run_id` BIGINT UNSIGNED NOT NULL,
  `finding_type` VARCHAR(64) NOT NULL,
  `risk_level` VARCHAR(16) NOT NULL,
  `title` VARCHAR(255) NOT NULL,
  `description` TEXT NOT NULL,
  `amount` DECIMAL(20,2) NULL,
  `evidence_refs_json` JSON NOT NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'open',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_annual_finding_engagement` (`engagement_id`, `risk_level`, `status`),
  CONSTRAINT `fk_annual_finding_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`),
  CONSTRAINT `fk_annual_finding_run`
    FOREIGN KEY (`analysis_run_id`) REFERENCES `annual_analysis_run` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `annual_workpaper` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `workpaper_code` VARCHAR(64) NOT NULL,
  `workpaper_name` VARCHAR(255) NOT NULL,
  `template_version` VARCHAR(64) NOT NULL,
  `workpaper_version` INT NOT NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'draft',
  `facts_json` JSON NOT NULL,
  `conclusion_text` LONGTEXT NULL,
  `artifact_ref` VARCHAR(1024) NULL,
  `created_by` VARCHAR(128) NOT NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_annual_workpaper_version`
    (`engagement_id`, `workpaper_code`, `workpaper_version`),
  CONSTRAINT `fk_annual_workpaper_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

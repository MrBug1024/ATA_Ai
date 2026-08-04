-- AI 会计师·年审智能体 MySQL V1 基础数据模型
-- Target database is deliberately fixed to the isolated annual-audit database.
USE `ata_agent`;

CREATE TABLE IF NOT EXISTS `ata_schema_migration` (
  `version` VARCHAR(64) NOT NULL,
  `description` VARCHAR(255) NOT NULL,
  `applied_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `audit_engagement` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_code` VARCHAR(64) NOT NULL,
  `name` VARCHAR(255) NOT NULL,
  `entity_name` VARCHAR(255) NOT NULL,
  `fiscal_year` SMALLINT NOT NULL,
  `period_start` DATE NOT NULL,
  `period_end` DATE NOT NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'planning',
  `created_by` VARCHAR(128) NOT NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  `deleted_at` DATETIME(6) NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_audit_engagement_code` (`engagement_code`),
  KEY `idx_audit_engagement_period` (`fiscal_year`, `period_end`),
  KEY `idx_audit_engagement_status` (`status`, `deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `ata_project_member` (
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `user_id` VARCHAR(128) NOT NULL,
  `role_code` VARCHAR(64) NOT NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`engagement_id`, `user_id`),
  KEY `idx_ata_project_member_user` (`user_id`),
  CONSTRAINT `fk_ata_project_member_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `ata_thread` (
  `thread_id` VARCHAR(128) NOT NULL,
  `engagement_id` BIGINT UNSIGNED NULL,
  `owner_user_id` VARCHAR(128) NOT NULL,
  `title` VARCHAR(255) NOT NULL DEFAULT '',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  `deleted_at` DATETIME(6) NULL,
  PRIMARY KEY (`thread_id`),
  KEY `idx_ata_thread_owner_updated` (`owner_user_id`, `updated_at`),
  KEY `idx_ata_thread_engagement` (`engagement_id`),
  CONSTRAINT `fk_ata_thread_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `ata_checkpoint` (
  `thread_id` VARCHAR(128) NOT NULL,
  `checkpoint_ns` VARCHAR(255) NOT NULL DEFAULT '',
  `checkpoint_id` VARCHAR(128) NOT NULL,
  `parent_checkpoint_id` VARCHAR(128) NULL,
  `checkpoint_type` VARCHAR(64) NOT NULL,
  `checkpoint_blob` LONGBLOB NOT NULL,
  `metadata_blob` LONGBLOB NOT NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`thread_id`, `checkpoint_ns`, `checkpoint_id`),
  KEY `idx_ata_checkpoint_latest` (`thread_id`, `checkpoint_ns`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `ata_checkpoint_write` (
  `thread_id` VARCHAR(128) NOT NULL,
  `checkpoint_ns` VARCHAR(255) NOT NULL DEFAULT '',
  `checkpoint_id` VARCHAR(128) NOT NULL,
  `task_id` VARCHAR(128) NOT NULL,
  `write_idx` INT NOT NULL,
  `channel_name` VARCHAR(255) NOT NULL,
  `value_type` VARCHAR(64) NOT NULL,
  `value_blob` LONGBLOB NOT NULL,
  PRIMARY KEY (`thread_id`, `checkpoint_ns`, `checkpoint_id`, `task_id`, `write_idx`),
  CONSTRAINT `fk_ata_checkpoint_write_checkpoint`
    FOREIGN KEY (`thread_id`, `checkpoint_ns`, `checkpoint_id`)
    REFERENCES `ata_checkpoint` (`thread_id`, `checkpoint_ns`, `checkpoint_id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `ata_conversation_message` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `thread_id` VARCHAR(128) NOT NULL,
  `turn_id` VARCHAR(128) NOT NULL,
  `role` VARCHAR(32) NOT NULL,
  `content` LONGTEXT NOT NULL,
  `content_json` JSON NULL,
  `final_report_ref` VARCHAR(128) NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_ata_conversation_turn_role` (`thread_id`, `turn_id`, `role`),
  KEY `idx_ata_conversation_thread` (`thread_id`, `created_at`),
  CONSTRAINT `fk_ata_conversation_thread`
    FOREIGN KEY (`thread_id`) REFERENCES `ata_thread` (`thread_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `audit_source_file` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `file_name` VARCHAR(512) NOT NULL,
  `media_type` VARCHAR(128) NULL,
  `sha256` CHAR(64) NOT NULL,
  `storage_ref` VARCHAR(1024) NOT NULL,
  `parse_status` VARCHAR(32) NOT NULL DEFAULT 'pending',
  `uploaded_by` VARCHAR(128) NOT NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_audit_source_file_hash` (`engagement_id`, `sha256`),
  KEY `idx_audit_source_file_status` (`engagement_id`, `parse_status`),
  CONSTRAINT `fk_audit_source_file_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `audit_evidence_anchor` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `source_file_id` BIGINT UNSIGNED NOT NULL,
  `anchor_type` VARCHAR(32) NOT NULL,
  `locator_json` JSON NOT NULL,
  `content_text` LONGTEXT NULL,
  `content_hash` CHAR(64) NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_audit_evidence_engagement` (`engagement_id`, `anchor_type`),
  CONSTRAINT `fk_audit_evidence_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`),
  CONSTRAINT `fk_audit_evidence_source`
    FOREIGN KEY (`source_file_id`) REFERENCES `audit_source_file` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `audit_graph_entity` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `entity_type` VARCHAR(64) NOT NULL,
  `entity_key` VARCHAR(255) NOT NULL,
  `display_name` VARCHAR(512) NOT NULL,
  `attributes_json` JSON NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_audit_graph_entity` (`engagement_id`, `entity_type`, `entity_key`),
  CONSTRAINT `fk_audit_graph_entity_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `audit_graph_relation` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `source_entity_id` BIGINT UNSIGNED NOT NULL,
  `target_entity_id` BIGINT UNSIGNED NOT NULL,
  `relation_type` VARCHAR(64) NOT NULL,
  `attributes_json` JSON NULL,
  `evidence_anchor_id` BIGINT UNSIGNED NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_audit_graph_relation_source` (`engagement_id`, `source_entity_id`),
  KEY `idx_audit_graph_relation_target` (`engagement_id`, `target_entity_id`),
  CONSTRAINT `fk_audit_graph_relation_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`),
  CONSTRAINT `fk_audit_graph_relation_source`
    FOREIGN KEY (`source_entity_id`) REFERENCES `audit_graph_entity` (`id`),
  CONSTRAINT `fk_audit_graph_relation_target`
    FOREIGN KEY (`target_entity_id`) REFERENCES `audit_graph_entity` (`id`),
  CONSTRAINT `fk_audit_graph_relation_evidence`
    FOREIGN KEY (`evidence_anchor_id`) REFERENCES `audit_evidence_anchor` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `audit_report` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `report_type` VARCHAR(64) NOT NULL,
  `template_version` VARCHAR(64) NOT NULL,
  `report_version` INT NOT NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'draft',
  `fact_snapshot_json` JSON NOT NULL,
  `artifact_ref` VARCHAR(1024) NULL,
  `created_by` VARCHAR(128) NOT NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_audit_report_version` (`engagement_id`, `report_type`, `report_version`),
  CONSTRAINT `fk_audit_report_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `ata_audit_log` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `actor_user_id` VARCHAR(128) NOT NULL,
  `engagement_id` BIGINT UNSIGNED NULL,
  `action` VARCHAR(128) NOT NULL,
  `target_type` VARCHAR(64) NOT NULL,
  `target_id` VARCHAR(128) NULL,
  `request_id` VARCHAR(128) NULL,
  `details_json` JSON NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_ata_audit_log_engagement` (`engagement_id`, `created_at`),
  KEY `idx_ata_audit_log_actor` (`actor_user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `ata_schema_migration` (`version`, `description`)
VALUES ('001', 'annual audit chat-first isolated storage foundation')
ON DUPLICATE KEY UPDATE `description` = VALUES(`description`);

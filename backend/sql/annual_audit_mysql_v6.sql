-- Annual engagement task management.
CREATE TABLE IF NOT EXISTS `annual_task` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `engagement_id` BIGINT UNSIGNED NOT NULL,
  `task_no` VARCHAR(64) NULL,
  `action` VARCHAR(500) NOT NULL,
  `detail` TEXT NULL,
  `assigned_role` VARCHAR(128) NULL,
  `assigned_to` VARCHAR(128) NULL,
  `deadline` DATE NULL,
  `deliverable` VARCHAR(500) NULL,
  `priority` VARCHAR(16) NOT NULL DEFAULT '中',
  `source_engine` VARCHAR(64) NOT NULL DEFAULT 'annual_audit',
  `status` VARCHAR(32) NOT NULL DEFAULT '待执行',
  `completion_note` TEXT NULL,
  `started_at` DATETIME(6) NULL,
  `completed_at` DATETIME(6) NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  `deleted_at` DATETIME(6) NULL,
  PRIMARY KEY (`id`),
  KEY `idx_annual_task_engagement_status` (`engagement_id`, `status`, `deadline`),
  KEY `idx_annual_task_assignee` (`assigned_to`, `status`),
  CONSTRAINT `fk_annual_task_engagement`
    FOREIGN KEY (`engagement_id`) REFERENCES `audit_engagement` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

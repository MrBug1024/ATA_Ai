-- Generated artifact references can contain several versioned object refs.
-- Use LONGTEXT so the database does not truncate a valid publication manifest.
ALTER TABLE `audit_report`
  MODIFY COLUMN `artifact_ref` LONGTEXT NULL;

ALTER TABLE `annual_workpaper`
  MODIFY COLUMN `artifact_ref` LONGTEXT NULL;

INSERT INTO `ata_schema_migration` (`version`, `description`)
VALUES ('008', 'allow versioned annual report and workpaper artifact manifests')
ON DUPLICATE KEY UPDATE `description` = VALUES(`description`);

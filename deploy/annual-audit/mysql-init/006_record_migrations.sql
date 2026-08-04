-- Docker entrypoint executes the reviewed SQL files directly instead of the
-- Python migration runner.  Record 002-006 only after all preceding scripts
-- have completed successfully.
USE `ata_agent`;

INSERT INTO `ata_schema_migration` (`version`, `description`) VALUES
  ('002', 'annual engagement compatibility and tenancy fields'),
  ('003', 'remove platform persistence tables from annual MySQL'),
  ('004', 'remove platform files evidence and graph tables from annual MySQL'),
  ('005', 'annual audit structured ledgers analysis findings and workpapers'),
  ('006', 'annual engagement task management')
ON DUPLICATE KEY UPDATE `description` = VALUES(`description`);

-- Docker entrypoint executes the reviewed SQL files directly instead of the
-- Python migration runner. Record all compatibility migrations after they
-- have completed successfully.
INSERT INTO `ata_schema_migration` (`version`, `description`) VALUES
  ('002', 'annual engagement compatibility and tenancy fields'),
  ('003', 'remove platform persistence tables from annual MySQL'),
  ('004', 'remove platform files evidence and graph tables from annual MySQL'),
  ('005', 'annual audit structured ledgers analysis findings and workpapers'),
  ('006', 'annual engagement task management'),
  ('007', 'bind annual structured rows to platform evidence anchors'),
  ('008', 'allow versioned annual report and workpaper artifact manifests'),
  ('009', 'annual audit execution, evidence, review, issuance and knowledge governance'),
  ('010', 'immutable annual report citation manifests'),
  ('011', 'immutable annual report citation delivery references'),
  ('012', 'versioned annual-audit templates and confirmed attachment packages'),
  ('013', 'file-backed annual-audit template versions'),
  ('014', 'generic template version and file management'),
  ('015', 'normalize selectable template types and annual-audit type key')
ON DUPLICATE KEY UPDATE `description` = VALUES(`description`);

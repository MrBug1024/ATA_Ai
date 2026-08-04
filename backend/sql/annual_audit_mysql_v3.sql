-- Keep platform persistence on PostgreSQL as in the original architecture.
-- These four tables were introduced before that boundary was clarified and
-- are empty. Annual-audit MySQL remains responsible for domain data only.
USE `ata_agent`;

DROP TABLE IF EXISTS `ata_checkpoint_write`;
DROP TABLE IF EXISTS `ata_conversation_message`;
DROP TABLE IF EXISTS `ata_checkpoint`;
DROP TABLE IF EXISTS `ata_thread`;

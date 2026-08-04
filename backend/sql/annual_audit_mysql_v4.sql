-- Files, evidence anchors and knowledge graphs keep the original PostgreSQL
-- implementation. These empty duplicate tables do not belong in domain MySQL.
USE `ata_agent`;

DROP TABLE IF EXISTS `audit_graph_relation`;
DROP TABLE IF EXISTS `audit_graph_entity`;
DROP TABLE IF EXISTS `audit_evidence_anchor`;
DROP TABLE IF EXISTS `audit_source_file`;

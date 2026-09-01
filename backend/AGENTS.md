# Backend Agent Guide

## Scope

This backend serves the AI accountant annual financial statement audit product only. Preserve the AI-first workflow, evidence traceability, knowledge graph, report generation, authentication, tenancy and administration architecture. Do not add historical business routes, prompts, tools, sample data or database fallbacks.

## Commands

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python -m compileall -q ai_hunter
python -m ai_hunter
```

Only `tests/` is collected by pytest. Runtime configuration comes from `backend/.env`; use `backend/.env.example` as the field reference.

## Architecture

- `ai_hunter/app/main.py`: unified FastAPI entrypoint.
- `ai_hunter/app/graph/main.py`: top-level AI conversation graph.
- `ai_hunter/app/subgraphs/`: annual business-line, ingestion and specialized graphs.
- `ai_hunter/annual_audit/`: deterministic annual project, import, analysis, evidence and report services.
- `ai_hunter/app/prompts/annual_audit_*.txt`: the only runtime prompts.
- `ai_hunter/app/tools/registry.py`: annual drilldown tool registry.
- `sql/annual_audit_*`: annual storage migrations.

The browser and all internal operations use one FastAPI process on `8080`. PostgreSQL stores all annual-audit business and platform data in `POSTGRESQL_DATABASE=ata_ai`. Redis keys must use the annual namespace and Redis is limited to cache and broker duties; MinIO must use the configured online annual buckets. Never fall back to a historical database, bucket, collection or key prefix.

## Engineering Rules

- A positive `case_id` is the compatibility identifier for `audit_engagement.id`.
- The audited entity comes from engagement master data; uploaded files must not override it.
- Reports and workpapers cite source chunks, pages and graph evidence.
- Corrections are persisted as an authoritative ledger and trigger regeneration from source data.
- Large report payloads stay out of chat messages and use heavy-payload storage.
- Register new tools and capabilities centrally and add focused tests.
- Database migrations must be idempotent and restricted to the configured `POSTGRESQL_DATABASE`.

## Change Audit

After edits, list changed files and key diff hunks with the reason for each. The final response must distinguish current changes from pre-existing worktree changes, report tests and real smoke checks, and disclose remaining risks or unverified behavior. For persistence, permissions, SSE, model providers or DDL changes, state whether the service was restarted and whether a live smoke test was completed.

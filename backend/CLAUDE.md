# Backend Guide

- Install: `python -m pip install -e ".[dev]"`
- Run: `uvicorn ai_hunter.app.main:app --host 0.0.0.0 --port 8080`
- Test: `python -m pytest -q`
- Domain: annual financial statement audit only.
- Storage: use the external PostgreSQL, Redis and MinIO services configured by `backend/.env`; the project database is `POSTGRESQL_DATABASE=ata_ai`.
- Never add a fallback connection to a historical project database.
- Keep AI chat, evidence traceability, knowledge graph, report generation, authentication and administration in the unified FastAPI service.

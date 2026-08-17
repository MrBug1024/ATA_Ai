from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_local_compose_uses_dedicated_annual_audit_stores():
    compose = (
        REPO_ROOT / "deploy" / "annual-audit" / "docker-compose.yml"
    ).read_text(encoding="utf-8")

    assert "name: ata-annual-audit-local" in compose
    assert "container_name: ata-annual-postgres" in compose
    assert "container_name: ata-annual-mysql" in compose
    assert "container_name: ata-annual-redis" in compose
    assert "container_name: ata-annual-minio" in compose
    assert "container_name: ata-annual-minio-init" in compose
    assert "${ANNUAL_POSTGRES_PORT:-55432}:5432" in compose
    assert "${ANNUAL_MYSQL_PORT:-53306}:3306" in compose
    assert "${ANNUAL_REDIS_PORT:-56379}:6379" in compose
    assert "${ANNUAL_MINIO_API_PORT:-61000}:9000" in compose
    assert "${ANNUAL_MINIO_CONSOLE_PORT:-61001}:9001" in compose
    assert "name: ata-annual-minio-data" in compose
    assert "annual_audit_mysql_v7.sql:/docker-entrypoint-initdb.d/007_evidence_bindings.sql:ro" in compose
    assert "annual_audit_mysql_v8.sql:/docker-entrypoint-initdb.d/008_artifact_refs.sql:ro" in compose
    assert "annual_audit_mysql_v9.sql:/docker-entrypoint-initdb.d/009_execution_and_knowledge_governance.sql:ro" in compose
    assert "annual_audit_postgres_v2.sql:/docker-entrypoint-initdb.d/062_annual_material_catalog.sql:ro" in compose


def test_annual_postgres_contract_uses_isolated_platform_schema():
    contract = (
        REPO_ROOT
        / "deploy"
        / "annual-audit"
        / "postgres-init"
        / "060_annual_platform_contract.sql"
    ).read_text(encoding="utf-8").lower()

    assert "create table if not exists public.thread_metadata" in contract
    assert "create table if not exists public.doc_category_catalog" in contract
    assert "create table if not exists public.cases" not in contract
    assert "references public.cases" not in contract


def test_local_launcher_prefers_configured_company_minio_and_keeps_local_fallback():
    launcher = (
        REPO_ROOT / "scripts" / "annual-audit-local.ps1"
    ).read_text(encoding="utf-8")
    env_example = (
        REPO_ROOT / "deploy" / "annual-audit" / ".env.example"
    ).read_text(encoding="utf-8")

    assert '$env:BUSINESS_DOMAIN = "annual_audit"' in launcher
    assert '$backendPort = "8080"' in launcher
    assert '$env:APP_PORT = $backendPort' in launcher
    assert '$env:ANNUAL_POSTGRES_DSN' in launcher
    assert 'function Get-BackendSettingValue' in launcher
    assert 'function Use-ConfiguredMySql' in launcher
    assert 'function Use-ConfiguredRedis' in launcher
    assert 'function Use-LocalMinio' in launcher
    assert 'function Use-ForcedLocalServices' in launcher
    assert 'ANNUAL_FORCE_LOCAL_SERVICES' in launcher
    assert 'Explicit process values are used for conflict-free local ports.' in launcher
    assert '[Environment]::GetEnvironmentVariable($name, "Process")' in launcher
    assert 'if (Use-ForcedLocalServices) {' in launcher
    assert 'if (Use-LocalMinio) {' in launcher
    assert '$env:AI_HUNTER_MINIO_ENABLED = "true"' in launcher
    assert 'Remove-Item -Path "Env:$name"' in launcher
    assert '$upServices = @("postgres")' in launcher
    assert '& $Docker @composeArgs run --rm minio-init' in launcher
    assert '[ValidateSet("up", "down", "status", "verify", "migrate", "auth-seed", "seed", "backend")]' in launcher
    assert '"auth-seed" {' in launcher
    assert "must not receive a fabricated engagement or financial data" in launcher
    assert "Invoke-AnnualMigrations" in launcher
    assert '$upServices += "minio"' in launcher
    assert "run --rm minio-init" in launcher
    assert "ANNUAL_MYSQL_DATABASE=ata_ai" in env_example
    assert "ANNUAL_MINIO_BUCKET_RAW=ata-annual-raw" in env_example


def test_annual_task_schema_is_isolated_and_migrated():
    schema = (REPO_ROOT / "backend" / "sql" / "annual_audit_mysql_v6.sql").read_text(
        encoding="utf-8"
    )
    migration = (
        REPO_ROOT
        / "backend"
        / "ai_hunter"
        / "annual_audit"
        / "storage"
        / "migrate.py"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS `annual_task`" in schema
    assert "REFERENCES `audit_engagement` (`id`)" in schema
    assert '"006"' in migration

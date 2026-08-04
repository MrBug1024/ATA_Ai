from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_local_compose_uses_dedicated_annual_audit_stores():
    compose = (
        REPO_ROOT / "deploy" / "annual-audit" / "docker-compose.yml"
    ).read_text(encoding="utf-8")

    assert "name: ata-agent-local" in compose
    assert "container_name: ata-agent-postgres" in compose
    assert "container_name: ata-agent-mysql" in compose
    assert "container_name: ata-agent-redis" in compose
    assert "container_name: ata-agent-minio" in compose
    assert "container_name: ata-agent-minio-init" in compose
    assert "${ANNUAL_POSTGRES_PORT:-55432}:5432" in compose
    assert "${ANNUAL_MYSQL_PORT:-53306}:3306" in compose
    assert "${ANNUAL_REDIS_PORT:-56379}:6379" in compose
    assert "${ANNUAL_MINIO_API_PORT:-61000}:9000" in compose
    assert "${ANNUAL_MINIO_CONSOLE_PORT:-61001}:9001" in compose
    assert "name: ata-agent-minio-data" in compose
    assert "annual_audit_mysql_v6.sql:/docker-entrypoint-initdb.d/006_annual_tasks.sql:ro" in compose


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


def test_local_launcher_forces_annual_mode_on_the_single_backend_port():
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
    assert '$env:AI_HUNTER_MINIO_ENABLED = "true"' in launcher
    assert '[ValidateSet("up", "down", "status", "verify", "migrate", "seed", "backend")]' in launcher
    assert "Invoke-AnnualMigrations" in launcher
    assert "up -d --wait postgres mysql redis minio" in launcher
    assert "run --rm minio-init" in launcher
    assert "ANNUAL_MYSQL_DATABASE=ata_agent" in env_example
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

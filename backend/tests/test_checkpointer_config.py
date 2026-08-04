from ai_hunter.app.settings import Settings


def _settings(dsn: str) -> Settings:
    return Settings(
        _env_file=None,
        annual_mysql_database="ata_agent",
        annual_postgres_database="ata_agent_platform",
        annual_postgres_dsn=dsn,
        annual_redis_password="",
    )


def test_postgres_checkpointer_dsn_normalizes_sqlalchemy_scheme():
    settings = _settings(
        "postgresql+psycopg://ata_agent_app:secret@127.0.0.1:55432/ata_agent_platform"
    )
    assert settings.postgres_checkpointer_dsn == (
        "postgresql://ata_agent_app:secret@127.0.0.1:55432/ata_agent_platform"
    )


def test_postgres_checkpointer_dsn_keeps_plain_postgres_scheme():
    dsn = "postgresql://ata_agent_app:secret@127.0.0.1:55432/ata_agent_platform"
    assert _settings(dsn).postgres_checkpointer_dsn == dsn

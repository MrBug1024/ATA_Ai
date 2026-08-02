from ai_hunter.app.settings import Settings


def test_postgres_checkpointer_dsn_normalizes_sqlalchemy_scheme():
    settings = Settings(
        postgres_dsn="postgresql+psycopg://postgres:secret@127.0.0.1:5432/ai_hunter"
    )

    assert settings.postgres_checkpointer_dsn == "postgresql://postgres:secret@127.0.0.1:5432/ai_hunter"


def test_postgres_checkpointer_dsn_keeps_plain_postgres_scheme():
    settings = Settings(postgres_dsn="postgresql://postgres:secret@127.0.0.1:5432/ai_hunter")

    assert settings.postgres_checkpointer_dsn == "postgresql://postgres:secret@127.0.0.1:5432/ai_hunter"

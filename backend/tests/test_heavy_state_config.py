from ai_hunter.app.settings import Settings


def test_heavy_payload_settings_defaults_are_exposed():
    settings = Settings(_env_file=None, annual_mysql_database="ata_ai", annual_redis_password="")
    assert settings.heavy_payload_ttl_seconds == 86400
    assert settings.heavy_payload_enable_postgres is True


def test_redis_url_is_derived_from_isolated_annual_settings():
    settings = Settings(
        _env_file=None,
        annual_mysql_database="ata_ai",
        heavy_payload_ttl_seconds=3600,
        heavy_payload_enable_postgres=False,
        annual_redis_port=56380,
        annual_redis_password="annual-secret",
    )
    assert settings.heavy_payload_ttl_seconds == 3600
    assert settings.heavy_payload_enable_postgres is False
    assert settings.redis_url == "redis://:annual-secret@127.0.0.1:56380/0"

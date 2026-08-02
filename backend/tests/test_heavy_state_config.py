from ai_hunter.app.settings import Settings


def test_heavy_payload_settings_defaults_are_exposed():
    settings = Settings()

    assert settings.heavy_payload_ttl_seconds == 86400
    assert settings.heavy_payload_enable_postgres is True


def test_heavy_payload_settings_allow_env_style_override():
    settings = Settings(
        heavy_payload_ttl_seconds=3600,
        heavy_payload_enable_postgres=False,
        redis_url="redis://10.0.10.2:6379/0",
    )

    assert settings.heavy_payload_ttl_seconds == 3600
    assert settings.heavy_payload_enable_postgres is False
    assert settings.redis_url == "redis://10.0.10.2:6379/0"

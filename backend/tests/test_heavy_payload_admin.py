from ai_hunter.app.services.heavy_payload_admin import prune_heavy_payloads
from ai_hunter.app.settings import get_settings


def test_prune_heavy_payloads_dry_run_without_matches():
    result = prune_heavy_payloads(
        dry_run=True,
        payload_type="__unlikely_payload_type__",
        older_than_seconds=1,
        limit=5,
    )

    assert result["dry_run"] is True
    assert result["payload_type"] == "__unlikely_payload_type__"
    assert result["candidate_count"] == 0
    assert result["candidates"] == []


def test_heavy_payload_prune_batch_size_setting_is_exposed():
    settings = get_settings()

    assert settings.heavy_payload_prune_batch_size == 500

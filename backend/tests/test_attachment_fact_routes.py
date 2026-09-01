from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_hunter.app.api import routes_artifacts


def _identity():
    return SimpleNamespace(user_id="reviewer-1", is_admin=True, roles=())


def _payload(*, source_sha256: str = "a" * 64):
    return routes_artifacts.FactUpsertRequest(
        value="3000000",
        display_value="300万元",
        data_type="number",
        status="confirmed",
        source_kind="manual_review",
        evidence_refs=[
            {
                "source_file_id": 91,
                "source_sha256": source_sha256,
                "source_locator": {"page_no": 2},
            }
        ],
    )


def test_fact_route_rejects_evidence_without_immutable_source_hash(monkeypatch) -> None:
    monkeypatch.setattr(routes_artifacts, "require_case_access", lambda *_args: None)
    monkeypatch.setattr(
        routes_artifacts,
        "validate_evidence_ownership",
        lambda *_args, **_kwargs: [],
    )
    called = False

    def fail_if_persisted(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(routes_artifacts.repository, "upsert_fact_version", fail_if_persisted)

    with pytest.raises(HTTPException) as caught:
        routes_artifacts.put_engagement_fact(
            7,
            "entity.registered_capital",
            _payload(source_sha256=""),
            _identity(),
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "FACT_EVIDENCE_INVALID"
    assert called is False


def test_fact_route_rejects_cross_case_or_stale_evidence(monkeypatch) -> None:
    monkeypatch.setattr(routes_artifacts, "require_case_access", lambda *_args: None)
    monkeypatch.setattr(
        routes_artifacts,
        "validate_evidence_ownership",
        lambda *_args, **_kwargs: ["证据文件 91 不属于当前项目或已失效"],
    )
    monkeypatch.setattr(
        routes_artifacts.repository,
        "upsert_fact_version",
        lambda **_kwargs: pytest.fail("invalid evidence must not be persisted"),
    )

    with pytest.raises(HTTPException) as caught:
        routes_artifacts.put_engagement_fact(
            7,
            "entity.registered_capital",
            _payload(),
            _identity(),
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "FACT_EVIDENCE_INVALID"


def test_fact_route_persists_only_case_owned_hash_bound_evidence(monkeypatch) -> None:
    monkeypatch.setattr(routes_artifacts, "require_case_access", lambda *_args: None)
    observed = {}

    def validate(case_id, refs):
        observed["validation"] = (case_id, refs)
        return []

    def persist(**kwargs):
        observed["persisted"] = kwargs
        return {"id": 17, "revision": 1}

    monkeypatch.setattr(routes_artifacts, "validate_evidence_ownership", validate)
    monkeypatch.setattr(routes_artifacts.repository, "upsert_fact_version", persist)

    result = routes_artifacts.put_engagement_fact(
        7,
        "entity.registered_capital",
        _payload(),
        _identity(),
    )

    assert result == {"id": 17, "revision": 1}
    assert observed["validation"][0] == 7
    assert observed["persisted"]["engagement_id"] == 7
    assert observed["persisted"]["evidence_refs"][0]["source_sha256"] == "a" * 64

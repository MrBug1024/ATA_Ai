from types import SimpleNamespace

import pytest

from ai_hunter.platform_core import scoped_object_key, scoped_redis_key, validate_domain
from ai_hunter.app.services.vector_search import _embedding_literal


def _settings():
    return SimpleNamespace(
        business_domain="annual_audit",
        annual_redis_namespace="ata:online:",
        annual_minio_prefix="annual_audit",
    )


def test_shared_services_receive_annual_domain_and_project_scope():
    settings = _settings()

    assert scoped_redis_key(settings, "heavy", "final_report", "abc") == (
        "ata:online:annual_audit:heavy:final_report:abc"
    )
    assert scoped_object_key(
        settings,
        project_id=7,
        category="artifacts",
        parts=("annual-audit-7-v1.docx",),
    ) == "annual_audit/project-7/artifacts/annual-audit-7-v1.docx"


def test_domain_scope_is_explicit_and_legacy_domain_cannot_collide():
    with pytest.raises(ValueError):
        validate_domain("npa", expected="annual_audit")

    settings = SimpleNamespace(
        business_domain="npa",
        annual_redis_namespace="ata:online:",
        annual_minio_prefix="annual_audit",
    )
    assert scoped_redis_key(settings, "heavy", "payload") == "ata:online:npa:heavy:payload"
    assert scoped_redis_key(settings, "heavy", "payload") != (
        "ata:online:annual_audit:heavy:payload"
    )


def test_vector_query_contract_validates_dimension_and_finite_values():
    assert _embedding_literal([0.1, 0.2], dimension=2) == "[0.1,0.2]"
    with pytest.raises(ValueError):
        _embedding_literal([0.1], dimension=2)
    with pytest.raises(ValueError):
        _embedding_literal([float("nan")], dimension=1)

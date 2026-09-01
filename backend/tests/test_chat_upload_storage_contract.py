from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_hunter.app.api import _upload_helpers
from ai_hunter.app.services.minio_service import build_raw_object_key


class _Minio:
    def __init__(self, size: int) -> None:
        self.size = size
        self.seen: list[str] = []

    def stat_object(self, storage_ref: str):
        self.seen.append(storage_ref)
        return SimpleNamespace(size=self.size)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        business_domain="annual_audit",
        annual_minio_prefix="annual_audit",
        annual_minio_bucket_raw="raw",
    )


def _file_item(*, case_id: int = 7, content: str = "") -> dict[str, object]:
    file_hash = "a" * 64
    key = build_raw_object_key(
        case_id=case_id,
        entity_id=9,
        file_name="trial balance.csv",
        content_sha256=file_hash,
        settings=_settings(),
    )
    storage_ref = f"minio://raw/{key}"
    return {
        "name": "trial balance.csv",
        "content": content,
        "content_ref": storage_ref,
        "storage_ref": storage_ref,
        "storage_provider": "minio",
        "storage_bucket": "raw",
        "storage_key": key,
        "file_hash": file_hash,
        "file_size": 12,
    }


def test_raw_object_key_is_content_addressed() -> None:
    key = build_raw_object_key(
        case_id=7,
        entity_id=9,
        file_name="trial balance.csv",
        content_sha256="a" * 64,
        settings=_settings(),
    )

    assert key == "annual_audit/project-7/raw/entity-9/" + ("a" * 64)

    unicode_key = build_raw_object_key(
        case_id=7,
        entity_id=0,
        entity_name="北京有限公司",
        file_name="审计报告.docx",
        content_sha256="b" * 64,
        settings=_settings(),
    )
    assert unicode_key.endswith("/" + ("b" * 64))
    assert "%" not in unicode_key
    assert unicode_key.isascii()

    with pytest.raises(ValueError, match="content_sha256"):
        build_raw_object_key(
            case_id=7,
            entity_id=9,
            file_name="trial balance.csv",
            content_sha256="not-a-sha",
            settings=_settings(),
        )


def test_chat_file_contract_accepts_only_current_case_raw_object(monkeypatch) -> None:
    minio = _Minio(size=12)
    monkeypatch.setattr(_upload_helpers, "get_minio_service", lambda: minio)
    monkeypatch.setattr(
        _upload_helpers,
        "resolve_minio_reference_url",
        lambda storage_ref: f"https://object.example/{storage_ref.removeprefix('minio://')}",
    )

    validated = _upload_helpers.validate_chat_uploaded_file_items(
        [_file_item()],
        case_id=7,
        settings=_settings(),
    )

    assert minio.seen == [validated[0]["storage_ref"]]
    assert validated[0]["content"] == ""
    assert validated[0]["storage_provider"] == "minio"


@pytest.mark.parametrize(
    ("item", "case_id", "status_code"),
    [
        (_file_item(case_id=8), 7, 403),
        (_file_item(content="inline content"), 7, 422),
    ],
)
def test_chat_file_contract_rejects_untrusted_payloads(
    monkeypatch,
    item: dict[str, object],
    case_id: int,
    status_code: int,
) -> None:
    monkeypatch.setattr(_upload_helpers, "get_minio_service", lambda: _Minio(size=12))

    with pytest.raises(HTTPException) as caught:
        _upload_helpers.validate_chat_uploaded_file_items(
            [item],
            case_id=case_id,
            settings=_settings(),
        )

    assert caught.value.status_code == status_code

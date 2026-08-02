"""Shared helpers for /chat/upload-files and /files/upload-and-ingest.

Encapsulates the UploadFile -> FileItem normalization so the chat path
(POST /chat/upload-files, sync, MinIO only) and the operator path
(POST /files/upload-and-ingest, 202 async, full ingest) share the same
storage layout and the same debtor-name resolution strategy.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile

from ..auth.identity import Identity
from ..graph.state import FileItem
from ..services.case_api import get_case_api_client
from ..services.minio_service import get_minio_service, resolve_minio_reference_url
from ..settings import Settings


_PLAIN_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv"}


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DebtorResolution:
    debtor_id: int
    debtor_name: str
    source: str


def _normalize_party_name(value: str) -> str:
    return "".join(str(value or "").split())


def _profile_debtors(profile: object) -> list[tuple[int, str]]:
    if not isinstance(profile, dict):
        return []
    rows = profile.get("debtors")
    if not isinstance(rows, list):
        return []
    debtors: list[tuple[int, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            resolved_id = int(row.get("debtor_id") or 0)
        except (TypeError, ValueError):
            continue
        resolved_name = str(row.get("entity_name") or row.get("name") or "").strip()
        if resolved_id > 0 and resolved_name:
            debtors.append((resolved_id, resolved_name))
    return debtors


def resolve_effective_debtor(
    *,
    case_id: int,
    debtor_id: int = 0,
    debtor_name: str = "",
    identity: Identity | None = None,
) -> DebtorResolution:
    """Resolve one upload debtor from authoritative case-profile data.

    Priority: exact debtor_id -> exact debtor_name -> the only case debtor.
    Parties with non-debtor roles are intentionally ignored.
    """
    if int(case_id or 0) <= 0:
        raise HTTPException(status_code=400, detail="上传前必须先选择有效案件")
    try:
        profile = get_case_api_client().get_case_profile_sync(int(case_id), identity=identity)
    except Exception as exc:
        _LOGGER.error(
            "debtor_name_resolve_failed case_id=%s error=%s", case_id, exc,
        )
        raise HTTPException(status_code=502, detail="案件债务人主数据暂不可用，已停止上传") from exc

    debtors = _profile_debtors(profile)
    requested_id = int(debtor_id or 0)
    requested_name = str(debtor_name or "").strip()

    if requested_id > 0:
        matches = [item for item in debtors if item[0] == requested_id]
        if not matches:
            raise HTTPException(status_code=409, detail="debtor_id 不属于当前案件")
        resolved_id, resolved_name = matches[0]
        if requested_name and _normalize_party_name(requested_name) != _normalize_party_name(resolved_name):
            raise HTTPException(status_code=409, detail="debtor_name 与 debtor_id 对应的案件主数据不一致")
        return DebtorResolution(resolved_id, resolved_name, "debtor_id")

    if requested_name:
        normalized = _normalize_party_name(requested_name)
        matches = [item for item in debtors if _normalize_party_name(item[1]) == normalized]
        if not matches:
            raise HTTPException(status_code=409, detail="debtor_name 与当前案件主数据不一致")
        if len(matches) > 1:
            raise HTTPException(status_code=409, detail="同名债务人不唯一，请显式传入 debtor_id")
        return DebtorResolution(matches[0][0], matches[0][1], "debtor_name")

    if len(debtors) == 1:
        return DebtorResolution(debtors[0][0], debtors[0][1], "single_case_debtor")
    if not debtors:
        raise HTTPException(status_code=409, detail="当前案件尚未建立有效债务人")
    raise HTTPException(status_code=409, detail="当前案件存在多个债务人，请显式传入 debtor_id")


def resolve_effective_debtor_name(
    *,
    case_id: int,
    debtor_id: int = 0,
    debtor_name: str = "",
    identity: Identity | None = None,
) -> str:
    """Compatibility wrapper returning only the authoritative debtor name."""
    return resolve_effective_debtor(
        case_id=case_id,
        debtor_id=debtor_id,
        debtor_name=debtor_name,
        identity=identity,
    ).debtor_name


async def to_file_item(
    upload: UploadFile,
    settings: Settings,
    logger: logging.LoggerAdapter,
    *,
    current_case_id: int,
    current_debtor_id: int = 0,
    debtor_name: str = "",
    doc_category: str = "",
    upload_batch_id: str = "",
    populate_content: bool = False,
) -> FileItem:
    """Convert one FastAPI UploadFile into the graph's normalized FileItem shape.

    When ``ai_hunter_minio_enabled`` is true, the bytes are uploaded to MinIO
    and the storage_* fields are filled.

    ``populate_content`` controls the legacy ``content`` field:
    - True: fill ``content`` with the inlined base64 / text payload (matches
      the pre-refactor behavior used by the 202 async path so the OCR
      pipeline keeps working when MinIO is disabled).
    - False (default): leave ``content`` empty so downstream graph nodes
      re-fetch via ``storage_ref`` (used by the chat path to keep
      LangGraph state lean).
    """
    file_bytes = await upload.read()
    file_name = upload.filename or "uploaded-file"
    extension = Path(file_name).suffix.lower()
    content_type = upload.content_type or ""
    file_size_mb = len(file_bytes) / (1024 * 1024)
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    if file_size_mb > settings.max_upload_file_mb:
        raise HTTPException(
            status_code=400,
            detail=f"文件 {file_name} 超过 {settings.max_upload_file_mb}MB 限制。",
        )
    file_type = _classify_upload_type(extension, content_type)
    if file_type == "image" and file_size_mb > settings.max_image_file_mb:
        raise HTTPException(
            status_code=400,
            detail=f"图片文件 {file_name} 超过 {settings.max_image_file_mb}MB 限制。",
        )

    storage_payload = {
        "storage_ref": "",
        "storage_provider": "",
        "storage_bucket": "",
        "storage_key": "",
        "storage_etag": "",
        "storage_version": "",
    }
    if settings.ai_hunter_minio_enabled:
        uploaded = get_minio_service().upload_raw_file(
            case_id=current_case_id,
            debtor_id=current_debtor_id,
            file_name=file_name,
            content_type=content_type,
            file_bytes=file_bytes,
            debtor_name=debtor_name,
        )
        storage_payload = {
            "storage_ref": uploaded.storage_ref,
            "storage_provider": uploaded.storage_provider,
            "storage_bucket": uploaded.storage_bucket,
            "storage_key": uploaded.storage_key,
            "storage_etag": uploaded.storage_etag,
            "storage_version": uploaded.storage_version,
        }

    if populate_content:
        if extension in _PLAIN_TEXT_EXTENSIONS:
            content_payload = file_bytes.decode("utf-8", errors="replace")
        else:
            content_payload = base64.b64encode(file_bytes).decode("utf-8")
    else:
        content_payload = ""

    logger.info(
        "file_normalized name=%s hash=%s case_id=%s debtor_name=%s storage_ref=%s populate_content=%s",
        file_name,
        file_hash[:12],
        current_case_id,
        debtor_name,
        storage_payload["storage_ref"],
        populate_content,
    )
    return {
        "name": file_name,
        "url": resolve_minio_reference_url(storage_payload["storage_ref"]),
        "type": file_type,
        "extension": extension,
        "content_type": content_type,
        "content": content_payload,
        "content_ref": storage_payload["storage_ref"],
        "doc_category": doc_category,
        "upload_batch_id": upload_batch_id,
        "file_hash": file_hash,
        "file_size": len(file_bytes),
        **storage_payload,
    }


def _classify_upload_type(extension: str, content_type: str) -> str:
    image_extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
    if extension in image_extensions or content_type.startswith("image/"):
        return "image"
    return "document"


def resolve_upload_batch_id(upload_batch_id: str) -> str:
    """Normalize a caller-provided batch id; generate a local one when empty."""
    normalized = (upload_batch_id or "").strip()
    if normalized:
        return normalized
    return f"local-{uuid.uuid4().hex[:12]}"

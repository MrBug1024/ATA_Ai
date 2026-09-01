"""Shared helpers for /chat/upload-files and /files/upload-and-ingest.

Encapsulates the UploadFile -> FileItem normalization so the chat path
(POST /chat/upload-files, sync, MinIO only) and the operator path
(POST /files/upload-and-ingest, 202 async, full ingest) share the same
storage layout and the same audited-entity resolution strategy.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, UploadFile

from ..auth.identity import Identity
from ..graph.state import FileItem
from ..services.minio_service import get_minio_service, resolve_minio_reference_url
from ..settings import Settings
from ...annual_audit.engagement_repository import get_engagement_profile
from ...platform_core import scoped_object_key


_PLAIN_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


_LOGGER = logging.getLogger(__name__)


def _load_engagement_profile(
    case_id: int,
    *,
    identity: Identity | None = None,
) -> dict:
    """Load an annual engagement directly without self-calling FastAPI."""

    return get_engagement_profile(int(case_id))


@dataclass(frozen=True)
class EngagementEntityResolution:
    entity_id: int
    entity_name: str
    source: str


def _normalize_party_name(value: str) -> str:
    return "".join(str(value or "").split())


def _profile_audited_entity(profile: object) -> tuple[int, str] | None:
    if not isinstance(profile, dict):
        return None
    annual = profile.get("annual_audit") or {}
    case = profile.get("case") or {}
    try:
        entity_id = int(case.get("case_id") or 0)
    except (TypeError, ValueError):
        return None
    entity_name = str(annual.get("entity_name") or "").strip()
    return (entity_id, entity_name) if entity_id > 0 and entity_name else None


def resolve_engagement_entity(
    *,
    case_id: int,
    entity_id: int = 0,
    entity_name: str = "",
    identity: Identity | None = None,
) -> EngagementEntityResolution:
    """Resolve the audited entity for an upload from engagement master data."""
    if int(case_id or 0) <= 0:
        raise HTTPException(status_code=400, detail="上传前必须先选择有效年审项目")
    try:
        profile = _load_engagement_profile(int(case_id), identity=identity)
    except Exception as exc:
        _LOGGER.error(
            "audited_entity_resolve_failed project_id=%s error=%s", case_id, exc,
        )
        raise HTTPException(status_code=502, detail="年审项目主数据暂不可用，已停止上传") from exc

    entity = _profile_audited_entity(profile)
    if entity is None:
        raise HTTPException(status_code=409, detail="年审项目缺少有效的被审计单位")
    resolved_id, resolved_name = entity
    requested_id = int(entity_id or 0)
    requested_name = str(entity_name or "").strip()

    if requested_id > 0 and requested_id != resolved_id:
        raise HTTPException(status_code=409, detail="实体编号不属于当前年审项目")
    if requested_name and _normalize_party_name(requested_name) != _normalize_party_name(resolved_name):
        raise HTTPException(status_code=409, detail="被审计单位名称与年审项目主数据不一致")
    source = "entity_id" if requested_id > 0 else "entity_name" if requested_name else "engagement"
    return EngagementEntityResolution(resolved_id, resolved_name, source)


async def to_file_item(
    upload: UploadFile,
    settings: Settings,
    logger: logging.LoggerAdapter,
    *,
    current_case_id: int,
    current_entity_id: int = 0,
    entity_name: str = "",
    doc_category: str = "",
    upload_batch_id: str = "",
    populate_content: bool = False,
) -> FileItem:
    """Convert one FastAPI UploadFile into the graph's normalized FileItem shape.

    File bytes are always written to the configured online MinIO service and
    the storage_* fields are filled.

    ``populate_content`` controls the inline ``content`` field:
    - True: fill ``content`` with the inlined base64 / text payload (matches
      the payload used by the 202 async path while durable storage remains
      MinIO-backed).
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

    if not settings.annual_minio_enabled:
        raise HTTPException(
            status_code=503,
            detail="线上 MinIO 未启用，已拒绝写入非标准文件存储",
        )
    uploaded = get_minio_service().upload_raw_file(
        case_id=current_case_id,
        entity_id=current_entity_id,
        file_name=file_name,
        content_type=content_type,
        file_bytes=file_bytes,
        entity_name=entity_name,
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
        "file_normalized name=%s hash=%s project_id=%s entity_name=%s storage_ref=%s populate_content=%s",
        file_name,
        file_hash[:12],
        current_case_id,
        entity_name,
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


def validate_chat_uploaded_file_items(
    uploaded_files: list[FileItem],
    *,
    case_id: int,
    settings: Settings,
) -> list[FileItem]:
    """Validate client-returned chat file descriptors against the raw MinIO scope.

    ``/chat/upload-files`` does not persist a source-file row yet, so its
    durable authorization boundary is the configured raw bucket and the
    annual-project path. The returned descriptor must be replayed unchanged;
    arbitrary object buckets, other projects, URL references and inline bytes
    are not valid chat inputs.
    """

    if int(case_id or 0) <= 0:
        raise HTTPException(status_code=400, detail="上传资料必须绑定有效年审项目")

    expected_bucket = settings.annual_minio_bucket_raw.strip()
    expected_prefix = (
        scoped_object_key(settings, project_id=int(case_id), category="raw").rstrip("/")
        + "/"
    )
    minio = get_minio_service()
    normalized_files: list[FileItem] = []

    for raw_item in uploaded_files:
        item = dict(raw_item)
        storage_ref = str(item.get("storage_ref") or "").strip()
        content_ref = str(item.get("content_ref") or "").strip()
        if not storage_ref or content_ref != storage_ref:
            raise HTTPException(status_code=422, detail="对话文件必须使用服务端返回的 MinIO storage_ref")
        if str(item.get("storage_provider") or "").strip().lower() != "minio":
            raise HTTPException(status_code=422, detail="对话文件仅支持 MinIO 对象存储")
        if str(item.get("content") or "").strip():
            raise HTTPException(status_code=422, detail="对话文件不接受内联文本或 Base64 内容")

        parsed = urlsplit(storage_ref)
        bucket = parsed.netloc.strip("/")
        key = parsed.path.lstrip("/")
        if (
            parsed.scheme != "minio"
            or parsed.query
            or parsed.fragment
            or not bucket
            or not key
            or storage_ref != f"minio://{bucket}/{key}"
        ):
            raise HTTPException(status_code=422, detail="对话文件 storage_ref 格式无效")
        if bucket != expected_bucket or str(item.get("storage_bucket") or "").strip() != bucket:
            raise HTTPException(status_code=422, detail="对话文件不属于配置的原始资料桶")
        if str(item.get("storage_key") or "").strip() != key:
            raise HTTPException(status_code=422, detail="对话文件 MinIO 元数据不一致")
        if not key.startswith(expected_prefix):
            raise HTTPException(status_code=403, detail="对话文件不属于当前年审项目")

        file_name = str(item.get("name") or "").strip()
        file_hash = str(item.get("file_hash") or "").strip().lower()
        if not _SHA256_RE.fullmatch(file_hash):
            raise HTTPException(status_code=422, detail="对话文件缺少有效 SHA-256")
        if not file_name or key.rsplit("/", 1)[-1] != file_hash:
            raise HTTPException(status_code=422, detail="对话文件 SHA-256 与 MinIO 对象不一致")

        try:
            object_stat = minio.stat_object(storage_ref)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="对话文件的 MinIO 对象不存在或不可读取") from exc
        actual_size = int(getattr(object_stat, "size", -1))
        reported_size = item.get("file_size")
        try:
            normalized_size = int(reported_size)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="对话文件大小无效") from None
        if actual_size < 0 or normalized_size != actual_size:
            raise HTTPException(status_code=422, detail="对话文件大小与 MinIO 对象不一致")

        normalized_files.append(
            {
                **item,
                "content": "",
                "content_ref": storage_ref,
                "storage_ref": storage_ref,
                "storage_provider": "minio",
                "storage_bucket": bucket,
                "storage_key": key,
                "url": resolve_minio_reference_url(storage_ref),
                "file_hash": file_hash,
                "file_size": actual_size,
            }
        )
    return normalized_files

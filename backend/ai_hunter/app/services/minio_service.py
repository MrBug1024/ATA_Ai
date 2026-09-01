"""MinIO service used for raw-case-file persistence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from urllib.parse import quote, urlsplit

from ...platform_core import scoped_object_key, validate_domain
from ..settings import get_settings


@dataclass
class MinioUploadResult:
    """Structured upload result returned to file-ingest flows."""

    storage_provider: str
    storage_bucket: str
    storage_key: str
    storage_etag: str
    storage_version: str

    @property
    def storage_ref(self) -> str:
        return f"minio://{self.storage_bucket}/{self.storage_key}"


class MinioService:
    """Thin wrapper around the MinIO Python client for AI Hunter buckets."""

    def __init__(self) -> None:
        settings = get_settings()
        self.enabled = settings.annual_minio_enabled
        self.bucket_raw = settings.annual_minio_bucket_raw
        self.bucket_derived = settings.annual_minio_bucket_derived
        self.bucket_artifacts = settings.annual_minio_bucket_artifacts
        self.bucket_templates = settings.annual_minio_bucket_templates
        try:
            from minio import Minio
        except ModuleNotFoundError as exc:
            raise RuntimeError("minio package is not installed") from exc
        endpoint_text = settings.annual_minio_endpoint.strip().rstrip("/")
        endpoint_parts = urlsplit(
            endpoint_text if "://" in endpoint_text else f"//{endpoint_text}"
        )
        endpoint = endpoint_parts.netloc or endpoint_parts.path
        secure = settings.annual_minio_use_ssl or endpoint_parts.scheme.lower() == "https"
        if not endpoint:
            raise RuntimeError("ANNUAL_MINIO_ENDPOINT is not configured")
        self.client = Minio(
            endpoint,
            access_key=settings.annual_minio_access_key,
            secret_key=settings.annual_minio_secret_key,
            secure=secure,
        )

    def upload_raw_file(
        self,
        *,
        case_id: int,
        entity_id: int,
        file_name: str,
        content_type: str,
        file_bytes: bytes,
        entity_name: str = "",
    ) -> MinioUploadResult:
        """Upload one raw case file to the configured raw bucket."""
        settings = get_settings()
        if not self.enabled:
            raise RuntimeError("ANNUAL_MINIO_ENABLED is false")
        if not self.bucket_raw:
            raise RuntimeError("ANNUAL_MINIO_BUCKET_RAW is not configured")

        content_sha256 = hashlib.sha256(file_bytes).hexdigest()
        object_key = build_raw_object_key(
            case_id=case_id,
            entity_id=entity_id,
            file_name=file_name,
            entity_name=entity_name,
            content_sha256=content_sha256,
            settings=settings,
        )
        self._ensure_bucket(self.bucket_raw)
        result = self.client.put_object(
            self.bucket_raw,
            object_key,
            data=BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type or _guess_content_type(file_name),
            metadata={"content-sha256": content_sha256},
        )
        return MinioUploadResult(
            storage_provider="minio",
            storage_bucket=self.bucket_raw,
            storage_key=object_key,
            storage_etag=result.etag or "",
            storage_version=result.version_id or "",
        )

    def upload_artifact(
        self,
        *,
        project_id: int,
        file_name: str,
        content_type: str,
        file_bytes: bytes,
    ) -> MinioUploadResult:
        """Upload a generated annual-audit artifact into the isolated bucket."""

        if not self.enabled:
            raise RuntimeError("ANNUAL_MINIO_ENABLED is false")
        if not self.bucket_artifacts:
            raise RuntimeError("ANNUAL_MINIO_BUCKET_ARTIFACTS is not configured")
        object_key = scoped_object_key(
            get_settings(),
            project_id=project_id,
            category="artifacts",
            parts=(Path(file_name).name,),
        )
        self._ensure_bucket(self.bucket_artifacts)
        result = self.client.put_object(
            self.bucket_artifacts,
            object_key,
            data=BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type or "application/octet-stream",
        )
        return MinioUploadResult(
            storage_provider="minio",
            storage_bucket=self.bucket_artifacts,
            storage_key=object_key,
            storage_etag=result.etag or "",
            storage_version=result.version_id or "",
        )

    def upload_template(
        self,
        *,
        template_version_id: str,
        template_file_id: str,
        file_name: str,
        content_type: str,
        file_bytes: bytes,
        variant: str,
    ) -> MinioUploadResult:
        """Store an immutable template source, compiled file, or preview."""

        if variant not in {"source", "compiled", "preview"}:
            raise ValueError("template variant must be source, compiled, or preview")
        if not self.enabled:
            raise RuntimeError("ANNUAL_MINIO_ENABLED is false")
        if not self.bucket_templates:
            raise RuntimeError("ANNUAL_MINIO_BUCKET_TEMPLATES is not configured")
        version_id = _safe_identifier(template_version_id, "template_version_id")
        file_id = _safe_identifier(template_file_id, "template_file_id")
        safe_name = quote(Path(file_name or "template-file").name, safe="")
        object_key = (
            f"templates/{version_id}/{file_id}/{variant}/"
            f"{uuid4().hex}-{safe_name}"
        )
        return self._put_bytes(
            bucket=self.bucket_templates,
            object_key=object_key,
            content_type=content_type,
            file_bytes=file_bytes,
            metadata={"template-variant": variant},
        )

    def upload_attachment_blob(
        self,
        *,
        project_id: int,
        blob_id: str,
        category: str,
        file_name: str,
        content_type: str,
        file_bytes: bytes,
    ) -> MinioUploadResult:
        """Store one immutable generation payload, artifact, or manifest."""

        if category not in {"contexts", "payloads", "artifacts", "manifests", "quality"}:
            raise ValueError("unsupported attachment blob category")
        if not self.enabled:
            raise RuntimeError("ANNUAL_MINIO_ENABLED is false")
        if not self.bucket_artifacts:
            raise RuntimeError("ANNUAL_MINIO_BUCKET_ARTIFACTS is not configured")
        safe_blob_id = _safe_identifier(blob_id, "blob_id")
        content_sha256 = hashlib.sha256(file_bytes).hexdigest()
        object_key = scoped_object_key(
            get_settings(),
            project_id=project_id,
            category=category,
            parts=(safe_blob_id, f"{content_sha256}-{quote(Path(file_name).name, safe='')}"),
        )
        return self._put_bytes(
            bucket=self.bucket_artifacts,
            object_key=object_key,
            content_type=content_type,
            file_bytes=file_bytes,
        )

    def upload_derived_blob(
        self,
        *,
        project_id: int,
        blob_id: str,
        file_name: str,
        content_type: str,
        file_bytes: bytes,
    ) -> MinioUploadResult:
        """Store a preview or thumbnail separately from deliverable files."""

        if not self.enabled:
            raise RuntimeError("ANNUAL_MINIO_ENABLED is false")
        if not self.bucket_derived:
            raise RuntimeError("ANNUAL_MINIO_BUCKET_DERIVED is not configured")
        safe_blob_id = _safe_identifier(blob_id, "blob_id")
        content_sha256 = hashlib.sha256(file_bytes).hexdigest()
        object_key = scoped_object_key(
            get_settings(),
            project_id=project_id,
            category="attachment-previews",
            parts=(safe_blob_id, f"{content_sha256}-{quote(Path(file_name).name, safe='')}"),
        )
        return self._put_bytes(
            bucket=self.bucket_derived,
            object_key=object_key,
            content_type=content_type,
            file_bytes=file_bytes,
        )

    def _put_bytes(
        self,
        *,
        bucket: str,
        object_key: str,
        content_type: str,
        file_bytes: bytes,
        metadata: dict[str, str] | None = None,
    ) -> MinioUploadResult:
        self._ensure_bucket(bucket)
        result = self.client.put_object(
            bucket,
            object_key,
            data=BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type or "application/octet-stream",
            metadata=metadata,
        )
        return MinioUploadResult(
            storage_provider="minio",
            storage_bucket=bucket,
            storage_key=object_key,
            storage_etag=result.etag or "",
            storage_version=result.version_id or "",
        )

    def _ensure_bucket(self, bucket: str) -> None:
        """Require a pre-provisioned configured bucket without mutating MinIO."""

        try:
            if not self.client.bucket_exists(bucket):
                raise RuntimeError(f"configured MinIO bucket is missing: {bucket}")
        except Exception as exc:
            raise RuntimeError(f"MinIO bucket is not available: {bucket}") from exc

    def get_object_bytes(self, storage_ref: str) -> bytes:
        """Fetch raw object bytes by minio://bucket/key ref."""
        bucket, key = self._parse_storage_ref(storage_ref)
        response = None
        try:
            response = self.client.get_object(bucket, key)
            return response.read()
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
                try:
                    response.release_conn()
                except Exception:
                    pass

    def open_object(self, storage_ref: str, *, offset: int = 0, length: int | None = None):
        """Open a streaming MinIO response; the caller must close it."""

        bucket, key = self._parse_storage_ref(storage_ref)
        return self.client.get_object(bucket, key, offset=offset, length=length)

    def stat_object(self, storage_ref: str):
        bucket, key = self._parse_storage_ref(storage_ref)
        return self.client.stat_object(bucket, key)

    def delete_object(self, storage_ref: str) -> bool:
        """Delete one raw object; return True on success, False on any failure."""
        bucket, key = self._parse_storage_ref(storage_ref)
        try:
            self.client.remove_object(bucket, key)
            return True
        except Exception:
            return False

    @staticmethod
    def _parse_storage_ref(storage_ref: str) -> tuple[str, str]:
        normalized = (storage_ref or "").strip()
        if not normalized.startswith("minio://"):
            raise ValueError(f"invalid storage_ref: {storage_ref!r}")
        parsed = urlsplit(normalized)
        bucket = parsed.netloc.strip("/")
        key = parsed.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(f"storage_ref missing bucket or key: {storage_ref!r}")
        return bucket, key


def build_raw_object_key(
    *,
    case_id: int,
    entity_id: int,
    file_name: str,
    entity_name: str = "",
    content_sha256: str,
    settings=None,
) -> str:
    """Build an immutable raw-case-file object key.

    entity 段优先级: entity_id > entity_name > entity-unknown。新上传使用
    内容 SHA-256，避免同名不同内容覆盖已有审计证据。
    """
    normalized_sha256 = str(content_sha256 or "").strip().lower()
    if len(normalized_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in normalized_sha256
    ):
        raise ValueError("content_sha256 must be a valid SHA-256 hex digest")
    # The remote MinIO deployment rejects percent-encoded Unicode object names.
    # Source-file metadata retains the original filename, while the immutable
    # object key remains portable and content-addressed.
    content_name = normalized_sha256
    case_segment = f"case-{case_id}" if case_id > 0 else "case-unknown"
    if entity_id > 0:
        entity_segment = f"entity-{entity_id}"
    elif (entity_name or "").strip():
        entity_name_hash = hashlib.sha256(entity_name.strip().encode("utf-8")).hexdigest()[:16]
        entity_segment = f"entity-name-{entity_name_hash}"
    else:
        entity_segment = "entity-unknown"
    if settings is not None:
        validate_domain(settings.business_domain, expected="annual_audit")
        return scoped_object_key(
            settings,
            project_id=case_id,
            category="raw",
            parts=(entity_segment, content_name),
        )
    return f"{case_segment}/{entity_segment}/raw/{content_name}"


def _guess_content_type(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".png"}:
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix == ".xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    return "application/octet-stream"


def _safe_identifier(value: str, field_name: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized or any(character not in "0123456789abcdef-" for character in normalized):
        raise ValueError(f"{field_name} is not a safe UUID-like identifier")
    return normalized


def resolve_minio_reference_url(storage_ref: str) -> str:
    """Convert a minio://bucket/key reference into a domain-based object URL."""
    normalized_ref = (storage_ref or "").strip()
    if not normalized_ref or not normalized_ref.startswith("minio://"):
        return normalized_ref

    parsed = urlsplit(normalized_ref)
    bucket = parsed.netloc.strip("/")
    object_key = parsed.path.lstrip("/")
    if not bucket or not object_key:
        return normalized_ref

    settings = get_settings()
    endpoint_text = settings.annual_minio_endpoint.strip().rstrip("/")
    if not endpoint_text:
        return normalized_ref

    endpoint_parts = urlsplit(
        endpoint_text if "://" in endpoint_text else f"//{endpoint_text}"
    )
    endpoint = endpoint_parts.netloc or endpoint_parts.path
    scheme = endpoint_parts.scheme or ("https" if settings.annual_minio_use_ssl else "http")
    if not endpoint:
        return normalized_ref
    encoded_key = quote(object_key, safe="/")
    return f"{scheme}://{endpoint}/{bucket}/{encoded_key}"


def get_minio_service() -> MinioService:
    """Build one MinIO service wrapper from environment settings."""
    return MinioService()

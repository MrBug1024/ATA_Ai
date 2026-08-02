"""MinIO service used for raw-case-file persistence."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, urlsplit

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
        self.enabled = settings.ai_hunter_minio_enabled
        self.bucket_raw = settings.ai_hunter_minio_bucket_raw
        self.bucket_derived = settings.ai_hunter_minio_bucket_derived
        self.bucket_artifacts = settings.ai_hunter_minio_bucket_artifacts
        try:
            from minio import Minio
        except ModuleNotFoundError as exc:
            raise RuntimeError("minio package is not installed") from exc
        self.client = Minio(
            settings.ai_hunter_minio_endpoint,
            access_key=settings.ai_hunter_minio_access_key,
            secret_key=settings.ai_hunter_minio_secret_key,
            secure=settings.ai_hunter_minio_use_ssl,
        )

    def upload_raw_file(
        self,
        *,
        case_id: int,
        debtor_id: int,
        file_name: str,
        content_type: str,
        file_bytes: bytes,
        debtor_name: str = "",
    ) -> MinioUploadResult:
        """Upload one raw case file to the configured raw bucket."""
        if not self.enabled:
            raise RuntimeError("AI Hunter MinIO is disabled")
        if not self.bucket_raw:
            raise RuntimeError("AI Hunter MinIO raw bucket is not configured")

        object_key = build_raw_object_key(
            case_id=case_id,
            debtor_id=debtor_id,
            file_name=file_name,
            debtor_name=debtor_name,
        )
        result = self.client.put_object(
            self.bucket_raw,
            object_key,
            data=BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type or _guess_content_type(file_name),
        )
        return MinioUploadResult(
            storage_provider="minio",
            storage_bucket=self.bucket_raw,
            storage_key=object_key,
            storage_etag=result.etag or "",
            storage_version=result.version_id or "",
        )

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
    debtor_id: int,
    file_name: str,
    debtor_name: str = "",
) -> str:
    """Build a stable raw-case-file object key.

    debtor 段优先级:debtor_id > debtor_name > debtor-unknown
    """
    safe_name = Path(file_name or "uploaded-file").name
    encoded_name = quote(safe_name, safe="")
    case_segment = f"case-{case_id}" if case_id > 0 else "case-unknown"
    if debtor_id > 0:
        debtor_segment = f"debtor-{debtor_id}"
    elif (debtor_name or "").strip():
        debtor_segment = f"debtor-{quote(debtor_name.strip(), safe='')}"
    else:
        debtor_segment = "debtor-unknown"
    return f"{case_segment}/{debtor_segment}/raw/{encoded_name}"


def _guess_content_type(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".png"}:
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "application/octet-stream"


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
    endpoint = settings.ai_hunter_minio_endpoint.strip().rstrip("/")
    if not endpoint:
        return normalized_ref

    scheme = "https" if settings.ai_hunter_minio_use_ssl else "http"
    encoded_key = quote(object_key, safe="/")
    return f"{scheme}://{endpoint}/{bucket}/{encoded_key}"


def get_minio_service() -> MinioService:
    """Build one MinIO service wrapper from environment settings."""
    return MinioService()

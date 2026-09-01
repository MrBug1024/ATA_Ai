from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tomllib

import pytest
import yaml

from ai_hunter.annual_audit.scripts.verify_attachment_runtime import (
    verify_runtime,
    write_font_manifest,
)
from ai_hunter.annual_audit.scripts.verify_storage import (
    REQUIRED_POSTGRES_COLUMNS,
    REQUIRED_POSTGRES_MIGRATIONS,
    REQUIRED_POSTGRES_TABLES,
)


RENDERER_DIGEST = "renderer.example/gotenberg:8.30.0@sha256:" + ("a" * 64)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent


def _font_manifest(tmp_path: Path) -> tuple[Path, Path]:
    font_root = tmp_path / "fonts"
    relative_path = Path("opentype/noto/NotoSansCJK-Regular.ttc")
    font_file = font_root / relative_path
    font_file.parent.mkdir(parents=True)
    font_file.write_bytes(b"stable-cjk-font")
    manifest_path = tmp_path / "font-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": "fonts-v1",
                "renderer_image_digest": RENDERER_DIGEST,
                "files": {
                    relative_path.as_posix(): hashlib.sha256(font_file.read_bytes()).hexdigest()
                },
            }
        ),
        encoding="utf-8",
    )
    return font_root, manifest_path


def test_attachment_runtime_verifies_renderer_and_font_hashes(tmp_path: Path) -> None:
    font_root, manifest_path = _font_manifest(tmp_path)

    result = verify_runtime(
        font_root=font_root,
        manifest_path=manifest_path,
        expected_manifest_version="fonts-v1",
        renderer_image_digest=RENDERER_DIGEST,
    )

    assert result["font_file_count"] == 1
    assert result["renderer_image_digest"] == RENDERER_DIGEST


def test_attachment_runtime_rejects_mutable_renderer_tag(tmp_path: Path) -> None:
    font_root, manifest_path = _font_manifest(tmp_path)

    with pytest.raises(RuntimeError, match="immutable image reference"):
        verify_runtime(
            font_root=font_root,
            manifest_path=manifest_path,
            expected_manifest_version="fonts-v1",
            renderer_image_digest="gotenberg/gotenberg:8",
        )


def test_attachment_runtime_rejects_font_source_renderer_mismatch(tmp_path: Path) -> None:
    font_root, manifest_path = _font_manifest(tmp_path)

    with pytest.raises(RuntimeError, match="different renderer image"):
        verify_runtime(
            font_root=font_root,
            manifest_path=manifest_path,
            expected_manifest_version="fonts-v1",
            renderer_image_digest="renderer.example/gotenberg:8.30.1@sha256:" + ("b" * 64),
        )


def test_font_manifest_generation_is_content_addressed(tmp_path: Path) -> None:
    font_root, _ = _font_manifest(tmp_path)
    manifest_path = tmp_path / "generated.json"

    write_font_manifest(
        font_root=font_root,
        manifest_path=manifest_path,
        version="fonts-v2",
        renderer_image_digest=RENDERER_DIGEST,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == "fonts-v2"
    assert manifest["renderer_image_digest"] == RENDERER_DIGEST
    assert manifest["files"] == {
        "opentype/noto/NotoSansCJK-Regular.ttc": hashlib.sha256(
            b"stable-cjk-font"
        ).hexdigest()
    }


def test_external_storage_contract_covers_attachment_storage() -> None:
    assert {"063", "064", "065", "066", "070"} <= REQUIRED_POSTGRES_MIGRATIONS
    assert {
        "annual_attachment_generation_job",
        "annual_attachment_storage_object",
        "annual_attachment_storage_reference",
    } <= REQUIRED_POSTGRES_TABLES
    assert {
        "document_template_version",
        "document_template_storage_object",
        "document_template_storage_reference",
    } <= REQUIRED_POSTGRES_TABLES
    assert REQUIRED_POSTGRES_COLUMNS["audit_engagement"] == {
        "engagement_type",
        "entity_uscc",
        "company_id",
        "owner_user_id",
    }


def test_runtime_lock_covers_direct_dependencies_with_hashes() -> None:
    pyproject = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    direct_names = {
        re.split(r"[<>=!~\[ ]", requirement, maxsplit=1)[0].lower().replace("_", "-")
        for requirement in pyproject["project"]["dependencies"]
    }
    lock_text = (BACKEND_ROOT / "requirements-runtime.lock").read_text(encoding="utf-8")
    locked_names = {
        match.group(1).lower().replace("_", "-")
        for match in re.finditer(r"(?m)^([A-Za-z0-9_.-]+)==[^\s]+ \\$", lock_text)
    }
    assert direct_names <= locked_names
    assert "--hash=sha256:" in lock_text


def test_compose_pins_images_and_uses_external_storage_services() -> None:
    compose_path = REPOSITORY_ROOT / "deploy" / "annual-audit" / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = compose["services"]

    assert set(services) == {
        "annual-api",
        "attachment-worker",
        "attachment-beat",
        "gotenberg",
        "clamav",
    }
    assert services["annual-api"]["healthcheck"]
    assert services["attachment-worker"]["healthcheck"]
    assert services["annual-api"]["networks"] == ["annual_runtime"]
    assert services["clamav"]["networks"] == ["annual_runtime"]
    assert "-mtime -3" in " ".join(services["clamav"]["healthcheck"]["test"])
    assert "check_storage_readiness" in " ".join(
        services["attachment-worker"]["healthcheck"]["test"]
    )
    for service_name in ("annual-api", "attachment-worker", "attachment-beat"):
        service = services[service_name]
        assert service["env_file"] == ["../../backend/.env"]
        environment = service.get("environment", {})
        assert "POSTGRESQL_HOST" not in environment
        assert "REDIS_HOST" not in environment
        assert "ANNUAL_MINIO_ENDPOINT" not in environment
    for service in services.values():
        image = service.get("image")
        if image and not image.startswith("ata-annual-"):
            assert re.search(r"@sha256:[0-9a-f]{64}$", image), image

    assert set(compose["volumes"]) == {"annual_clamav_data"}
    assert set(compose["networks"]) == {"annual_runtime"}


def test_dockerfiles_pin_build_inputs_and_copy_runtime_contracts() -> None:
    backend_dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.13-slim@sha256:" in backend_dockerfile
    assert "gotenberg/gotenberg:8.30.0@sha256:" in backend_dockerfile
    assert "--no-build-isolation --require-hashes -r requirements-runtime.lock" in backend_dockerfile
    assert "COPY config ./config" in backend_dockerfile
    assert "COPY sql ./sql" in backend_dockerfile

    web_dockerfile = (REPOSITORY_ROOT / "web" / "Dockerfile").read_text(encoding="utf-8")
    package_json = json.loads(
        (REPOSITORY_ROOT / "web" / "package.json").read_text(encoding="utf-8")
    )
    assert "node:22-alpine@sha256:" in web_dockerfile
    assert "gcompat=1.1.0-r4" in web_dockerfile
    assert re.fullmatch(
        r"pnpm@10\.14\.0\+sha512\.[0-9a-f]{128}", package_json["packageManager"]
    )

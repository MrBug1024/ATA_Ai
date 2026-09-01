"""Verify immutable renderer identity and the worker's CJK font manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re


DEFAULT_FONT_ROOT = Path("/usr/share/fonts")
DEFAULT_MANIFEST_PATH = Path("/usr/local/share/ata/font-manifest.json")
IMMUTABLE_IMAGE_RE = re.compile(r"^[^\s]+@sha256:[0-9a-f]{64}$")
FONT_SUFFIXES = frozenset({".otf", ".ttc", ".ttf"})


def write_font_manifest(
    *,
    font_root: Path,
    manifest_path: Path,
    version: str,
    renderer_image_digest: str,
) -> None:
    if not version:
        raise RuntimeError("font manifest version must not be empty")
    if not IMMUTABLE_IMAGE_RE.fullmatch(renderer_image_digest):
        raise RuntimeError("font source renderer must be an immutable image reference")
    files = {
        path.relative_to(font_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(font_root.rglob("*"))
        if path.is_file() and path.suffix.lower() in FONT_SUFFIXES
    }
    if not files or not any("notosanscjk" in path.lower() for path in files):
        raise RuntimeError("Noto Sans CJK is missing from the renderer font source")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "version": version,
                "renderer_image_digest": renderer_image_digest,
                "files": files,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def verify_runtime(
    *,
    font_root: Path = DEFAULT_FONT_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    expected_manifest_version: str | None = None,
    renderer_image_digest: str | None = None,
) -> dict[str, object]:
    expected_version = expected_manifest_version or os.getenv(
        "ATTACHMENT_FONT_MANIFEST_VERSION", ""
    )
    renderer = renderer_image_digest or os.getenv("ATTACHMENT_RENDERER_IMAGE_DIGEST", "")
    if not IMMUTABLE_IMAGE_RE.fullmatch(renderer):
        raise RuntimeError(
            "ATTACHMENT_RENDERER_IMAGE_DIGEST must be an immutable image reference"
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read CJK font manifest: {manifest_path}") from exc

    actual_version = str(manifest.get("version") or "")
    if not expected_version or actual_version != expected_version:
        raise RuntimeError(
            f"CJK font manifest version mismatch: expected {expected_version!r}, "
            f"found {actual_version!r}"
        )
    if str(manifest.get("renderer_image_digest") or "") != renderer:
        raise RuntimeError("CJK font manifest was built from a different renderer image")

    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("CJK font manifest does not contain any files")
    if not any("notosanscjk" in str(path).lower() for path in files):
        raise RuntimeError("CJK font manifest does not contain Noto Sans CJK")

    verified = 0
    for relative_path, expected_sha256 in sorted(files.items()):
        candidate = (font_root / str(relative_path)).resolve()
        try:
            candidate.relative_to(font_root.resolve())
        except ValueError as exc:
            raise RuntimeError(f"font manifest path escapes font root: {relative_path}") from exc
        try:
            actual_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
        except OSError as exc:
            raise RuntimeError(f"font manifest file is missing: {relative_path}") from exc
        if actual_sha256 != expected_sha256:
            raise RuntimeError(f"font manifest hash mismatch: {relative_path}")
        verified += 1

    return {
        "font_manifest_version": actual_version,
        "font_file_count": verified,
        "renderer_image_digest": renderer,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest-version")
    parser.add_argument("--renderer-image-digest")
    args = parser.parse_args()
    if args.write_manifest_version:
        write_font_manifest(
            font_root=DEFAULT_FONT_ROOT,
            manifest_path=DEFAULT_MANIFEST_PATH,
            version=args.write_manifest_version,
            renderer_image_digest=args.renderer_image_digest or "",
        )
        return
    print(json.dumps(verify_runtime(), sort_keys=True))


if __name__ == "__main__":
    main()

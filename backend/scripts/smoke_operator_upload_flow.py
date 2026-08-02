"""Smoke-test the operator upload flow against the unified AI Hunter backend.

Example:
    .venv/bin/python scripts/smoke_operator_upload_flow.py \
      --ai-hunter-url http://127.0.0.1:8081 \
      --fastserver-url http://10.0.10.2:8081 \
      --case-id 116 \
      --debtor-id 76 \
      --doc-category judgment \
      --file tests/fixtures/sample.txt
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import httpx


def main() -> None:
    args = parse_args()
    file_path = Path(args.file)
    if not file_path.exists():
        raise SystemExit(f"file not found: {file_path}")

    fastserver = args.fastserver_url.rstrip("/")
    ai_hunter = args.ai_hunter_url.rstrip("/")
    ai_hunter_headers = _bearer_headers(args.access_token)
    fastserver_headers = _audit_headers(args.audit_token)

    with httpx.Client(timeout=args.timeout_seconds) as client:
        catalog = client.get(
            f"{fastserver}/api/ingest/doc-categories",
            headers=fastserver_headers,
        )
        catalog.raise_for_status()
        catalog_payload = catalog.json()
        print("doc_categories:", len(catalog_payload.get("categories", [])))

        validation = client.post(
            f"{fastserver}/api/ingest/validate-doc-category",
            headers=fastserver_headers,
            json={
                "case_id": args.case_id,
                "doc_category": args.doc_category,
                "file_names": [file_path.name],
                "text_preview": "",
            },
        )
        validation.raise_for_status()
        validation_payload = validation.json()
        print("validation:", json.dumps(validation_payload, ensure_ascii=False))

        with file_path.open("rb") as file_obj:
            upload = client.post(
                f"{ai_hunter}/files/upload-and-ingest",
                headers=ai_hunter_headers,
                data={
                    "current_case_id": str(args.case_id),
                    "current_debtor_id": str(args.debtor_id),
                    "current_debtor_name": args.debtor_name,
                    "doc_category": args.doc_category,
                    "batch_name": args.batch_name,
                    "operator_id": args.operator_id,
                    "operator_name": args.operator_name,
                },
                files={"files": (file_path.name, file_obj, args.content_type)},
            )
        upload.raise_for_status()
        upload_payload = upload.json()
        upload_batch_id = upload_payload.get("upload_batch_id", "")
        material_event_id = upload_payload.get("material_event_id", "")
        print(
            "accepted:",
            json.dumps(
                _pick(
                    upload_payload,
                    [
                        "upload_batch_id",
                        "material_event_id",
                        "status",
                        "stage",
                        "file_count",
                    ],
                ),
                ensure_ascii=False,
            ),
        )

        if not upload_batch_id:
            raise SystemExit("upload response missing upload_batch_id")

        batch_payload = _wait_for_terminal_batch(
            client,
            ai_hunter=ai_hunter,
            upload_batch_id=upload_batch_id,
            material_event_id=material_event_id,
            headers=ai_hunter_headers,
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        )
        _validate_completed_batch(
            batch_payload,
            case_id=args.case_id,
            debtor_id=args.debtor_id,
            require_records=args.require_records,
        )
        print(
            "completed:",
            json.dumps(
                _pick(
                    batch_payload,
                    [
                        "upload_batch_id",
                        "case_id",
                        "debtor_id",
                        "status",
                        "file_count",
                        "records_inserted",
                        "persistence_checks",
                        "files",
                    ],
                ),
                ensure_ascii=False,
            ),
        )

        case_status = client.get(
            f"{fastserver}/api/case/{args.case_id}/doc-categories",
            headers=fastserver_headers,
        )
        case_status.raise_for_status()
        case_payload = case_status.json()
        print("missing_categories:", case_payload.get("missing_categories", []))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an operator upload smoke test.")
    parser.add_argument("--ai-hunter-url", default="http://127.0.0.1:8081")
    parser.add_argument("--fastserver-url", default="http://10.0.10.2:8081")
    parser.add_argument("--case-id", type=int, default=116)
    parser.add_argument("--debtor-id", type=int, default=0)
    parser.add_argument("--debtor-name", default="")
    parser.add_argument("--doc-category", default="judgment")
    parser.add_argument("--batch-name", default="operator-smoke")
    parser.add_argument("--operator-id", default="smoke")
    parser.add_argument("--operator-name", default="Smoke Test")
    parser.add_argument("--file", required=True)
    parser.add_argument("--content-type", default="text/plain")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument(
        "--access-token",
        default=os.environ.get("AI_HUNTER_SMOKE_ACCESS_TOKEN", ""),
        help="AI Hunter Bearer token; defaults to AI_HUNTER_SMOKE_ACCESS_TOKEN.",
    )
    parser.add_argument(
        "--audit-token",
        default=os.environ.get("AUDIT_API_TOKEN", ""),
        help="fastserver X-Audit-Token; defaults to AUDIT_API_TOKEN.",
    )
    parser.add_argument(
        "--require-records",
        action="store_true",
        help="Fail when parse-document completes without inserting records.",
    )
    return parser.parse_args()


def _pick(payload: dict, keys: list[str]) -> dict:
    return {key: payload.get(key) for key in keys}


def _bearer_headers(token: str) -> dict[str, str]:
    normalized = token.strip()
    return {"Authorization": f"Bearer {normalized}"} if normalized else {}


def _audit_headers(token: str) -> dict[str, str]:
    normalized = token.strip()
    return {"X-Audit-Token": normalized} if normalized else {}


def _wait_for_terminal_batch(
    client: httpx.Client,
    *,
    ai_hunter: str,
    upload_batch_id: str,
    material_event_id: str,
    headers: dict[str, str],
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_progress: tuple[str, str] | None = None
    while time.monotonic() < deadline:
        response = client.get(
            f"{ai_hunter}/files/upload-batches/{upload_batch_id}",
            headers=headers,
        )
        response.raise_for_status()
        batch = response.json()
        status = str(batch.get("status", "") or "")
        stage = str((batch.get("metadata") or {}).get("stage", "") or "")
        progress = (status, stage)
        if progress != last_progress:
            print("progress:", json.dumps({"status": status, "stage": stage}, ensure_ascii=False))
            last_progress = progress
        if status == "completed":
            return batch
        if status == "failed":
            event = _get_material_event(
                client,
                ai_hunter=ai_hunter,
                material_event_id=material_event_id,
                headers=headers,
            )
            detail = event.get("error_message") or (event.get("event_payload") or {}).get("error")
            raise SystemExit(f"upload batch failed at stage={stage}: {detail or 'unknown error'}")
        time.sleep(max(poll_interval_seconds, 0.1))
    raise SystemExit(f"upload batch timed out after {timeout_seconds}s: {upload_batch_id}")


def _get_material_event(
    client: httpx.Client,
    *,
    ai_hunter: str,
    material_event_id: str,
    headers: dict[str, str],
) -> dict:
    if not material_event_id:
        return {}
    response = client.get(
        f"{ai_hunter}/files/material-events/{material_event_id}",
        headers=headers,
    )
    response.raise_for_status()
    return response.json()


def _validate_completed_batch(
    batch: dict,
    *,
    case_id: int,
    debtor_id: int,
    require_records: bool,
) -> None:
    errors: list[str] = []
    if int(batch.get("case_id", 0) or 0) != case_id:
        errors.append("case_id mismatch")
    if debtor_id > 0 and int(batch.get("debtor_id", 0) or 0) != debtor_id:
        errors.append("debtor_id mismatch")
    files = list(batch.get("files") or [])
    if not files:
        errors.append("no persisted files")
    for item in files:
        if item.get("storage_provider") != "minio":
            errors.append(f"file is not stored in MinIO: {item.get('file_name', '')}")
        if not str(item.get("storage_ref", "") or "").startswith("minio://"):
            errors.append(f"file has invalid storage_ref: {item.get('file_name', '')}")
    checks = dict(batch.get("persistence_checks") or {})
    for key in (
        "source_upload_batch_exists",
        "source_file_count_matches",
        "all_files_have_chunks",
        "all_files_have_doc_category",
    ):
        if checks.get(key) is not True:
            errors.append(f"persistence check failed: {key}")
    if require_records and int(batch.get("records_inserted", 0) or 0) <= 0:
        errors.append("parse-document inserted no records")
    if errors:
        raise SystemExit("completed batch failed acceptance checks: " + "; ".join(errors))


if __name__ == "__main__":
    main()

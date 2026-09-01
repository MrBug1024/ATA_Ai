from __future__ import annotations

import json

import pytest

from ai_hunter.annual_audit.scripts import plan_attachment_storage_reclamation as script


class _TemplateRepository:
    def __init__(self, items: list[dict]) -> None:
        self.items = items
        self.limits: list[int] = []

    def plan_storage_reclamation(self, *, limit: int) -> list[dict]:
        self.limits.append(limit)
        return self.items


def _candidate(*, object_kind: str, ref_hash: str, private_ref: str) -> dict:
    return {
        "object_kind": object_kind,
        "storage_ref_hash": ref_hash,
        "retention_state": "reclaim_candidate",
        "unreferenced_at": "2026-08-01T00:00:00+00:00",
        "retention_until": "2026-08-31T00:00:00+00:00",
        "storage_ref": private_ref,
        "content_sha256": "9" * 64,
    }


def test_cli_projects_only_safe_candidate_fields(capsys, monkeypatch) -> None:
    private_template_ref = "minio://templates/private/source.docx"
    private_attachment_ref = "minio://artifacts/private/report.docx"
    template_repository = _TemplateRepository(
        [_candidate(object_kind="source", ref_hash="a" * 64, private_ref=private_template_ref)]
    )
    attachment_limits: list[int] = []

    def attachment_planner(*, limit: int) -> list[dict]:
        attachment_limits.append(limit)
        return [
            _candidate(
                object_kind="artifact",
                ref_hash="b" * 64,
                private_ref=private_attachment_ref,
            )
        ]

    monkeypatch.setattr(
        script,
        "DocumentTemplateRepository",
        lambda: template_repository,
    )
    monkeypatch.setattr(
        script.attachment_repository,
        "plan_storage_reclamation",
        attachment_planner,
    )

    script.main(["--limit", "17"])
    output = capsys.readouterr().out
    parsed = json.loads(output)

    assert template_repository.limits == [17]
    assert attachment_limits == [17]
    assert parsed["template_postgres"]["count"] == 1
    assert parsed["attachment_postgres"]["count"] == 1
    assert set(parsed["template_postgres"]["items"][0]) == {
        "object_kind",
        "storage_ref_hash",
        "retention_state",
        "unreferenced_at",
        "retention_until",
    }
    assert '"storage_ref":' not in output
    assert private_template_ref not in output
    assert private_attachment_ref not in output
    assert "content_sha256" not in output


@pytest.mark.parametrize("value", ["0", "1001", "not-a-number"])
def test_cli_rejects_unbounded_limit(value: str) -> None:
    with pytest.raises(SystemExit) as raised:
        script._parser().parse_args(["--limit", value])
    assert raised.value.code == 2


def test_public_projection_rejects_non_candidate_or_non_hash_values() -> None:
    with pytest.raises(RuntimeError, match="storage reference hash"):
        script._public_candidate(
            {
                "object_kind": "artifact",
                "storage_ref_hash": "minio://must-not-be-printed",
                "retention_state": "reclaim_candidate",
            }
        )
    with pytest.raises(RuntimeError, match="retention state"):
        script._public_candidate(
            {
                "object_kind": "artifact",
                "storage_ref_hash": "c" * 64,
                "retention_state": "active",
            }
        )

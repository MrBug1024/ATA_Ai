from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from ai_hunter.annual_audit.legacy_case_migration import (
    CASE_WORKPAPER_FILE_NAME,
    DEFAULT_MANIFEST_RELATIVE_PATH,
    SAFE_MANIFEST_RULES,
    MigrationPlanError,
    apply_manual_review_raw_plan,
    apply_safe_plan,
    build_migration_plan,
    execute_migration,
    manual_review_batch_id,
    stable_batch_id,
)


def _legacy_path(relative_path: Path) -> str:
    return str(PureWindowsPath("E:/legacy/NpaLang/new_docs", *relative_path.parts))


def _manifest_payload(root: Path, manifest_directory: Path) -> dict[str, list[str]]:
    names = {
        "trial_balance": ["科目余额表-试算平衡派生.xlsx"],
        "bank_statements": ["银行流水-底稿抽查派生.xlsx"],
        "journal_entries": ["工资.xlsx", "调整明细.xlsx"],
        "receivables": ["C5-2应收帐款审定表.xlsx"],
        "financial_statements": [
            "财务报表/1、A1-1审计报告-标准无保留意见（单体、企业会计准则）.docx",
            "财务报表/2、经审计的财务报表-（会计准则）.xls",
            "财务报表/3、会计报表附注-会计准则.doc",
        ],
        "revenue_support": ["咨询费合同抽查表.xlsx", "F1-2主营业务收入审定表.xlsx", "F1-3主营业务收入检查表.xlsx"],
        "confirmations": [
            "函证模版/1银行函证.docx",
            "函证模版/2有价证券询证函.xls",
            "函证模版/3 往来账项询证函模板.xls",
            "函证模版/4发出商品询证函.xls",
            "函证模版/5投资关系询证函.xls",
            "函证模版/6租赁询证函.xls",
        ],
        "tax_materials": [],
        "other": ["预收替代.xlsx", "基础信息.xlsx"],
    }
    return {
        category: [_legacy_path(manifest_directory.relative_to(root) / name) for name in paths]
        for category, paths in names.items()
    }


def _write(path: Path, content: bytes = b"fixture") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _build_plan(tmp_path: Path):
    root = tmp_path / "new_docs"
    manifest_path = root / DEFAULT_MANIFEST_RELATIVE_PATH
    manifest_directory = manifest_path.parent
    case_root = manifest_directory.parent
    payload = _manifest_payload(root, manifest_directory)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    _write(case_root / CASE_WORKPAPER_FILE_NAME)
    for rule in SAFE_MANIFEST_RULES:
        path = manifest_directory / rule.manifest_name
        if rule.replacement_name:
            _write(path, b"manifest original")
            path = path.with_name(rule.replacement_name)
        _write(path)

    # The three report artifacts moved out of the split-material directory.
    _write(manifest_directory / "税审报告" / "1、A1-1审计报告-标准无保留意见（单体、企业会计准则）.docx")
    _write(manifest_directory / "税审报告" / "2、经审计的财务报表-（会计准则）.xlsx")
    _write(manifest_directory / "税审报告" / "3、会计报表附注-会计准则.docx")
    for name in (
        "咨询费合同抽查表.xlsx",
        "F1-2主营业务收入审定表.xlsx",
        "F1-3主营业务收入检查表.xlsx",
        "预收替代.xlsx",
        "基础信息.xlsx",
    ):
        _write(manifest_directory / name)
    _write(manifest_directory / "函证模版" / "1银行函证.docx")
    for name in (
        "2有价证券询证函.xlsx",
        "3 往来账项询证函模板.xlsx",
        "4发出商品询证函.xlsx",
        "5投资关系询证函.xlsx",
        "6租赁询证函.xlsx",
    ):
        _write(manifest_directory / "函证模版" / name)
    return build_migration_plan(source_root=root)


def test_plan_resolves_only_reviewed_paths_and_known_replacements(tmp_path: Path) -> None:
    plan = _build_plan(tmp_path)

    assert plan.manifest_item_count == 19
    assert len(plan.safe_items) == 5
    assert len(plan.manual_review_items) == 15
    assert not plan.plan_errors
    assert plan.migration_id.startswith("beijing-v2-safe-v2-")

    adjustment = next(item for item in plan.manual_review_items if item.source_name == "调整明细.xlsx")
    assert adjustment.resolution == "legacy_manifest_path"
    assert adjustment.expected_dataset == "journal_entry"
    assert not adjustment.safe_to_apply
    assert "重复凭证行键" in adjustment.manual_review_reason

    financial = [item for item in plan.items if item.manifest_category == "financial_statements"]
    assert {item.resolution for item in financial} == {"financial_statement_report_directory_relocation"}
    assert {item.source_path.suffix.lower() for item in financial} == {".docx", ".xlsx"}

    replacements = [item for item in plan.items if item.resolution == "confirmation_xls_to_xlsx_replacement"]
    assert len(replacements) == 5
    assert all(not item.safe_to_apply for item in replacements)


def test_dry_run_never_requests_external_services(tmp_path: Path) -> None:
    plan = _build_plan(tmp_path)

    report = execute_migration(
        plan=plan,
        apply=False,
        case_id=42,
        validator=lambda item: {"status": "validated", "item_id": item.item_id},
    )

    assert report.mode == "dry_run"
    assert report.case_id == 42
    assert not report.batches
    assert not report.errors
    assert len(report.validation) == len(plan.items)


class _Minio:
    def __init__(self) -> None:
        self.uploaded_names: list[str] = []

    def upload_raw_file(self, **kwargs):
        self.uploaded_names.append(kwargs["file_name"])
        return SimpleNamespace(
            storage_ref=f"minio://raw/{kwargs['file_name']}",
            storage_provider="minio",
            storage_bucket="raw",
            storage_key=kwargs["file_name"],
            storage_etag="etag",
            storage_version="version",
        )


class _Kg:
    def __init__(self) -> None:
        self.batch_updates: list[dict] = []
        self.event_updates: list[dict] = []
        self.categories: list[str] = []
        self.existing_batches: dict[str, dict] = {}

    def upsert_source_upload_batch(self, summary: dict):
        self.batch_updates.append(summary)
        return summary

    def upsert_material_event(self, summary: dict):
        self.event_updates.append(summary)
        return summary

    def insert_source_files(self, rows: list[dict]):
        return [{"id": index + 1, **row} for index, row in enumerate(rows)]

    def link_source_files_to_upload_batch(self, *, upload_batch_id: str, files: list[dict]):
        return [{"upload_batch_id": upload_batch_id, "file_id": row["id"]} for row in files]

    def upsert_source_file_doc_categories(self, *, category_code: str, **_kwargs):
        self.categories.append(category_code)
        return []

    def fetch_source_upload_batch(self, upload_batch_id: str):
        return self.existing_batches.get(upload_batch_id, {})


def test_apply_safe_plan_never_uploads_manual_manifest_items(tmp_path: Path) -> None:
    plan = _build_plan(tmp_path)
    minio = _Minio()
    kg = _Kg()
    imported_batches: list[list[str]] = []

    def importer(*, files, **_kwargs):
        imported_batches.append([item["name"] for item in files])
        return {"new_row_count": len(files), "status": "completed"}

    outcomes = apply_safe_plan(
        plan,
        case_id=42,
        engagement={"entity_name": "北京有限公司"},
        operator_id="migration-test",
        operator_name="migration-test",
        minio_service=minio,
        kg_service=kg,
        importer=importer,
    )

    safe_names = {item.source_name for item in plan.safe_items}
    manual_names = {item.source_name for item in plan.manual_review_items}
    assert set(minio.uploaded_names) == safe_names
    assert not set(minio.uploaded_names) & manual_names
    assert {outcome["status"] for outcome in outcomes} == {"completed"}
    assert len(imported_batches) == 5
    assert set(kg.categories) == {
        "audit_workpapers",
        "trial_balance",
        "bank_statements",
        "receivables",
        "journal_entries",
    }
    assert all(update["metadata"]["retryable"] is False for update in kg.batch_updates)
    assert all(
        update["event_payload"]["retry_policy"] == "manual_review_required"
        for update in kg.event_updates
    )
    assert all(
        update["event_payload"]["material_event_id"] == update["material_event_id"]
        for update in kg.event_updates
    )
    processing_events = [update for update in kg.event_updates if update["status"] == "processing"]
    completed_events = [update for update in kg.event_updates if update["status"] == "completed"]
    assert len(processing_events) == len(completed_events) == 5
    assert all(
        update["event_payload"]["stage"] == "historical_migration_running"
        for update in processing_events
    )
    assert all(update["event_payload"]["stage"] == "completed" for update in completed_events)


def test_apply_manual_review_raw_plan_preserves_originals_without_category_coverage(tmp_path: Path) -> None:
    plan = _build_plan(tmp_path)
    minio = _Minio()
    kg = _Kg()

    outcomes = apply_manual_review_raw_plan(
        plan,
        case_id=42,
        engagement={"entity_name": "北京有限公司"},
        operator_id="migration-test",
        operator_name="migration-test",
        minio_service=minio,
        kg_service=kg,
    )

    expected_counts = {
        "financial_statements": 3,
        "revenue_support": 3,
        "confirmations": 6,
        "other": 2,
        "journal_entries": 1,
    }
    manual_names = {item.source_name for item in plan.manual_review_items}
    assert set(minio.uploaded_names) == manual_names
    assert kg.categories == []
    assert {outcome["doc_category"]: outcome["file_count"] for outcome in outcomes} == expected_counts
    assert all(outcome["status"] == "completed" for outcome in outcomes)
    assert all(outcome["stage"] == "raw_preserved_pending_review" for outcome in outcomes)
    assert all(outcome["records_inserted"] == 0 for outcome in outcomes)

    completed_batches = [update for update in kg.batch_updates if update["status"] == "completed"]
    assert len(completed_batches) == len(expected_counts)
    assert all(update["metadata"]["ingest_mode"] == "raw_only_manual_review" for update in completed_batches)
    assert all(update["metadata"]["structured_projection"] == "not_attempted" for update in completed_batches)
    assert all(update["metadata"]["source_file_doc_categories_written"] is False for update in completed_batches)
    assert all(update["metadata"]["stage"] == "raw_preserved_pending_review" for update in completed_batches)

    journal_batch = next(update for update in completed_batches if update["doc_category"] == "journal_entries")
    raw_adjustment = journal_batch["metadata"]["raw_only_files"][0]
    assert raw_adjustment["source_name"] == "调整明细.xlsx"
    assert raw_adjustment["source_role"] == "original_manifest_file"
    assert raw_adjustment["normalized_derivative"]["source_name"] == "调整明细-规范化.xlsx"
    assert raw_adjustment["normalized_derivative"]["derivative_action"] == "not_uploaded_by_raw_only_migration"
    assert manual_review_batch_id(plan, case_id=42, doc_category="journal_entries") != stable_batch_id(
        plan,
        case_id=42,
        doc_category="journal_entries",
    )


def test_apply_manual_review_raw_plan_rejects_changed_source_set_before_upload(tmp_path: Path) -> None:
    plan = _build_plan(tmp_path)
    minio = _Minio()
    kg = _Kg()
    batch_id = manual_review_batch_id(plan, case_id=42, doc_category="financial_statements")
    kg.existing_batches[batch_id] = {"files": [{"file_sha256": "0" * 64}]}

    with pytest.raises(MigrationPlanError, match="refusing to mix versions"):
        apply_manual_review_raw_plan(
            plan,
            case_id=42,
            engagement={"entity_name": "北京有限公司"},
            operator_id="migration-test",
            operator_name="migration-test",
            minio_service=minio,
            kg_service=kg,
        )

    assert minio.uploaded_names == []


def test_manual_raw_plan_never_substitutes_normalized_adjustment_for_missing_original(tmp_path: Path) -> None:
    plan = _build_plan(tmp_path)
    original = next(item for item in plan.manual_review_items if item.source_name == "调整明细.xlsx")
    original.source_path.unlink()

    plan = build_migration_plan(source_root=plan.source_root)
    adjustment = next(item for item in plan.manual_review_items if item.source_name == "调整明细.xlsx")
    assert adjustment.exists is False
    assert adjustment.resolution == "legacy_manifest_path"

    with pytest.raises(MigrationPlanError, match="requires every reviewed source"):
        apply_manual_review_raw_plan(
            plan,
            case_id=42,
            engagement={"entity_name": "北京有限公司"},
            operator_id="migration-test",
            operator_name="migration-test",
            minio_service=_Minio(),
            kg_service=_Kg(),
        )


def test_stable_batch_identity_is_case_and_category_scoped(tmp_path: Path) -> None:
    plan = _build_plan(tmp_path)

    assert stable_batch_id(plan, case_id=42, doc_category="journal_entries") == stable_batch_id(
        plan,
        case_id=42,
        doc_category="journal_entries",
    )
    assert stable_batch_id(plan, case_id=42, doc_category="journal_entries") != stable_batch_id(
        plan,
        case_id=43,
        doc_category="journal_entries",
    )


def test_apply_safe_plan_marks_partial_structured_import_as_failed(tmp_path: Path) -> None:
    plan = _build_plan(tmp_path)
    minio = _Minio()
    kg = _Kg()

    outcomes = apply_safe_plan(
        plan,
        case_id=42,
        engagement={"entity_name": "北京有限公司"},
        operator_id="migration-test",
        operator_name="migration-test",
        minio_service=minio,
        kg_service=kg,
        importer=lambda **_kwargs: {
            "new_row_count": 7,
            "status": "partial",
            "errors": [{"error": "duplicate row"}],
        },
    )

    assert outcomes[0]["status"] == "failed"
    assert outcomes[0]["records_inserted"] == 7
    assert "reviewed structured import did not complete" in outcomes[0]["error"]
    assert kg.batch_updates[-1]["status"] == "failed"
    assert kg.batch_updates[-1]["records_inserted"] == 7
    assert kg.batch_updates[-1]["metadata"]["partial_success"] is True


def test_apply_safe_plan_rejects_changed_source_set_for_existing_batch(tmp_path: Path) -> None:
    plan = _build_plan(tmp_path)
    minio = _Minio()
    kg = _Kg()
    batch_id = stable_batch_id(plan, case_id=42, doc_category="trial_balance")
    kg.existing_batches[batch_id] = {"files": [{"file_sha256": "0" * 64}]}

    with pytest.raises(MigrationPlanError, match="refusing to mix versions"):
        apply_safe_plan(
            plan,
            case_id=42,
            engagement={"entity_name": "北京有限公司"},
            operator_id="migration-test",
            operator_name="migration-test",
            minio_service=minio,
            kg_service=kg,
            importer=lambda **_kwargs: {"new_row_count": 0, "status": "completed"},
        )

    assert minio.uploaded_names == []

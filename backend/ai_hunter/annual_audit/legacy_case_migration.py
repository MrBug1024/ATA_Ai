"""Auditable import of the supplied Beijing V2 annual-audit case package.

This module deliberately handles one reviewed case manifest rather than serving
as a generic directory uploader.  The supplied manifest contains supporting
workpapers and templates whose filenames can be misclassified by the legacy
structured importer.  Only the reviewed case pack and reviewed derived
spreadsheets may be projected into business facts.  Every other manifest entry
is migrated as a raw, manual-review source without OCR, graph, or structured
import side effects.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping


MIGRATION_TOOL_VERSION = "beijing-v2-safe-v2"
EXPECTED_MANIFEST_FILE_COUNT = 19
HISTORICAL_RETRY_DISABLED_REASON = "历史迁移批次包含需人工复核的资料，不能自动重试。"

# This relative path identifies the reviewed customer package, not a developer
# workstation.  ``source_root`` supplies the local ``new_docs`` directory.
DEFAULT_MANIFEST_RELATIVE_PATH = Path(
    "逻辑资料V1"
) / "AI智能体相关法律、准则、底稿、案例、报告模版【20260703】" / "7、案例" / (
    "北京有限公司-京创会审字[2024]第3999号-标准无保留意见-4.3.V2"
) / "拆分上传材料" / "manifest.json"

CASE_WORKPAPER_FILE_NAME = "北京有限公司2023年年审底稿.xlsx"


@dataclass(frozen=True)
class SafeMaterialRule:
    """One reviewed source that may enter the automatic migration path."""

    manifest_category: str
    manifest_name: str
    doc_category: str
    expected_dataset: str
    replacement_name: str | None = None
    auto_apply: bool = True
    manual_review_reason: str = ""


# ``调整明细-规范化.xlsx`` remains a related derived artifact only.  The
# manifest's original adjustment sheet is preserved through the raw-only
# review path, and neither version is automatically projected as journal facts.
SAFE_MANIFEST_RULES: tuple[SafeMaterialRule, ...] = (
    SafeMaterialRule(
        "trial_balance",
        "科目余额表-试算平衡派生.xlsx",
        "trial_balance",
        "account_balance",
    ),
    SafeMaterialRule(
        "bank_statements",
        "银行流水-底稿抽查派生.xlsx",
        "bank_statements",
        "bank_transaction",
    ),
    SafeMaterialRule(
        "receivables",
        "C5-2应收帐款审定表.xlsx",
        "receivables",
        "receivable_item",
    ),
    SafeMaterialRule(
        "journal_entries",
        "工资.xlsx",
        "journal_entries",
        "journal_entry",
    ),
    SafeMaterialRule(
        "journal_entries",
        "调整明细.xlsx",
        "journal_entries",
        "journal_entry",
        replacement_name="调整明细-规范化.xlsx",
        auto_apply=False,
        manual_review_reason=(
            "规范化调整明细在真实 PostgreSQL 投影中出现重复凭证行键；"
            "在人工确认重复行的保留语义前，只能保留为待复核资料，不能自动写入分录事实。"
        ),
    ),
)


@dataclass(frozen=True)
class MigrationItem:
    """One resolved source entry with its automatic-migration eligibility."""

    item_id: str
    manifest_category: str
    doc_category: str
    legacy_path: str
    source_relative_path: str
    source_path: Path
    source_name: str
    safe_to_apply: bool
    expected_dataset: str = ""
    resolution: str = ""
    manual_review_reason: str = ""
    is_case_workpaper: bool = False
    exists: bool = False
    file_size_bytes: int = 0
    file_sha256: str = ""

    def to_report_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_path"] = str(self.source_path)
        return payload


@dataclass(frozen=True)
class MigrationPlan:
    """Portable plan built solely from explicit manifest paths."""

    source_root: Path
    manifest_path: Path
    manifest_relative_path: str
    manifest_sha256: str
    migration_id: str
    manifest_item_count: int
    items: tuple[MigrationItem, ...]
    plan_errors: tuple[str, ...] = ()

    @property
    def safe_items(self) -> tuple[MigrationItem, ...]:
        return tuple(item for item in self.items if item.safe_to_apply)

    @property
    def manual_review_items(self) -> tuple[MigrationItem, ...]:
        return tuple(item for item in self.items if not item.safe_to_apply and not item.is_case_workpaper)

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "tool_version": MIGRATION_TOOL_VERSION,
            "migration_id": self.migration_id,
            "source_root": str(self.source_root),
            "manifest_path": str(self.manifest_path),
            "manifest_relative_path": self.manifest_relative_path,
            "manifest_sha256": self.manifest_sha256,
            "manifest_item_count": self.manifest_item_count,
            "safe_apply_count": len(self.safe_items),
            "manual_review_count": len(self.manual_review_items),
            "plan_errors": list(self.plan_errors),
            "items": [item.to_report_dict() for item in self.items],
        }


@dataclass
class MigrationExecutionReport:
    """Result returned by dry-run and apply modes without hiding omissions."""

    plan: MigrationPlan
    mode: str
    case_id: int | None = None
    case_action: str = "not_requested"
    validation: list[dict[str, Any]] = field(default_factory=list)
    batches: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.plan.to_report_dict(),
            "mode": self.mode,
            "case_id": self.case_id,
            "case_action": self.case_action,
            "validation": self.validation,
            "batches": self.batches,
            "errors": self.errors,
            "automatic_scope": {
                "structured_projection_item_count": len(self.plan.safe_items),
                "manual_review_raw_item_count": len(self.plan.manual_review_items),
                "manual_review_raw_only": True,
                "graph_enrichment_enqueued": False,
                "reason": (
                    "Manual-review sources are persisted as raw evidence only; "
                    "they are never sent through filename-based OCR, graph, or "
                    "structured-import paths."
                ),
            },
        }


class MigrationPlanError(ValueError):
    """Raised before a write when the reviewed migration contract is invalid."""


def default_source_root() -> Path:
    """Return the repository-local ``new_docs`` without embedding a machine path."""

    return Path(__file__).resolve().parents[3] / "new_docs"


def default_manifest_path(source_root: Path) -> Path:
    return Path(source_root) / DEFAULT_MANIFEST_RELATIVE_PATH


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _legacy_relative_path(legacy_path: str) -> Path:
    """Extract the portable path after a legacy ``new_docs`` component."""

    raw = str(legacy_path or "").strip()
    if not raw:
        raise MigrationPlanError("manifest contains an empty path")
    windows_path = PureWindowsPath(raw.replace("/", "\\"))
    parts = list(windows_path.parts)
    marker_index = next((index for index, part in enumerate(parts) if part.casefold() == "new_docs"), -1)
    if marker_index < 0 or marker_index == len(parts) - 1:
        raise MigrationPlanError(f"legacy manifest path is outside new_docs: {raw}")
    relative = Path(*parts[marker_index + 1 :])
    if relative.is_absolute() or ".." in relative.parts:
        raise MigrationPlanError(f"legacy manifest path is unsafe: {raw}")
    return relative


def _path_with_suffix(path: Path, suffix: str) -> Path:
    return path.with_suffix(suffix) if path.suffix else path


def _candidate_paths(
    *,
    source_root: Path,
    source_relative_path: Path,
    manifest_category: str,
    rule: SafeMaterialRule | None,
) -> list[tuple[Path, str]]:
    """Return explicit candidate paths, ordered by reviewed replacements."""

    candidates: list[tuple[Path, str]] = []
    parts = list(source_relative_path.parts)
    if manifest_category == "financial_statements":
        try:
            report_index = parts.index("财务报表")
        except ValueError:
            report_index = -1
        if report_index >= 0:
            # The reviewed package renamed the ``财务报表`` child directory
            # under ``拆分上传材料`` to ``税审报告``.
            report_parts = [*parts]
            report_parts[report_index] = "税审报告"
            report_relative = Path(*report_parts)
            if report_relative.suffix.lower() == ".xls":
                report_relative = _path_with_suffix(report_relative, ".xlsx")
            elif report_relative.suffix.lower() == ".doc":
                report_relative = _path_with_suffix(report_relative, ".docx")
            candidates.append((source_root / report_relative, "financial_statement_report_directory_relocation"))

    if manifest_category == "confirmations" and source_relative_path.suffix.lower() == ".xls":
        candidates.append(
            (source_root / _path_with_suffix(source_relative_path, ".xlsx"), "confirmation_xls_to_xlsx_replacement")
        )

    if rule and rule.replacement_name:
        candidates.append(
            (
                source_root / source_relative_path.with_name(rule.replacement_name),
                "reviewed_normalized_structured_replacement",
            )
        )

    candidates.append((source_root / source_relative_path, "legacy_manifest_path"))

    # Keep ordering stable without probing the same file twice.
    unique: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for candidate, reason in candidates:
        normalized = candidate.resolve(strict=False)
        if normalized not in seen:
            seen.add(normalized)
            unique.append((candidate, reason))
    return unique


def _safe_rule(manifest_category: str, legacy_name: str) -> SafeMaterialRule | None:
    for rule in SAFE_MANIFEST_RULES:
        if rule.manifest_category == manifest_category and rule.manifest_name == legacy_name:
            return rule
    return None


def _item_id(manifest_category: str, source_relative_path: Path) -> str:
    return hashlib.sha256(
        f"{manifest_category}:{source_relative_path.as_posix()}".encode("utf-8")
    ).hexdigest()[:16]


def _manual_review_reason(manifest_category: str) -> str:
    return (
        "未进入自动迁移白名单：该支持性资料可能被通用导入器按文件名或表头投影为错误业务事实；"
        f"请人工确认其作为 {manifest_category} 的分类、用途和导入方式。"
    )


def _build_manifest_identity(manifest: Mapping[str, list[str]]) -> tuple[str, str]:
    portable = {
        str(category): [_legacy_relative_path(value).as_posix() for value in values]
        for category, values in sorted(manifest.items())
    }
    digest = hashlib.sha256(_canonical_json_bytes(portable)).hexdigest()
    return digest, f"{MIGRATION_TOOL_VERSION}-{digest[:16]}"


def load_manifest(manifest_path: Path) -> dict[str, list[str]]:
    try:
        raw = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MigrationPlanError(f"manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise MigrationPlanError(f"manifest is not valid JSON: {manifest_path}") from exc
    if not isinstance(raw, dict):
        raise MigrationPlanError("manifest root must be an object")

    normalized: dict[str, list[str]] = {}
    for category, values in raw.items():
        if not isinstance(category, str) or not isinstance(values, list):
            raise MigrationPlanError("manifest categories must map to path arrays")
        normalized[category] = []
        for value in values:
            if not isinstance(value, str):
                raise MigrationPlanError(f"manifest category {category} contains a non-string path")
            normalized[category].append(value)
    return normalized


def build_migration_plan(
    *,
    source_root: Path | str | None = None,
    manifest_path: Path | str | None = None,
) -> MigrationPlan:
    """Build a plan by touching only the explicit manifest candidates.

    No directory enumeration occurs here.  A source is checked only when its
    exact legacy-derived path or one of the reviewed replacement paths is used.
    """

    root = Path(source_root) if source_root is not None else default_source_root()
    root = root.resolve(strict=False)
    path = Path(manifest_path) if manifest_path is not None else default_manifest_path(root)
    path = path.resolve(strict=False)
    manifest = load_manifest(path)
    manifest_count = sum(len(values) for values in manifest.values())
    manifest_sha256, migration_id = _build_manifest_identity(manifest)
    errors: list[str] = []
    if manifest_count != EXPECTED_MANIFEST_FILE_COUNT:
        errors.append(
            f"reviewed Beijing V2 manifest must contain {EXPECTED_MANIFEST_FILE_COUNT} files; found {manifest_count}"
        )

    items: list[MigrationItem] = []
    for manifest_category, paths in manifest.items():
        for legacy_path in paths:
            relative = _legacy_relative_path(legacy_path)
            rule = _safe_rule(manifest_category, relative.name)
            candidates = _candidate_paths(
                source_root=root,
                source_relative_path=relative,
                manifest_category=manifest_category,
                rule=rule,
            )
            # A rejected derived projection must never replace the manifest's
            # original source. Missing originals are reported by strict
            # preflight instead of silently preserving a normalized derivative.
            if rule and rule.replacement_name and not rule.auto_apply:
                source_path, resolution = root / relative, "legacy_manifest_path"
            else:
                source_path, resolution = next(
                    ((candidate, reason) for candidate, reason in candidates if candidate.is_file()),
                    candidates[-1],
                )
            exists = source_path.is_file()
            safe = bool(rule and rule.auto_apply)
            items.append(
                MigrationItem(
                    item_id=_item_id(manifest_category, relative),
                    manifest_category=manifest_category,
                    doc_category=rule.doc_category if rule else manifest_category,
                    legacy_path=legacy_path,
                    source_relative_path=source_path.relative_to(root).as_posix()
                    if source_path.is_relative_to(root)
                    else relative.as_posix(),
                    source_path=source_path,
                    source_name=source_path.name,
                    safe_to_apply=safe,
                    expected_dataset=rule.expected_dataset if rule else "",
                    resolution=resolution,
                    manual_review_reason=(
                        ""
                        if safe
                        else (
                            rule.manual_review_reason
                            if rule and rule.manual_review_reason
                            else _manual_review_reason(manifest_category)
                        )
                    ),
                    exists=exists,
                    file_size_bytes=source_path.stat().st_size if exists else 0,
                    file_sha256=_sha256_file(source_path) if exists else "",
                )
            )

    # The complete 296-sheet workpaper is deliberately outside manifest.json.
    # It is a reviewed evidence pack and is represented by the controlled
    # case-workpaper importer, never as ledger facts.
    case_root = path.parent.parent
    workpaper_path = case_root / CASE_WORKPAPER_FILE_NAME
    workpaper_exists = workpaper_path.is_file()
    items.append(
        MigrationItem(
            item_id="complete-case-workpaper",
            manifest_category="case_workpaper",
            doc_category="audit_workpapers",
            legacy_path="",
            source_relative_path=workpaper_path.relative_to(root).as_posix()
            if workpaper_path.is_relative_to(root)
            else str(workpaper_path),
            source_path=workpaper_path,
            source_name=workpaper_path.name,
            safe_to_apply=True,
            expected_dataset="audit_workpaper_pack",
            resolution="reviewed_complete_case_workpaper",
            is_case_workpaper=True,
            exists=workpaper_exists,
            file_size_bytes=workpaper_path.stat().st_size if workpaper_exists else 0,
            file_sha256=_sha256_file(workpaper_path) if workpaper_exists else "",
        )
    )

    try:
        manifest_relative_path = path.relative_to(root).as_posix()
    except ValueError:
        manifest_relative_path = path.name
    return MigrationPlan(
        source_root=root,
        manifest_path=path,
        manifest_relative_path=manifest_relative_path,
        manifest_sha256=manifest_sha256,
        migration_id=migration_id,
        manifest_item_count=manifest_count,
        items=tuple(items),
        plan_errors=tuple(errors),
    )


def validate_case_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Validate metadata accepted for deterministic create-or-reuse behavior."""

    raw = dict(metadata.get("case", metadata))
    required = ("case_name", "entity_name", "company_id", "fiscal_year")
    missing = [field for field in required if not str(raw.get(field, "")).strip()]
    if missing:
        raise MigrationPlanError(f"case metadata requires: {', '.join(missing)}")
    try:
        fiscal_year = int(raw["fiscal_year"])
    except (TypeError, ValueError) as exc:
        raise MigrationPlanError("case metadata fiscal_year must be an integer") from exc
    if fiscal_year < 2000 or fiscal_year > 2200:
        raise MigrationPlanError("case metadata fiscal_year is outside the supported range")
    return {
        "case_name": str(raw["case_name"]).strip(),
        "entity_name": str(raw["entity_name"]).strip(),
        "company_id": str(raw["company_id"]).strip(),
        "fiscal_year": fiscal_year,
        "entity_uscc": str(raw.get("entity_uscc") or "").strip() or None,
        "owner_id": str(raw.get("owner_id") or "").strip(),
        "created_by": str(raw.get("created_by") or raw.get("owner_id") or "historical-migration").strip(),
    }


def _validate_safe_item_content(item: MigrationItem, *, period_end: date) -> dict[str, Any]:
    """Prove a reviewed item still matches its reviewed import contract."""

    if not item.exists:
        raise MigrationPlanError(f"safe source is missing: {item.source_relative_path}")
    data = item.source_path.read_bytes()
    from .import_service import (
        is_audit_workpaper_workbook,
        normalize_sheet_rows,
        read_tabular_sheets,
    )
    from .workpaper_case import summarize_workpaper_sheets

    sheets = read_tabular_sheets(item.source_name, data)
    if not sheets:
        raise MigrationPlanError(f"safe source has no readable sheets: {item.source_relative_path}")
    if item.is_case_workpaper:
        if not is_audit_workpaper_workbook(sheets):
            raise MigrationPlanError(f"case workpaper signature is missing: {item.source_relative_path}")
        summary = summarize_workpaper_sheets(sheets, file_name=item.source_name)
        if not summary.get("is_complete_case"):
            raise MigrationPlanError(f"case workpaper is not a complete annual-audit pack: {item.source_relative_path}")
        return {
            "item_id": item.item_id,
            "status": "validated",
            "sheet_count": int(summary.get("sheet_count") or 0),
            "recognized_datasets": ["audit_workpaper_pack"],
        }

    recognized: list[str] = []
    for sheet in sheets:
        normalized = normalize_sheet_rows(
            sheet,
            source_ref=f"preflight://{item.item_id}",
            file_name=item.source_name,
            source_sha256=item.file_sha256,
            source_hint=item.doc_category,
            default_period_end=period_end,
        )
        if normalized is not None:
            recognized.append(str(normalized[0]))
    unique = sorted(set(recognized))
    if item.expected_dataset not in unique:
        raise MigrationPlanError(
            f"safe source did not recognize expected {item.expected_dataset}: {item.source_relative_path}; got {unique}"
        )
    unexpected = sorted(set(unique) - {item.expected_dataset})
    if unexpected:
        raise MigrationPlanError(
            f"safe source recognized unexpected datasets {unexpected}: {item.source_relative_path}"
        )
    return {
        "item_id": item.item_id,
        "status": "validated",
        "sheet_count": len(sheets),
        "recognized_datasets": unique,
    }


def validate_plan(
    plan: MigrationPlan,
    *,
    period_end: date,
    strict: bool = False,
    validator: Callable[[MigrationItem], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Validate every auto-eligible source before any remote write occurs."""

    errors = list(plan.plan_errors)
    report: list[dict[str, Any]] = []
    reviewed_safe_count = sum(1 for rule in SAFE_MANIFEST_RULES if rule.auto_apply) + 1
    if len(plan.safe_items) != reviewed_safe_count:
        errors.append("reviewed automatic allowlist is incomplete")
    for item in plan.safe_items:
        try:
            result = validator(item) if validator else _validate_safe_item_content(item, period_end=period_end)
            report.append({"item_id": item.item_id, "safe_to_apply": True, **dict(result)})
        except Exception as exc:  # noqa: BLE001 - surface all preflight blockers
            message = str(exc)
            report.append({"item_id": item.item_id, "safe_to_apply": True, "status": "failed", "error": message})
            errors.append(message)
    for item in plan.manual_review_items:
        if strict and not item.exists:
            errors.append(f"strict mode: manual-review source is missing: {item.source_relative_path}")
        report.append(
            {
                "item_id": item.item_id,
                "safe_to_apply": False,
                "status": "manual_review_required" if item.exists else "manual_review_source_missing",
                "reason": item.manual_review_reason,
            }
        )
    if errors:
        raise MigrationPlanError("; ".join(errors))
    return report


def stable_batch_id(plan: MigrationPlan, *, case_id: int, doc_category: str) -> str:
    normalized_category = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in str(doc_category).strip().lower()
    ).strip("-")
    if not normalized_category:
        raise MigrationPlanError("doc_category is required for a stable batch id")
    return f"legacy-{plan.migration_id}-{int(case_id)}-{normalized_category}"


def manual_review_batch_id(plan: MigrationPlan, *, case_id: int, doc_category: str) -> str:
    """Keep raw-only review batches separate from structured-projection batches."""

    return f"{stable_batch_id(plan, case_id=case_id, doc_category=doc_category)}-manual-raw"


def _content_type(path: Path) -> str:
    known = {
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".pdf": "application/pdf",
        ".txt": "text/plain; charset=utf-8",
    }
    return known.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _migration_metadata(
    *,
    plan: MigrationPlan,
    items: Iterable[MigrationItem],
    manual_items: Iterable[MigrationItem],
    validation: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "migration_tool": MIGRATION_TOOL_VERSION,
        "migration_id": plan.migration_id,
        "retryable": False,
        "retry_policy": "manual_review_required",
        "retry_disabled_reason": HISTORICAL_RETRY_DISABLED_REASON,
        "manifest_sha256": plan.manifest_sha256,
        "manifest_relative_path": plan.manifest_relative_path,
        "ingest_mode": "safe_raw_metadata_and_reviewed_structured_projection",
        "graph_enrichment": "not_enqueued",
        "safe_files": [
            {
                "item_id": item.item_id,
                "legacy_path": item.legacy_path,
                "source_relative_path": item.source_relative_path,
                "source_sha256": item.file_sha256,
                "resolution": item.resolution,
                "expected_dataset": item.expected_dataset,
            }
            for item in items
        ],
        "manual_review_manifest_items": [
            {
                "item_id": item.item_id,
                "manifest_category": item.manifest_category,
                "legacy_path": item.legacy_path,
                "source_relative_path": item.source_relative_path,
                "reason": item.manual_review_reason,
            }
            for item in manual_items
        ],
        "preflight": list(validation),
    }


def _file_item(item: MigrationItem, uploaded: Any) -> dict[str, Any]:
    return {
        "name": item.source_name,
        "url": uploaded.storage_ref,
        "type": "document",
        "extension": item.source_path.suffix.lower(),
        "content_type": _content_type(item.source_path),
        "content": "",
        "content_ref": uploaded.storage_ref,
        "doc_category": item.doc_category,
        "file_hash": item.file_sha256,
        "file_size": item.file_size_bytes,
        "storage_ref": uploaded.storage_ref,
        "storage_provider": uploaded.storage_provider,
        "storage_bucket": uploaded.storage_bucket,
        "storage_key": uploaded.storage_key,
        "storage_etag": uploaded.storage_etag,
        "storage_version": uploaded.storage_version,
    }


def _raw_review_file_metadata(item: MigrationItem, *, source_root: Path) -> dict[str, Any]:
    """Describe an immutable review source without classifying it as complete material."""

    details: dict[str, Any] = {
        "item_id": item.item_id,
        "legacy_path": item.legacy_path,
        "source_relative_path": item.source_relative_path,
        "source_name": item.source_name,
        "source_sha256": item.file_sha256,
        "file_size_bytes": item.file_size_bytes,
        "resolution": item.resolution,
        "source_role": "original_manifest_file",
        "reason": item.manual_review_reason,
    }
    legacy_name = _legacy_relative_path(item.legacy_path).name if item.legacy_path else item.source_name
    rule = _safe_rule(item.manifest_category, legacy_name)
    if not rule or not rule.replacement_name:
        return details

    derivative_path = item.source_path.with_name(rule.replacement_name)
    if not derivative_path.is_file() or derivative_path == item.source_path:
        return details
    try:
        derivative_relative_path = derivative_path.relative_to(source_root).as_posix()
    except ValueError:
        derivative_relative_path = derivative_path.name
    details["normalized_derivative"] = {
        "source_name": derivative_path.name,
        "source_relative_path": derivative_relative_path,
        "source_sha256": _sha256_file(derivative_path),
        "file_size_bytes": derivative_path.stat().st_size,
        "source_role": "normalized_derivative_previously_preserved",
        "derivative_action": "not_uploaded_by_raw_only_migration",
    }
    return details


def _source_row(file_item: Mapping[str, Any], *, case_id: int, entity_id: int) -> dict[str, Any]:
    return {
        "case_id": int(case_id),
        "entity_id": int(entity_id),
        "file_name": str(file_item["name"]),
        "file_type": str(file_item["type"]),
        "content_type": str(file_item["content_type"]),
        "file_sha256": str(file_item["file_hash"]),
        "file_size_bytes": int(file_item["file_size"]),
        "storage_ref": str(file_item["storage_ref"]),
        "storage_provider": str(file_item["storage_provider"]),
        "storage_bucket": str(file_item["storage_bucket"]),
        "storage_key": str(file_item["storage_key"]),
        "storage_etag": str(file_item["storage_etag"]),
        "storage_version": str(file_item["storage_version"]),
        "ingest_payload_ref": "",
        "ocr_provider": "",
        "ocr_version": "",
        "parser_version": MIGRATION_TOOL_VERSION,
        "status": "active",
    }


def _upsert_batch_and_event(
    *,
    kg_service: Any,
    batch_id: str,
    case_id: int,
    entity_id: int,
    doc_category: str,
    batch_name: str,
    operator_id: str,
    operator_name: str,
    file_count: int,
    status: str,
    records_inserted: int,
    metadata: dict[str, Any],
    error_message: str = "",
    stage: str | None = None,
) -> None:
    material_event_id = f"historical-migration:{batch_id}"
    resolved_stage = stage or {
        "processing": "historical_migration_running",
        "completed": "completed",
        "failed": "manual_review_required",
    }.get(status, status)
    persisted_metadata = {
        **metadata,
        "material_event_id": material_event_id,
        "stage": resolved_stage,
        "retryable": False,
        "retry_policy": "manual_review_required",
        "retry_disabled_reason": HISTORICAL_RETRY_DISABLED_REASON,
    }
    kg_service.upsert_source_upload_batch(
        {
            "upload_batch_id": batch_id,
            "case_id": int(case_id),
            "entity_id": int(entity_id),
            "batch_name": batch_name,
            "doc_category": doc_category,
            "operator_id": operator_id,
            "operator_name": operator_name,
            "status": status,
            "file_count": file_count,
            "new_file_count": file_count,
            "duplicate_file_count": 0,
            "suspected_mismatch_file_count": 0,
            "records_inserted": records_inserted,
            "metadata": persisted_metadata,
        }
    )
    kg_service.upsert_material_event(
        {
            "material_event_id": material_event_id,
            "case_id": int(case_id),
            "entity_id": int(entity_id),
            "upload_batch_id": batch_id,
            "event_type": "historical_manifest_migration",
            "status": status,
            "batch_name": batch_name,
            "doc_category": doc_category,
            "operator_id": operator_id,
            "operator_name": operator_name,
            "file_count": file_count,
            "records_inserted": records_inserted,
            "event_payload": persisted_metadata,
            "error_message": error_message,
        }
    )


def _ensure_existing_batch_sources_match(
    *,
    kg_service: Any,
    plan: MigrationPlan,
    case_id: int,
    grouped: Mapping[str, list[MigrationItem]],
    ordered_categories: Iterable[str],
    batch_id_for_category: Callable[[str], str],
) -> None:
    """Reject a rerun that would mix changed files into an existing batch."""

    fetch_batch = getattr(kg_service, "fetch_source_upload_batch", None)
    if not callable(fetch_batch):
        return
    for doc_category in ordered_categories:
        items = grouped.get(doc_category, [])
        if not items:
            continue
        batch_id = batch_id_for_category(doc_category)
        existing = dict(fetch_batch(batch_id) or {})
        existing_files = [
            item
            for item in existing.get("files", []) or []
            if isinstance(item, Mapping) and str(item.get("file_sha256") or "").strip()
        ]
        if not existing_files:
            continue
        expected_hashes = {item.file_sha256 for item in items}
        existing_hashes = {str(item.get("file_sha256") or "") for item in existing_files}
        if existing_hashes != expected_hashes:
            raise MigrationPlanError(
                "existing historical migration batch has a different source-file set; "
                f"refusing to mix versions: {batch_id}"
            )


def apply_safe_plan(
    plan: MigrationPlan,
    *,
    case_id: int,
    engagement: Mapping[str, Any],
    operator_id: str,
    operator_name: str,
    batch_name: str = "",
    validation: Iterable[dict[str, Any]] = (),
    minio_service: Any | None = None,
    kg_service: Any | None = None,
    importer: Callable[..., dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Persist only the reviewed subset and project verified structured rows.

    The function intentionally does not enqueue the HTTP route's in-process
    OCR/knowledge-graph executor.  A process exit would lose that work and the
    reviewed manual materials must not be fed into filename-based classifiers.
    """

    if int(case_id or 0) <= 0:
        raise MigrationPlanError("case_id must be positive for apply")
    if minio_service is None:
        from ai_hunter.app.services.minio_service import get_minio_service

        minio_service = get_minio_service()
    if kg_service is None:
        from ai_hunter.app.services.kg_service import get_kg_service

        kg_service = get_kg_service()
    uses_runtime_importer = importer is None
    if importer is None:
        from .import_service import import_uploaded_files

        importer = import_uploaded_files

    entity_id = int(case_id)
    entity_name = str(engagement.get("entity_name") or "")
    validation_rows = list(validation)
    outcomes: list[dict[str, Any]] = []
    grouped: dict[str, list[MigrationItem]] = {}
    for item in plan.safe_items:
        grouped.setdefault(item.doc_category, []).append(item)

    ordered_categories = ("audit_workpapers", "trial_balance", "bank_statements", "receivables", "journal_entries")
    _ensure_existing_batch_sources_match(
        kg_service=kg_service,
        plan=plan,
        case_id=case_id,
        grouped=grouped,
        ordered_categories=ordered_categories,
        batch_id_for_category=lambda doc_category: stable_batch_id(
            plan,
            case_id=case_id,
            doc_category=doc_category,
        ),
    )
    for doc_category in ordered_categories:
        items = grouped.get(doc_category, [])
        if not items:
            continue
        batch_id = stable_batch_id(plan, case_id=case_id, doc_category=doc_category)
        display_batch_name = batch_name.strip() or f"历史案例迁移 {plan.migration_id}"
        display_batch_name = f"{display_batch_name} / {doc_category}"
        metadata = _migration_metadata(
            plan=plan,
            items=items,
            manual_items=plan.manual_review_items,
            validation=[row for row in validation_rows if row.get("item_id") in {item.item_id for item in items}],
        )
        records_inserted = 0
        import_summary: dict[str, Any] = {}
        try:
            _upsert_batch_and_event(
                kg_service=kg_service,
                batch_id=batch_id,
                case_id=case_id,
                entity_id=entity_id,
                doc_category=doc_category,
                batch_name=display_batch_name,
                operator_id=operator_id,
                operator_name=operator_name,
                file_count=len(items),
                status="processing",
                records_inserted=0,
                metadata=metadata,
            )
            file_items: list[dict[str, Any]] = []
            for item in items:
                uploaded = minio_service.upload_raw_file(
                    case_id=case_id,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    file_name=item.source_name,
                    content_type=_content_type(item.source_path),
                    file_bytes=item.source_path.read_bytes(),
                )
                file_items.append(_file_item(item, uploaded))

            persisted_files = kg_service.insert_source_files(
                [_source_row(item, case_id=case_id, entity_id=entity_id) for item in file_items]
            )
            linked_files = kg_service.link_source_files_to_upload_batch(
                upload_batch_id=batch_id,
                files=persisted_files,
            )
            if len(linked_files) != len(persisted_files):
                raise RuntimeError("historical migration did not persist every source-file/batch link")
            kg_service.upsert_source_file_doc_categories(
                case_id=case_id,
                category_code=doc_category,
                files=persisted_files,
                match_source="historical_manifest_reviewed",
                confidence=1.0,
                notes=f"{MIGRATION_TOOL_VERSION}; migration_id={plan.migration_id}",
            )
            import_summary = importer(
                engagement_id=case_id,
                files=file_items,
                actor=operator_id,
            )
            metadata = {**metadata, "structured_import": import_summary}
            records_inserted = int(import_summary.get("new_row_count", 0) or 0)
            import_errors = list(import_summary.get("errors") or [])
            import_status = str(import_summary.get("status") or "")
            if import_status != "completed" or import_errors:
                details = "; ".join(
                    str(entry.get("error") or entry)[:240]
                    for entry in import_errors
                )
                raise RuntimeError(
                    "reviewed structured import did not complete"
                    + (f": {details}" if details else f": status={import_status or 'missing'}")
                )
            _upsert_batch_and_event(
                kg_service=kg_service,
                batch_id=batch_id,
                case_id=case_id,
                entity_id=entity_id,
                doc_category=doc_category,
                batch_name=display_batch_name,
                operator_id=operator_id,
                operator_name=operator_name,
                file_count=len(items),
                status="completed",
                records_inserted=records_inserted,
                metadata=metadata,
            )
            outcomes.append(
                {
                    "upload_batch_id": batch_id,
                    "doc_category": doc_category,
                    "status": "completed",
                    "file_count": len(items),
                    "records_inserted": records_inserted,
                    "import_summary": import_summary,
                }
            )
        except Exception as exc:  # noqa: BLE001 - preserve retryable batch metadata
            message = str(exc)
            failure_metadata = {
                **metadata,
                "error": message[:500],
                "partial_success": records_inserted > 0,
            }
            try:
                _upsert_batch_and_event(
                    kg_service=kg_service,
                    batch_id=batch_id,
                    case_id=case_id,
                    entity_id=entity_id,
                    doc_category=doc_category,
                    batch_name=display_batch_name,
                    operator_id=operator_id,
                    operator_name=operator_name,
                    file_count=len(items),
                    status="failed",
                    records_inserted=records_inserted,
                    metadata=failure_metadata,
                    error_message=message[:500],
                )
            except Exception:
                # The original failure is more useful than a best-effort audit
                # update failure.  Deterministic object keys make reruns safe.
                pass
            outcomes.append(
                {
                    "upload_batch_id": batch_id,
                    "doc_category": doc_category,
                    "status": "failed",
                    "file_count": len(items),
                    "records_inserted": records_inserted,
                    "import_summary": import_summary,
                    "error": message,
                }
            )
            break
    if uses_runtime_importer and outcomes and all(
        outcome.get("status") == "completed" for outcome in outcomes
    ):
        from .import_service import backfill_structured_source_anchors

        binding = backfill_structured_source_anchors(case_id)
        unbound_count = int(binding.get("unbound_count") or 0)
        outcomes.append(
            {
                "upload_batch_id": "",
                "doc_category": "evidence_anchors",
                "status": "completed" if unbound_count == 0 else "failed",
                "file_count": int(binding.get("parsed_source_file_count") or 0),
                "records_inserted": int(binding.get("newly_bound_count") or 0),
                "evidence_anchor_binding": binding,
                **(
                    {}
                    if unbound_count == 0
                    else {
                        "error": (
                            "historical structured evidence anchor binding is incomplete: "
                            f"{unbound_count} rows remain unbound"
                        )
                    }
                ),
            }
        )
    return outcomes


def apply_manual_review_raw_plan(
    plan: MigrationPlan,
    *,
    case_id: int,
    engagement: Mapping[str, Any],
    operator_id: str,
    operator_name: str,
    batch_name: str = "",
    validation: Iterable[dict[str, Any]] = (),
    minio_service: Any | None = None,
    kg_service: Any | None = None,
) -> list[dict[str, Any]]:
    """Persist manual-review material as raw evidence without projecting facts."""

    if int(case_id or 0) <= 0:
        raise MigrationPlanError("case_id must be positive for apply")
    if minio_service is None:
        from ai_hunter.app.services.minio_service import get_minio_service

        minio_service = get_minio_service()
    if kg_service is None:
        from ai_hunter.app.services.kg_service import get_kg_service

        kg_service = get_kg_service()

    manual_items = plan.manual_review_items
    missing_items = [item.source_relative_path for item in manual_items if not item.exists]
    if missing_items:
        raise MigrationPlanError(
            "manual-review raw migration requires every reviewed source: "
            + ", ".join(missing_items)
        )

    entity_id = int(case_id)
    entity_name = str(engagement.get("entity_name") or "")
    validation_rows = list(validation)
    grouped: dict[str, list[MigrationItem]] = {}
    for item in manual_items:
        grouped.setdefault(item.doc_category, []).append(item)

    ordered_categories = (
        "financial_statements",
        "revenue_support",
        "confirmations",
        "other",
        "journal_entries",
    )
    expected_manual_counts = {
        "financial_statements": 3,
        "revenue_support": 3,
        "confirmations": 6,
        "other": 2,
        "journal_entries": 1,
    }
    actual_manual_counts = {category: len(items) for category, items in grouped.items()}
    if actual_manual_counts != expected_manual_counts:
        raise MigrationPlanError(
            "reviewed raw-only scope changed; refusing to skip or add manual-review sources: "
            f"{actual_manual_counts}"
        )
    _ensure_existing_batch_sources_match(
        kg_service=kg_service,
        plan=plan,
        case_id=case_id,
        grouped=grouped,
        ordered_categories=ordered_categories,
        batch_id_for_category=lambda doc_category: manual_review_batch_id(
            plan,
            case_id=case_id,
            doc_category=doc_category,
        ),
    )

    outcomes: list[dict[str, Any]] = []
    for doc_category in ordered_categories:
        items = grouped.get(doc_category, [])
        if not items:
            continue
        batch_id = manual_review_batch_id(plan, case_id=case_id, doc_category=doc_category)
        display_batch_name = batch_name.strip() or f"历史案例迁移 {plan.migration_id}"
        display_batch_name = f"{display_batch_name} / {doc_category} / manual_review"
        metadata = {
            **_migration_metadata(
                plan=plan,
                items=(),
                manual_items=manual_items,
                validation=[
                    row
                    for row in validation_rows
                    if row.get("item_id") in {item.item_id for item in items}
                ],
            ),
            "ingest_mode": "raw_only_manual_review",
            "structured_projection": "not_attempted",
            "source_file_doc_categories_written": False,
            "manual_review_only": True,
            "raw_only_files": [
                _raw_review_file_metadata(item, source_root=plan.source_root)
                for item in items
            ],
            "parse_summary": (
                f"已迁移 {len(items)} 个原件；未执行 OCR、图谱或结构化入库，等待人工确认分类和用途。"
            ),
        }
        raw_files_persisted = 0
        try:
            _upsert_batch_and_event(
                kg_service=kg_service,
                batch_id=batch_id,
                case_id=case_id,
                entity_id=entity_id,
                doc_category=doc_category,
                batch_name=display_batch_name,
                operator_id=operator_id,
                operator_name=operator_name,
                file_count=len(items),
                status="processing",
                records_inserted=0,
                metadata=metadata,
            )
            file_items: list[dict[str, Any]] = []
            for item in items:
                uploaded = minio_service.upload_raw_file(
                    case_id=case_id,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    file_name=item.source_name,
                    content_type=_content_type(item.source_path),
                    file_bytes=item.source_path.read_bytes(),
                )
                file_items.append(_file_item(item, uploaded))

            persisted_files = kg_service.insert_source_files(
                [_source_row(item, case_id=case_id, entity_id=entity_id) for item in file_items]
            )
            raw_files_persisted = len(persisted_files)
            linked_files = kg_service.link_source_files_to_upload_batch(
                upload_batch_id=batch_id,
                files=persisted_files,
            )
            if len(linked_files) != len(persisted_files):
                raise RuntimeError("historical raw migration did not persist every source-file/batch link")
            _upsert_batch_and_event(
                kg_service=kg_service,
                batch_id=batch_id,
                case_id=case_id,
                entity_id=entity_id,
                doc_category=doc_category,
                batch_name=display_batch_name,
                operator_id=operator_id,
                operator_name=operator_name,
                file_count=len(items),
                status="completed",
                records_inserted=0,
                metadata=metadata,
                stage="raw_preserved_pending_review",
            )
            outcomes.append(
                {
                    "upload_batch_id": batch_id,
                    "doc_category": doc_category,
                    "status": "completed",
                    "stage": "raw_preserved_pending_review",
                    "file_count": len(items),
                    "records_inserted": 0,
                    "raw_only": True,
                }
            )
        except Exception as exc:  # noqa: BLE001 - preserve a retry-safe audit record
            message = str(exc)
            failure_metadata = {
                **metadata,
                "error": message[:500],
                "raw_files_persisted": raw_files_persisted,
            }
            try:
                _upsert_batch_and_event(
                    kg_service=kg_service,
                    batch_id=batch_id,
                    case_id=case_id,
                    entity_id=entity_id,
                    doc_category=doc_category,
                    batch_name=display_batch_name,
                    operator_id=operator_id,
                    operator_name=operator_name,
                    file_count=len(items),
                    status="failed",
                    records_inserted=0,
                    metadata=failure_metadata,
                    error_message=message[:500],
                    stage="manual_review_required",
                )
            except Exception:
                pass
            outcomes.append(
                {
                    "upload_batch_id": batch_id,
                    "doc_category": doc_category,
                    "status": "failed",
                    "stage": "manual_review_required",
                    "file_count": len(items),
                    "records_inserted": 0,
                    "raw_only": True,
                    "error": message,
                }
            )
            break
    return outcomes


def execute_migration(
    *,
    plan: MigrationPlan,
    apply: bool,
    case_id: int | None = None,
    case_metadata: Mapping[str, Any] | None = None,
    operator_id: str = "historical-migration",
    operator_name: str = "historical-migration",
    batch_name: str = "",
    strict: bool = False,
    validator: Callable[[MigrationItem], dict[str, Any]] | None = None,
    minio_service: Any | None = None,
    kg_service: Any | None = None,
    importer: Callable[..., dict[str, Any]] | None = None,
) -> MigrationExecutionReport:
    """Execute a dry-run or the reviewed write path.

    A metadata-driven engagement is created only after every local safe-source
    preflight passes, so a malformed package cannot leave an empty project.
    """

    metadata = validate_case_metadata(case_metadata) if case_metadata is not None else None
    report = MigrationExecutionReport(plan=plan, mode="apply" if apply else "dry_run")
    if case_id is not None:
        report.case_id = int(case_id)
        report.case_action = "existing_case"
    elif metadata is not None:
        report.case_action = "create_or_reuse_from_metadata"
    if not apply:
        period_end = date(int(metadata["fiscal_year"]), 12, 31) if metadata else date.today()
        try:
            report.validation = validate_plan(plan, period_end=period_end, strict=strict, validator=validator)
        except MigrationPlanError as exc:
            report.errors.append(str(exc))
        return report

    if case_id is None and metadata is None:
        report.errors.append("--apply requires --case-id or --metadata")
        return report

    from .engagement_repository import create_engagement, get_engagement

    engagement: dict[str, Any]
    try:
        if case_id is not None:
            engagement = get_engagement(int(case_id))
            report.case_id = int(case_id)
            report.case_action = "existing_case"
        else:
            # Validate local inputs against the requested fiscal period before
            # creating the engagement below.
            provisional_period_end = date(int(metadata["fiscal_year"]), 12, 31)
            report.validation = validate_plan(
                plan,
                period_end=provisional_period_end,
                strict=True,
                validator=validator,
            )
            created = create_engagement(metadata or {})
            report.case_id = int(created["case_id"])
            report.case_action = "reused_case" if created.get("deduplicated") else "created_case"
            engagement = get_engagement(report.case_id)
        if not report.validation:
            period_end = engagement.get("period_end")
            if not isinstance(period_end, date):
                raise MigrationPlanError("engagement has no valid period_end")
            report.validation = validate_plan(plan, period_end=period_end, strict=True, validator=validator)
    except Exception as exc:  # noqa: BLE001 - command prints a structured report
        report.errors.append(str(exc))
        return report

    structured_outcomes = apply_safe_plan(
        plan,
        case_id=int(report.case_id),
        engagement=engagement,
        operator_id=operator_id,
        operator_name=operator_name,
        batch_name=batch_name,
        validation=report.validation,
        minio_service=minio_service,
        kg_service=kg_service,
        importer=importer,
    )
    report.batches.extend(structured_outcomes)
    if not any(item.get("status") == "failed" for item in structured_outcomes):
        raw_review_outcomes = apply_manual_review_raw_plan(
            plan,
            case_id=int(report.case_id),
            engagement=engagement,
            operator_id=operator_id,
            operator_name=operator_name,
            batch_name=batch_name,
            validation=report.validation,
            minio_service=minio_service,
            kg_service=kg_service,
        )
        report.batches.extend(raw_review_outcomes)
    report.errors.extend(
        str(item.get("error")) for item in report.batches if item.get("status") == "failed"
    )
    return report


__all__ = [
    "CASE_WORKPAPER_FILE_NAME",
    "DEFAULT_MANIFEST_RELATIVE_PATH",
    "EXPECTED_MANIFEST_FILE_COUNT",
    "MIGRATION_TOOL_VERSION",
    "MigrationExecutionReport",
    "MigrationItem",
    "MigrationPlan",
    "MigrationPlanError",
    "SAFE_MANIFEST_RULES",
    "apply_manual_review_raw_plan",
    "apply_safe_plan",
    "build_migration_plan",
    "default_manifest_path",
    "default_source_root",
    "execute_migration",
    "load_manifest",
    "manual_review_batch_id",
    "stable_batch_id",
    "validate_case_metadata",
    "validate_plan",
]

"""Pure assembly of immutable attachment-generation context snapshots."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .fact_registry import FactRegistry
from .financial_statements import FinancialStatementsContext


class ReportSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, populate_by_name=True)

    report_id: int = Field(alias="id", gt=0)
    report_version: int = Field(alias="version", gt=0)
    fact_snapshot_sha256: str
    opinion_type: str = ""
    status: str = "draft"

    @field_validator("fact_snapshot_sha256")
    @classmethod
    def validate_snapshot_sha(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("fact_snapshot_sha256 must contain 64 lowercase hex characters")
        return normalized


class GenerationContextSnapshot(BaseModel):
    """All authoritative inputs frozen for one attachment-generation attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_version: str = "1.0"
    engagement: dict[str, Any]
    entity_facts: dict[str, Any]
    report: ReportSnapshot
    financial_statements: FinancialStatementsContext | dict[str, Any] = Field(
        default_factory=dict,
        union_mode="left_to_right",
    )
    financial_statement_validation: dict[str, Any] = Field(default_factory=dict)
    audit_program: list[Any] = Field(default_factory=list)
    findings: list[Any] = Field(default_factory=list)
    corrections: list[Any] = Field(default_factory=list)
    reviews: list[Any] = Field(default_factory=list)
    release_gate: dict[str, Any] = Field(default_factory=dict)
    materials: list[Any] = Field(default_factory=list)
    evidence_manifest: dict[str, Any] = Field(default_factory=dict)
    policy_binding: dict[str, Any] = Field(default_factory=dict)
    generation_policy_version: str

    @field_validator("generation_policy_version")
    @classmethod
    def validate_policy_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("generation_policy_version is required")
        return normalized

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", by_alias=True))

    @property
    def snapshot_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def build_generation_context_snapshot(
    *,
    engagement: Mapping[str, Any],
    report: ReportSnapshot | Mapping[str, Any],
    generation_policy_version: str,
    entity_facts: Mapping[str, Any] | None = None,
    fact_registry: FactRegistry | None = None,
    financial_statements: FinancialStatementsContext | Mapping[str, Any] | None = None,
    financial_statement_validation: Mapping[str, Any] | None = None,
    audit_program: list[Any] | tuple[Any, ...] = (),
    findings: list[Any] | tuple[Any, ...] = (),
    corrections: list[Any] | tuple[Any, ...] = (),
    reviews: list[Any] | tuple[Any, ...] = (),
    release_gate: Mapping[str, Any] | None = None,
    materials: list[Any] | tuple[Any, ...] = (),
    evidence_manifest: Mapping[str, Any] | None = None,
    policy_binding: Mapping[str, Any] | None = None,
) -> GenerationContextSnapshot:
    """Build a stable snapshot without reading databases or object storage.

    Callers load and authorize data before invoking this function.  The input is
    JSON-normalized and deep-copied so later mutations to repository rows cannot
    alter the frozen snapshot or its SHA-256.
    """

    if entity_facts is not None and fact_registry is not None:
        raise ValueError("provide either entity_facts or fact_registry, not both")
    report_value = _normalize_report(report)
    fact_value = fact_registry.frozen_snapshot() if fact_registry is not None else dict(entity_facts or {})

    payload = {
        "engagement": _copy_supported(dict(engagement)),
        "entity_facts": _copy_supported(fact_value),
        "report": report_value,
        "financial_statements": _copy_supported(financial_statements or {}),
        "financial_statement_validation": _copy_supported(
            dict(financial_statement_validation or {})
        ),
        "audit_program": _copy_supported(list(audit_program)),
        "findings": _copy_supported(list(findings)),
        "corrections": _copy_supported(list(corrections)),
        "reviews": _copy_supported(list(reviews)),
        "release_gate": _copy_supported(dict(release_gate or {})),
        "materials": _copy_supported(list(materials)),
        "evidence_manifest": _copy_supported(dict(evidence_manifest or {})),
        "policy_binding": _copy_supported(dict(policy_binding or {})),
        "generation_policy_version": generation_policy_version,
    }
    return GenerationContextSnapshot.model_validate(payload)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _freeze_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _normalize_report(report: ReportSnapshot | Mapping[str, Any]) -> ReportSnapshot:
    if isinstance(report, ReportSnapshot):
        return report
    payload = copy.deepcopy(dict(report))
    if "id" not in payload and "report_id" in payload:
        payload["id"] = payload["report_id"]
    if "version" not in payload and "report_version" in payload:
        payload["version"] = payload["report_version"]
    if not payload.get("fact_snapshot_sha256"):
        if "fact_snapshot" in payload:
            fact_snapshot = payload["fact_snapshot"]
        elif "fact_snapshot_json" in payload:
            fact_snapshot = payload["fact_snapshot_json"]
        else:
            raise ValueError("report requires fact_snapshot_sha256 or fact_snapshot")
        payload["fact_snapshot_sha256"] = hashlib.sha256(
            canonical_json_bytes(fact_snapshot)
        ).hexdigest()
    return ReportSnapshot.model_validate(payload)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _freeze_json(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _freeze_json(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_freeze_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"generation context contains unsupported value: {type(value).__name__}")


def _copy_supported(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _copy_supported(value.model_dump(mode="python", by_alias=True))
    if isinstance(value, (Decimal, date, datetime)):
        return copy.deepcopy(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _copy_supported(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_copy_supported(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"generation context contains unsupported value: {type(value).__name__}")


__all__ = [
    "GenerationContextSnapshot",
    "ReportSnapshot",
    "build_generation_context_snapshot",
    "canonical_json_bytes",
]

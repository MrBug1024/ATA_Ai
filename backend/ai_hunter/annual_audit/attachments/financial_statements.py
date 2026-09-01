"""Strict financial-statement inputs for annual-audit attachments.

The attachment pipeline must not derive a complete set of financial statements
from trial-balance fragments or local audit analyses.  This module defines the
only accepted report-snapshot contract and projects it into renderer-friendly
rows after validating source evidence and declared reconciliations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


StatementType = Literal["balance_sheet", "income_statement", "cash_flow_statement"]
AmountField = Literal["current_amount", "comparative_amount"]
FinancialLineRole = Literal[
    "balance.cash_and_cash_equivalents",
    "balance.total_assets",
    "balance.total_liabilities",
    "balance.total_equity",
    "income.operating_revenue",
    "income.operating_profit",
    "income.profit_before_tax",
    "income.net_profit",
    "cash_flow.cash_beginning",
    "cash_flow.net_cash_change",
    "cash_flow.cash_ending",
]

_REQUIRED_LINE_ROLES: dict[StatementType, frozenset[str]] = {
    "balance_sheet": frozenset(
        {
            "balance.cash_and_cash_equivalents",
            "balance.total_assets",
            "balance.total_liabilities",
            "balance.total_equity",
        }
    ),
    "income_statement": frozenset(
        {
            "income.operating_revenue",
            "income.operating_profit",
            "income.profit_before_tax",
            "income.net_profit",
        }
    ),
    "cash_flow_statement": frozenset(
        {
            "cash_flow.cash_beginning",
            "cash_flow.net_cash_change",
            "cash_flow.cash_ending",
        }
    ),
}
_FORMAL_RECONCILIATION_ROLES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "balance_equation": (
        frozenset({"balance.total_assets"}),
        frozenset({"balance.total_liabilities", "balance.total_equity"}),
    ),
    "cash_to_balance_sheet": (
        frozenset({"balance.cash_and_cash_equivalents"}),
        frozenset({"cash_flow.cash_ending"}),
    ),
    "cash_movement": (
        frozenset({"cash_flow.cash_ending"}),
        frozenset({"cash_flow.cash_beginning", "cash_flow.net_cash_change"}),
    ),
}

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _required_text(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("value must not be blank")
    return normalized


def _identifier(value: str) -> str:
    normalized = _required_text(value)
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError("value must be a canonical dotted identifier")
    return normalized


def _finite_decimal(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("amount must be finite")
    return value


class FinancialStatementSourceLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page_no: int | None = Field(default=None, gt=0)
    sheet_name: str | None = Field(default=None, max_length=255)
    cell_range: str | None = Field(default=None, max_length=128)
    row_number: int | None = Field(default=None, gt=0)
    row_start: int | None = Field(default=None, gt=0)
    row_end: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_pairs(self) -> "FinancialStatementSourceLocator":
        if bool(self.sheet_name) != bool(self.cell_range or self.row_number):
            raise ValueError("sheet_name requires a cell_range or row_number, and vice versa")
        if bool(self.row_start) != bool(self.row_end):
            raise ValueError("row_start and row_end must be provided together")
        if self.row_start and self.row_end and self.row_end < self.row_start:
            raise ValueError("row_end must not precede row_start")
        return self

    @property
    def has_locator(self) -> bool:
        return bool(self.page_no or self.sheet_name or self.row_start)


class FinancialStatementEvidenceRef(BaseModel):
    """A case-owned source file plus an immutable position inside that file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_file_id: int = Field(gt=0)
    source_page_id: int | None = Field(default=None, gt=0)
    source_chunk_id: str | None = Field(default=None, max_length=255)
    source_sha256: str
    source_locator: FinancialStatementSourceLocator = Field(
        default_factory=FinancialStatementSourceLocator
    )

    @field_validator("source_chunk_id")
    @classmethod
    def normalize_chunk_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value)

    @field_validator("source_sha256")
    @classmethod
    def validate_source_sha(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("source_sha256 must contain 64 lowercase hex characters")
        return normalized

    @model_validator(mode="after")
    def validate_anchor(self) -> "FinancialStatementEvidenceRef":
        if not (self.source_page_id or self.source_chunk_id or self.source_locator.has_locator):
            raise ValueError("evidence requires a page, chunk, sheet cell, or row locator")
        return self

    @property
    def token(self) -> str:
        if self.source_chunk_id:
            locator = f"chunk:{self.source_chunk_id}"
        elif self.source_page_id:
            locator = f"page-id:{self.source_page_id}"
        elif self.source_locator.page_no:
            locator = f"page:{self.source_locator.page_no}"
        elif self.source_locator.sheet_name:
            position = self.source_locator.cell_range or f"row-{self.source_locator.row_number}"
            locator = f"sheet:{self.source_locator.sheet_name}:{position}"
        else:
            locator = f"rows:{self.source_locator.row_start}-{self.source_locator.row_end}"
        return (
            f"financial-source:file:{self.source_file_id}:"
            f"sha256:{self.source_sha256}:{locator}"
        )


class FinancialStatementLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    line_id: str
    line_name: str = Field(max_length=255)
    current_amount: Decimal
    comparative_amount: Decimal | None = None
    section: str = Field(default="", max_length=255)
    display_order: int = Field(ge=0)
    note_ref: str | None = Field(default=None, max_length=128)
    is_total: bool = False
    semantic_role: FinancialLineRole | None = None
    evidence_refs: list[FinancialStatementEvidenceRef] = Field(min_length=1, max_length=20)

    _validate_line_id = field_validator("line_id")(_identifier)
    _validate_line_name = field_validator("line_name")(_required_text)
    _validate_current_amount = field_validator("current_amount")(_finite_decimal)

    @field_validator("comparative_amount")
    @classmethod
    def validate_comparative_amount(cls, value: Decimal | None) -> Decimal | None:
        return _finite_decimal(value) if value is not None else None

    @field_validator("note_ref")
    @classmethod
    def normalize_note_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _identifier(value)


class FinancialStatement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    statement_type: StatementType
    title: str = Field(max_length=255)
    rows: list[FinancialStatementLine] = Field(min_length=1, max_length=5_000)

    _validate_title = field_validator("title")(_required_text)

    @model_validator(mode="after")
    def validate_rows(self) -> "FinancialStatement":
        line_ids = [row.line_id for row in self.rows]
        if len(set(line_ids)) != len(line_ids):
            raise ValueError("statement line_id values must be unique")
        orders = [row.display_order for row in self.rows]
        if len(set(orders)) != len(orders):
            raise ValueError("statement display_order values must be unique")
        return self


class FinancialStatementLineRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    statement_type: StatementType
    line_id: str

    _validate_line_id = field_validator("line_id")(_identifier)


class FinancialStatementNote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    note_id: str
    title: str = Field(max_length=255)
    paragraphs: list[str] = Field(min_length=1, max_length=500)
    line_refs: list[FinancialStatementLineRef] = Field(default_factory=list, max_length=500)
    evidence_refs: list[FinancialStatementEvidenceRef] = Field(min_length=1, max_length=100)

    _validate_note_id = field_validator("note_id")(_identifier)
    _validate_title = field_validator("title")(_required_text)

    @field_validator("paragraphs")
    @classmethod
    def validate_paragraphs(cls, values: list[str]) -> list[str]:
        return [_required_text(value) for value in values]


class ReconciliationTerm(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    statement_type: StatementType
    line_id: str
    amount_field: AmountField = "current_amount"
    coefficient: Decimal = Decimal("1")

    _validate_line_id = field_validator("line_id")(_identifier)

    @field_validator("coefficient")
    @classmethod
    def validate_coefficient(cls, value: Decimal) -> Decimal:
        finite = _finite_decimal(value)
        if finite == 0:
            raise ValueError("reconciliation coefficient must not be zero")
        return finite


class FinancialStatementReconciliation(BaseModel):
    """A declared equality whose amounts are always recomputed by the platform."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str
    kind: Literal[
        "balance_equation",
        "cash_to_balance_sheet",
        "cash_movement",
        "other",
    ]
    description: str = Field(max_length=1_000)
    left_terms: list[ReconciliationTerm] = Field(min_length=1, max_length=100)
    right_terms: list[ReconciliationTerm] = Field(min_length=1, max_length=100)
    tolerance: Decimal = Field(default=Decimal("0"), ge=0)

    _validate_check_id = field_validator("check_id")(_identifier)
    _validate_description = field_validator("description")(_required_text)
    _validate_tolerance = field_validator("tolerance")(_finite_decimal)


class FinancialStatementNoteTieOut(BaseModel):
    """A note amount tied to exactly one referenced statement line."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    note_id: str
    statement_type: StatementType
    line_id: str
    current_note_amount: Decimal
    comparative_note_amount: Decimal | None = None
    tolerance: Decimal = Field(default=Decimal("0"), ge=0)
    evidence_refs: list[FinancialStatementEvidenceRef] = Field(min_length=1, max_length=100)

    _validate_note_id = field_validator("note_id")(_identifier)
    _validate_line_id = field_validator("line_id")(_identifier)
    _validate_current_amount = field_validator("current_note_amount")(_finite_decimal)
    _validate_tolerance = field_validator("tolerance")(_finite_decimal)

    @field_validator("comparative_note_amount")
    @classmethod
    def validate_comparative_amount(cls, value: Decimal | None) -> Decimal | None:
        return _finite_decimal(value) if value is not None else None


class FinancialStatementPackage(BaseModel):
    """Complete, approved structured input frozen into one report version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    approval_status: Literal["approved"]
    approved_by: str = Field(max_length=128)
    approved_at: datetime
    source_revision: str = Field(max_length=255)
    currency: str = Field(min_length=3, max_length=3)
    unit: Decimal = Field(default=Decimal("1"), gt=0)
    period_start: date
    period_end: date
    comparative_period_start: date | None = None
    comparative_period_end: date | None = None
    balance_sheet: FinancialStatement
    income_statement: FinancialStatement
    cash_flow_statement: FinancialStatement
    notes: list[FinancialStatementNote] = Field(min_length=1, max_length=1_000)
    note_tie_outs: list[FinancialStatementNoteTieOut] = Field(
        default_factory=list, max_length=5_000
    )
    reconciliations: list[FinancialStatementReconciliation] = Field(
        default_factory=list, max_length=100
    )

    _validate_approved_by = field_validator("approved_by")(_required_text)
    _validate_source_revision = field_validator("source_revision")(_required_text)
    _validate_unit = field_validator("unit")(_finite_decimal)

    @field_validator("approved_at")
    @classmethod
    def validate_approved_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approved_at must include an explicit timezone")
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", normalized):
            raise ValueError("currency must be a three-letter ISO code")
        return normalized

    @model_validator(mode="after")
    def validate_package(self) -> "FinancialStatementPackage":
        if self.period_end < self.period_start:
            raise ValueError("period_end must not precede period_start")
        if bool(self.comparative_period_start) != bool(self.comparative_period_end):
            raise ValueError("comparative period dates must be supplied together")
        if (
            self.comparative_period_start
            and self.comparative_period_end
            and self.comparative_period_end < self.comparative_period_start
        ):
            raise ValueError("comparative_period_end must not precede comparative_period_start")
        if self.comparative_period_end and self.comparative_period_end >= self.period_start:
            raise ValueError("comparative period must end before the current period starts")

        statements = self.statement_map
        rows_by_key: dict[tuple[StatementType, str], FinancialStatementLine] = {}
        rows_by_role: dict[str, FinancialStatementLine] = {}
        for expected_type, statement in statements.items():
            if statement.statement_type != expected_type:
                raise ValueError(f"{expected_type} contains the wrong statement_type")
            has_comparative_period = self.comparative_period_start is not None
            for row in statement.rows:
                if has_comparative_period != (row.comparative_amount is not None):
                    raise ValueError(
                        "every row must contain comparative_amount exactly when a comparative period exists"
                    )
                rows_by_key[(expected_type, row.line_id)] = row
                if row.semantic_role is not None:
                    if row.semantic_role not in _REQUIRED_LINE_ROLES[expected_type]:
                        raise ValueError(
                            f"semantic role {row.semantic_role} is invalid for {expected_type}"
                        )
                    if row.semantic_role in rows_by_role:
                        raise ValueError(f"semantic role {row.semantic_role} must be unique")
                    rows_by_role[row.semantic_role] = row
            present_roles = {
                row.semantic_role for row in statement.rows if row.semantic_role is not None
            }
            missing_roles = sorted(_REQUIRED_LINE_ROLES[expected_type] - present_roles)
            if missing_roles:
                raise ValueError(
                    f"{expected_type} is missing required semantic roles: "
                    + ", ".join(missing_roles)
                )

        note_ids = [note.note_id for note in self.notes]
        if len(set(note_ids)) != len(note_ids):
            raise ValueError("note_id values must be unique")
        line_keys = set(rows_by_key)
        notes_by_id = set(note_ids)
        notes_by_key = {note.note_id: note for note in self.notes}
        note_line_keys = {
            note.note_id: {
                (reference.statement_type, reference.line_id)
                for reference in note.line_refs
            }
            for note in self.notes
        }
        for statement_type, statement in statements.items():
            for row in statement.rows:
                if row.note_ref and row.note_ref not in notes_by_id:
                    raise ValueError(
                        f"{statement_type}.{row.line_id} references an unavailable note"
                    )
        for note in self.notes:
            for reference in note.line_refs:
                key = (reference.statement_type, reference.line_id)
                if key not in line_keys:
                    raise ValueError(f"note {note.note_id} references an unavailable statement line")
                if rows_by_key[key].note_ref != note.note_id:
                    raise ValueError(
                        f"note {note.note_id} line_refs must match the statement line note_ref"
                    )

        tie_outs_by_line: dict[tuple[StatementType, str], list[FinancialStatementNoteTieOut]] = {}
        for tie_out in self.note_tie_outs:
            key = (tie_out.statement_type, tie_out.line_id)
            row = rows_by_key.get(key)
            note = notes_by_key.get(tie_out.note_id)
            if row is None or note is None:
                raise ValueError("note tie-out references an unavailable note or statement line")
            if row.note_ref != tie_out.note_id:
                raise ValueError("note tie-out does not match the statement line note_ref")
            if key not in note_line_keys[tie_out.note_id]:
                raise ValueError("note tie-out line is not declared in the note line_refs")
            if tie_out.tolerance != 0:
                raise ValueError("formal note tie-outs require zero tolerance")
            has_comparative_period = self.comparative_period_start is not None
            if has_comparative_period != (tie_out.comparative_note_amount is not None):
                raise ValueError(
                    "note tie-out comparative amount must match the comparative-period contract"
                )
            if abs(row.current_amount - tie_out.current_note_amount) > tie_out.tolerance:
                raise ValueError(
                    f"note tie-out {tie_out.note_id} failed for current_amount"
                )
            if (
                row.comparative_amount is not None
                and tie_out.comparative_note_amount is not None
                and abs(row.comparative_amount - tie_out.comparative_note_amount)
                > tie_out.tolerance
            ):
                raise ValueError(
                    f"note tie-out {tie_out.note_id} failed for comparative_amount"
                )
            tie_outs_by_line.setdefault(key, []).append(tie_out)
        for key, row in rows_by_key.items():
            matches = tie_outs_by_line.get(key, [])
            if row.note_ref and len(matches) != 1:
                raise ValueError(
                    f"statement line {key[0]}.{key[1]} requires exactly one note tie-out"
                )
            if not row.note_ref and matches:
                raise ValueError(
                    f"statement line {key[0]}.{key[1]} has a tie-out without note_ref"
                )

        check_ids = [check.check_id for check in self.reconciliations]
        if len(set(check_ids)) != len(check_ids):
            raise ValueError("reconciliation check_id values must be unique")
        required_kinds = set(_FORMAL_RECONCILIATION_ROLES)
        covered_formal_checks: set[tuple[str, AmountField]] = set()
        for check in self.reconciliations:
            terms = [*check.left_terms, *check.right_terms]
            statement_types = {term.statement_type for term in terms}
            if check.kind == "balance_equation" and statement_types != {"balance_sheet"}:
                raise ValueError("balance_equation must only reference balance_sheet lines")
            if check.kind == "cash_to_balance_sheet" and statement_types != {
                "balance_sheet",
                "cash_flow_statement",
            }:
                raise ValueError(
                    "cash_to_balance_sheet must reference balance_sheet and cash_flow_statement"
                )
            if check.kind == "cash_to_balance_sheet":
                left_types = {term.statement_type for term in check.left_terms}
                right_types = {term.statement_type for term in check.right_terms}
                if {frozenset(left_types), frozenset(right_types)} != {
                    frozenset({"balance_sheet"}),
                    frozenset({"cash_flow_statement"}),
                }:
                    raise ValueError(
                        "cash_to_balance_sheet must place each statement on a separate side"
                    )
            if check.kind == "cash_movement" and statement_types != {
                "cash_flow_statement"
            }:
                raise ValueError("cash_movement must only reference cash_flow_statement lines")
            if check.kind in required_kinds:
                amount_fields = {term.amount_field for term in terms}
                if len(amount_fields) != 1:
                    raise ValueError(
                        f"formal reconciliation {check.check_id} cannot mix amount fields"
                    )
                amount_field = next(iter(amount_fields))
                try:
                    left_roles = [
                        rows_by_key[(term.statement_type, term.line_id)].semantic_role
                        for term in check.left_terms
                    ]
                    right_roles = [
                        rows_by_key[(term.statement_type, term.line_id)].semantic_role
                        for term in check.right_terms
                    ]
                except KeyError as exc:
                    raise ValueError(
                        f"formal reconciliation {check.check_id} references an unavailable line"
                    ) from exc
                if any(term.coefficient != Decimal("1") for term in terms):
                    raise ValueError(
                        f"formal reconciliation {check.check_id} requires coefficient 1"
                    )
                expected_left, expected_right = _FORMAL_RECONCILIATION_ROLES[check.kind]
                actual_sides = {frozenset(left_roles), frozenset(right_roles)}
                expected_sides = {expected_left, expected_right}
                if (
                    actual_sides != expected_sides
                    or len(left_roles) != len(set(left_roles))
                    or len(right_roles) != len(set(right_roles))
                ):
                    raise ValueError(
                        f"formal reconciliation {check.check_id} must use the canonical semantic roles"
                    )
                if check.tolerance != 0:
                    raise ValueError(
                        f"formal reconciliation {check.check_id} requires zero tolerance"
                    )
                covered_formal_checks.add((check.kind, amount_field))
            result = self._evaluate_reconciliation(check, rows_by_key=rows_by_key)
            if abs(result["difference"]) > check.tolerance:
                raise ValueError(
                    f"reconciliation {check.check_id} failed: absolute difference exceeds tolerance"
                )
        required_checks = {(kind, "current_amount") for kind in required_kinds}
        if self.comparative_period_start is not None:
            required_checks.update((kind, "comparative_amount") for kind in required_kinds)
        missing_checks = sorted(required_checks - covered_formal_checks)
        if missing_checks:
            raise ValueError(
                "missing required formal reconciliations: "
                + ", ".join(f"{kind}.{amount_field}" for kind, amount_field in missing_checks)
            )
        return self

    @property
    def statement_map(self) -> dict[StatementType, FinancialStatement]:
        return {
            "balance_sheet": self.balance_sheet,
            "income_statement": self.income_statement,
            "cash_flow_statement": self.cash_flow_statement,
        }

    def _line_index(self) -> dict[tuple[StatementType, str], FinancialStatementLine]:
        return {
            (statement_type, row.line_id): row
            for statement_type, statement in self.statement_map.items()
            for row in statement.rows
        }

    def _amount_for(
        self,
        term: ReconciliationTerm,
        *,
        rows_by_key: Mapping[tuple[StatementType, str], FinancialStatementLine],
    ) -> Decimal:
        row = rows_by_key.get((term.statement_type, term.line_id))
        if row is None:
            raise ValueError(
                f"reconciliation references unavailable line {term.statement_type}.{term.line_id}"
            )
        value = getattr(row, term.amount_field)
        if value is None:
            raise ValueError(
                f"reconciliation references unavailable {term.amount_field} on "
                f"{term.statement_type}.{term.line_id}"
            )
        return value * term.coefficient

    def _evaluate_reconciliation(
        self,
        check: FinancialStatementReconciliation,
        *,
        rows_by_key: Mapping[tuple[StatementType, str], FinancialStatementLine] | None = None,
    ) -> dict[str, Decimal | bool]:
        index = rows_by_key or self._line_index()
        left_amount = sum(
            (self._amount_for(term, rows_by_key=index) for term in check.left_terms),
            Decimal("0"),
        )
        right_amount = sum(
            (self._amount_for(term, rows_by_key=index) for term in check.right_terms),
            Decimal("0"),
        )
        difference = left_amount - right_amount
        return {
            "left_amount": left_amount,
            "right_amount": right_amount,
            "difference": difference,
            "passed": abs(difference) <= check.tolerance,
        }

    def reconciliation_results(self) -> list[dict[str, Any]]:
        rows_by_key = self._line_index()
        return [
            {
                "check_id": check.check_id,
                "kind": check.kind,
                "description": check.description,
                "left_amount": result["left_amount"],
                "right_amount": result["right_amount"],
                "difference": result["difference"],
                "tolerance": check.tolerance,
                "passed": result["passed"],
            }
            for check in self.reconciliations
            for result in (self._evaluate_reconciliation(check, rows_by_key=rows_by_key),)
        ]

    def evidence_references(self) -> list[dict[str, Any]]:
        """Return each unique source anchor in the platform evidence shape."""

        references: dict[str, FinancialStatementEvidenceRef] = {}
        for statement in self.statement_map.values():
            for row in statement.rows:
                for reference in row.evidence_refs:
                    references[reference.token] = reference
        for note in self.notes:
            for reference in note.evidence_refs:
                references[reference.token] = reference
        for tie_out in self.note_tie_outs:
            for reference in tie_out.evidence_refs:
                references[reference.token] = reference
        return [
            references[token].model_dump(mode="json")
            for token in sorted(references)
        ]

    def frozen_report_value(self) -> dict[str, Any]:
        """Return JSON-compatible data suitable for ``fact_snapshot_json``."""

        return self.model_dump(mode="json")

    def renderer_context(self) -> "FinancialStatementsContext":
        evidence_manifest: dict[str, FinancialStatementEvidenceRef] = {}

        def render_rows(statement: FinancialStatement) -> list[FinancialStatementRenderRow]:
            rendered: list[FinancialStatementRenderRow] = []
            for row in sorted(statement.rows, key=lambda item: item.display_order):
                tokens = []
                for reference in row.evidence_refs:
                    evidence_manifest[reference.token] = reference
                    tokens.append(reference.token)
                rendered.append(
                    FinancialStatementRenderRow(
                        line_id=row.line_id,
                        line_name=row.line_name,
                        current_amount=row.current_amount,
                        comparative_amount=row.comparative_amount,
                        section=row.section,
                        display_order=row.display_order,
                        note_ref=row.note_ref,
                        is_total=row.is_total,
                        semantic_role=row.semantic_role,
                        evidence_tokens=tokens,
                    )
                )
            return rendered

        notes = []
        for note in self.notes:
            tokens = []
            for reference in note.evidence_refs:
                evidence_manifest[reference.token] = reference
                tokens.append(reference.token)
            notes.append(
                FinancialStatementNoteRenderRow(
                    note_id=note.note_id,
                    title=note.title,
                    text="\n".join(note.paragraphs),
                    line_refs=", ".join(
                        f"{item.statement_type}.{item.line_id}" for item in note.line_refs
                    ),
                    evidence_tokens=tokens,
                )
            )
        note_tie_outs = []
        for tie_out in self.note_tie_outs:
            tokens = []
            for reference in tie_out.evidence_refs:
                evidence_manifest[reference.token] = reference
                tokens.append(reference.token)
            note_tie_outs.append(
                FinancialStatementNoteTieOutRenderRow(
                    note_id=tie_out.note_id,
                    statement_type=tie_out.statement_type,
                    line_id=tie_out.line_id,
                    current_note_amount=tie_out.current_note_amount,
                    comparative_note_amount=tie_out.comparative_note_amount,
                    tolerance=tie_out.tolerance,
                    evidence_tokens=tokens,
                )
            )
        return FinancialStatementsContext(
            approval_status=self.approval_status,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            source_revision=self.source_revision,
            currency=self.currency,
            unit=self.unit,
            period_start=self.period_start,
            period_end=self.period_end,
            comparative_period_start=self.comparative_period_start,
            comparative_period_end=self.comparative_period_end,
            balance_sheet=render_rows(self.balance_sheet),
            income_statement=render_rows(self.income_statement),
            cash_flow_statement=render_rows(self.cash_flow_statement),
            notes=notes,
            note_tie_outs=note_tie_outs,
            reconciliations=[
                FinancialStatementReconciliationRenderRow.model_validate(item)
                for item in self.reconciliation_results()
            ],
            evidence_manifest=evidence_manifest,
        )


class FinancialStatementRenderRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    line_id: str
    line_name: str
    current_amount: Decimal
    comparative_amount: Decimal | None = None
    section: str = ""
    display_order: int
    note_ref: str | None = None
    is_total: bool = False
    semantic_role: FinancialLineRole | None = None
    evidence_tokens: list[str] = Field(default_factory=list, alias="__evidence_refs__")


class FinancialStatementNoteRenderRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    note_id: str
    title: str
    text: str
    line_refs: str = ""
    evidence_tokens: list[str] = Field(default_factory=list, alias="__evidence_refs__")


class FinancialStatementReconciliationRenderRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str
    kind: Literal[
        "balance_equation",
        "cash_to_balance_sheet",
        "cash_movement",
        "other",
    ]
    description: str
    left_amount: Decimal
    right_amount: Decimal
    difference: Decimal
    tolerance: Decimal
    passed: bool


class FinancialStatementNoteTieOutRenderRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    note_id: str
    statement_type: StatementType
    line_id: str
    current_note_amount: Decimal
    comparative_note_amount: Decimal | None = None
    tolerance: Decimal
    evidence_tokens: list[str] = Field(default_factory=list, alias="__evidence_refs__")


class FinancialStatementsContext(BaseModel):
    """Renderer projection that preserves native Decimal values after reload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    contract_status: Literal["ready"] = "ready"
    approval_status: Literal["approved"]
    approved_by: str
    approved_at: datetime
    source_revision: str
    currency: str
    unit: Decimal
    period_start: date
    period_end: date
    comparative_period_start: date | None = None
    comparative_period_end: date | None = None
    balance_sheet: list[FinancialStatementRenderRow]
    income_statement: list[FinancialStatementRenderRow]
    cash_flow_statement: list[FinancialStatementRenderRow]
    notes: list[FinancialStatementNoteRenderRow] = Field(default_factory=list)
    note_tie_outs: list[FinancialStatementNoteTieOutRenderRow] = Field(default_factory=list)
    reconciliations: list[FinancialStatementReconciliationRenderRow] = Field(default_factory=list)
    evidence_manifest: dict[str, FinancialStatementEvidenceRef] = Field(default_factory=dict)


class FinancialStatementBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    field: str = "financial_statements"
    message: str


class FinancialStatementEvidenceOwnershipError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("财务报表证据不属于当前项目或缺少有效定位")


class FinancialStatementApprovalError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class FinancialStatementAdaptation:
    context: FinancialStatementsContext | None
    blockers: tuple[FinancialStatementBlocker, ...]

    @property
    def status(self) -> Literal["ready", "missing", "invalid"]:
        if self.context is not None:
            return "ready"
        return "missing" if any(item.code == "FINANCIAL_STATEMENTS_MISSING" for item in self.blockers) else "invalid"

    def validation_snapshot(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blockers": [item.model_dump(mode="json") for item in self.blockers],
        }


def adapt_financial_statement_snapshot(value: Any) -> FinancialStatementAdaptation:
    """Validate a frozen report value without inventing or deriving statement rows."""

    if value in (None, {}):
        return FinancialStatementAdaptation(
            context=None,
            blockers=(
                FinancialStatementBlocker(
                    code="FINANCIAL_STATEMENTS_MISSING",
                    message="冻结报告未包含经确认的完整资产负债表、利润表和现金流量表",
                ),
            ),
        )
    if isinstance(value, FinancialStatementPackage):
        package = value
    elif isinstance(value, Mapping):
        try:
            package = FinancialStatementPackage.model_validate(dict(value))
        except ValidationError as exc:
            blockers = []
            for error in exc.errors(include_url=False, include_input=False)[:50]:
                location = ".".join(str(item) for item in error.get("loc") or ())
                blockers.append(
                    FinancialStatementBlocker(
                        code="FINANCIAL_STATEMENTS_INVALID",
                        field=f"financial_statements.{location}".rstrip("."),
                        message=str(error.get("msg") or "财务报表结构化输入不符合合同"),
                    )
                )
            return FinancialStatementAdaptation(context=None, blockers=tuple(blockers))
    else:
        return FinancialStatementAdaptation(
            context=None,
            blockers=(
                FinancialStatementBlocker(
                    code="FINANCIAL_STATEMENTS_INVALID",
                    message="财务报表结构化输入必须是对象",
                ),
            ),
        )
    return FinancialStatementAdaptation(context=package.renderer_context(), blockers=())


__all__ = [
    "FinancialStatement",
    "FinancialStatementAdaptation",
    "FinancialStatementApprovalError",
    "FinancialStatementBlocker",
    "FinancialStatementEvidenceRef",
    "FinancialStatementEvidenceOwnershipError",
    "FinancialStatementLine",
    "FinancialStatementLineRef",
    "FinancialStatementNote",
    "FinancialStatementNoteTieOut",
    "FinancialStatementPackage",
    "FinancialStatementReconciliation",
    "FinancialStatementsContext",
    "ReconciliationTerm",
    "adapt_financial_statement_snapshot",
]

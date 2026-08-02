"""Role-code helpers backed by the editable auth seed file."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any


ROLE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
DEFAULT_AUTH_SEED_FILE = Path(__file__).resolve().parents[3] / "config" / "auth_private_seed.json"


@lru_cache(maxsize=4)
def load_auth_seed(seed_file: str | Path | None = None) -> dict[str, Any]:
    path = Path(seed_file) if seed_file else DEFAULT_AUTH_SEED_FILE
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _seed() -> dict[str, Any]:
    return load_auth_seed()


def super_admin_role_code() -> str:
    value = str(_seed().get("super_admin_role_code") or "")
    if not value:
        raise ValueError("auth seed 缺少 super_admin_role_code")
    return value


def company_admin_role_code() -> str:
    value = str(_seed().get("company_admin_role_code") or "")
    if not value:
        raise ValueError("auth seed 缺少 company_admin_role_code")
    return value


ADMIN_ROLE = super_admin_role_code()
COMPANY_ADMIN_ROLE = company_admin_role_code()


def role_permissions_from_seed(seed: dict[str, Any] | None = None) -> dict[str, dict]:
    data = seed or _seed()
    out: dict[str, dict] = {}
    for role in data.get("roles", []):
        code = canonical_role_code(str(role.get("role_code") or ""))
        if not code:
            continue
        out[code] = {
            "role_name": role.get("role_name") or code,
            "tier": role.get("tier", "field"),
            "modules": role.get("modules", []),
            "visible_report_sections": role.get("visible_report_sections", []),
            "description": role.get("description", ""),
        }
    return out


def report_sections_from_seed(seed: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    data = seed or _seed()
    sections: list[dict[str, Any]] = []
    for item in data.get("report_sections", []):
        section_code = str(item.get("section_code") or "").strip()
        section_id = str(item.get("section_id") or "").strip()
        if not section_code or not section_id:
            continue
        sections.append(
            {
                "section_code": section_code,
                "section_id": section_id,
                "title": str(item.get("title") or ""),
                "audience": str(item.get("audience") or "field"),
                "sort_order": int(item.get("sort_order") or 0),
                "status": str(item.get("status") or "active"),
                "description": str(item.get("description") or ""),
            }
        )
    return sorted(sections, key=lambda row: (int(row["section_id"]) if row["section_id"].isdigit() else 9999, row["section_code"]))


def default_company_from_seed(seed: dict[str, Any] | None = None) -> dict[str, str]:
    data = seed or _seed()
    companies = data.get("companies") or []
    if not companies:
        raise ValueError("auth seed 缺少 companies")
    company = companies[0]
    company_id = str(company.get("company_id") or "")
    company_name = str(company.get("company_name") or "")
    if not company_id or not company_name:
        raise ValueError("auth seed 默认公司缺少 company_id/company_name")
    return {"company_id": company_id, "company_name": company_name}


def _legacy_aliases() -> dict[str, str]:
    aliases = _seed().get("legacy_role_aliases", {})
    if not isinstance(aliases, dict):
        return {}
    return {str(k): str(v) for k, v in aliases.items()}


def canonical_role_code(role_code: str) -> str:
    """Return the stable English role code for legacy or canonical input."""
    value = (role_code or "").strip()
    return _legacy_aliases().get(value, value)


def normalize_roles(role_codes: list[str]) -> list[str]:
    """Normalize role code list while preserving order and removing blanks/duplicates."""
    out: list[str] = []
    seen: set[str] = set()
    for role in role_codes:
        code = canonical_role_code(role)
        if not code or code in seen:
            continue
        out.append(code)
        seen.add(code)
    return out


def role_display_name(role_code: str) -> str:
    code = canonical_role_code(role_code)
    role = role_permissions_from_seed().get(code)
    return str((role or {}).get("role_name") or code)


def validate_role_code(role_code: str) -> str:
    code = canonical_role_code(role_code)
    if not ROLE_CODE_PATTERN.fullmatch(code):
        raise ValueError("role_code 必须使用英文小写字母、数字和下划线，且以字母开头")
    return code

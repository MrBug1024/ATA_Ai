"""Initialize private-mode auth data.

The editable seed file defines companies, roles, permissions, tag catalog, and
bootstrap users. Passwords are never stored in the seed file; provide them via
the per-user password_env value or enter them interactively.

Production deployments that must remain free of demo configuration should use
``--superadmin-only``. It creates only the super-admin role, the local
``superadmin`` credential, and the required audit record.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from typing import Any

from ai_hunter.app.auth.local_auth import hash_password
from ai_hunter.app.auth.roles import (
    ADMIN_ROLE,
    DEFAULT_AUTH_SEED_FILE,
    load_auth_seed,
    normalize_roles,
)
from ai_hunter.app.services.user_service import get_user_service


SUPERADMIN_USER_ID = "local_super_admin"
SUPERADMIN_LOGIN_IDENTIFIER = "superadmin"


def _password_from_env_or_prompt(env_name: str, prompt_label: str) -> str:
    value = os.getenv(env_name, "")
    if not value and env_name != "INIT_ADMIN_PASSWORD":
        value = os.getenv("INIT_ADMIN_PASSWORD", "")
    if value:
        return value
    first = getpass.getpass(f"{prompt_label} password: ")
    second = getpass.getpass(f"Confirm {prompt_label} password: ")
    if first != second:
        raise ValueError("两次输入的密码不一致")
    return first


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize private-mode auth seed data.",
    )
    parser.add_argument("--seed-file", default=str(DEFAULT_AUTH_SEED_FILE), help="auth seed JSON file")
    parser.add_argument("--skip-passwords", action="store_true", help="do not create/update local credentials")
    parser.add_argument(
        "--superadmin-only",
        action="store_true",
        help="create only the production superadmin role and local credential",
    )
    return parser


def _seed_companies(svc, seed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    companies: dict[str, dict[str, Any]] = {}
    for item in seed.get("companies", []):
        row = svc.upsert_company(
            company_id=item.get("company_id") or None,
            company_name=str(item.get("company_name") or ""),
            company_type=str(item.get("company_type") or "customer"),
            status=str(item.get("status") or "active"),
            notes=str(item.get("notes") or ""),
        )
        companies[str(row["company_id"])] = row
    return companies


def _seed_roles(svc, seed: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for role in seed.get("roles", []):
        row = svc.upsert_role_permission(
            str(role.get("role_code") or ""),
            role_name=str(role.get("role_name") or ""),
            tier=str(role.get("tier") or "field"),
            modules=list(role.get("modules") or []),
            description=str(role.get("description") or ""),
        )
        codes.append(str(row["role_code"]))
    return codes


def _seed_report_sections(svc, seed: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for section in seed.get("report_sections", []):
        row = svc.upsert_report_section(
            section_code=str(section.get("section_code") or ""),
            section_id=str(section.get("section_id") or ""),
            title=str(section.get("title") or ""),
            audience=str(section.get("audience") or "field"),
            sort_order=int(section.get("sort_order") or 0),
            status=str(section.get("status") or "active"),
            description=str(section.get("description") or ""),
        )
        codes.append(str(row["section_code"]))
    return codes


def _seed_role_report_sections(svc, seed: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for role in seed.get("roles", []):
        role_code = str(role.get("role_code") or "")
        if not role_code:
            continue
        sections = [str(code) for code in role.get("visible_report_sections", [])]
        out[role_code] = svc.replace_role_report_sections(role_code, sections)
    return out


def _seed_tag_catalog(svc, seed: dict[str, Any]) -> int:
    count = 0
    for item in seed.get("tag_catalog", []):
        svc.upsert_tag_catalog_item(
            dimension=str(item.get("dimension") or ""),
            tag_value=str(item.get("tag_value") or ""),
            tag_group=str(item.get("tag_group") or ""),
            sort_order=int(item.get("sort_order") or 0),
        )
        count += 1
    return count


def _seed_users(svc, seed: dict[str, Any], companies: dict[str, dict[str, Any]], *, skip_passwords: bool) -> list[str]:
    user_ids: list[str] = []
    for user in seed.get("bootstrap_users", []):
        user_id = str(user.get("user_id") or "")
        if not user_id:
            raise ValueError("bootstrap_users.user_id 不能为空")
        company_id = str(user.get("company_id") or "")
        company_name = str((companies.get(company_id) or {}).get("company_name") or "")
        row = svc.upsert_user(
            user_id,
            username=str(user.get("username") or user_id),
            company_id=company_id,
            company=company_name,
            auth_source=str(user.get("auth_source") or "local"),
            status=str(user.get("status") or "active"),
            is_super_admin=bool(user.get("is_super_admin")),
            note=str(user.get("note") or ""),
        )
        login_identifier = str(user.get("login_identifier") or user_id)
        if not skip_passwords:
            password_env = str(user.get("password_env") or "INIT_ADMIN_PASSWORD")
            password = _password_from_env_or_prompt(password_env, login_identifier)
            svc.set_local_password(
                user_id,
                login_identifier=login_identifier,
                password_hash=hash_password(password, username=login_identifier),
            )
        roles = svc.replace_user_roles(
            user_id,
            company_id=company_id,
            roles=normalize_roles([str(role) for role in user.get("roles", [])]),
            assigned_by="system:init_local_admin",
        )
        for dimension, values in dict(user.get("tags") or {}).items():
            svc.set_tags(user_id, str(dimension), [str(value) for value in values])
        svc.write_auth_audit_log(
            event_type="auth_seed_user_initialized",
            actor_id="system:init_local_admin",
            company_id=company_id,
            target_type="user",
            target_id=user_id,
            action="init_or_update_seed_user",
            decision="success",
            detail={
                "login_identifier": login_identifier,
                "roles": roles,
                "tag_dimensions": sorted(dict(user.get("tags") or {}).keys()),
                "is_super_admin": bool(user.get("is_super_admin")),
                "password_set": not skip_passwords,
            },
        )
        print(
            "bootstrap user ready: "
            f"user_id={row['user_id']} login={login_identifier} company_id={company_id!r} roles={','.join(roles)}"
        )
        user_ids.append(user_id)
    return user_ids


def _seed_production_superadmin(svc) -> str:
    """Create the minimum auth records needed for a clean production login."""

    password = _password_from_env_or_prompt(
        "INIT_SUPER_ADMIN_PASSWORD",
        SUPERADMIN_LOGIN_IDENTIFIER,
    )
    password_hash = hash_password(password, username=SUPERADMIN_LOGIN_IDENTIFIER)
    row = svc.bootstrap_production_superadmin(
        user_id=SUPERADMIN_USER_ID,
        username="系统超级管理员",
        login_identifier=SUPERADMIN_LOGIN_IDENTIFIER,
        password_hash=password_hash,
        role_code=ADMIN_ROLE,
    )
    print(
        "production superadmin ready: "
        f"user_id={row['user_id']} login={SUPERADMIN_LOGIN_IDENTIFIER} role={ADMIN_ROLE}"
    )
    return str(row["user_id"])


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.superadmin_only:
        if args.skip_passwords:
            raise ValueError("--superadmin-only cannot be combined with --skip-passwords")
        user_id = _seed_production_superadmin(get_user_service())
        print(f"production auth initialized: bootstrap_users=1 user_id={user_id}")
        return 0

    seed = load_auth_seed(args.seed_file)
    svc = get_user_service()
    companies = _seed_companies(svc, seed)
    roles = _seed_roles(svc, seed)
    report_sections = _seed_report_sections(svc, seed)
    role_report_sections = _seed_role_report_sections(svc, seed)
    tag_count = _seed_tag_catalog(svc, seed)
    users = _seed_users(svc, seed, companies, skip_passwords=args.skip_passwords)
    print(
        "auth seed initialized: "
        f"companies={len(companies)} roles={len(roles)} report_sections={len(report_sections)} "
        f"role_section_roles={len(role_report_sections)} tag_catalog={tag_count} bootstrap_users={len(users)}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI should print a concise failure
        print(f"init_local_admin failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

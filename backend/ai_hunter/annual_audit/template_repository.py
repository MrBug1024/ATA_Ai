"""Backward-compatible facade for the file-backed template repository.

The original JSON registry is retained for imports from older code, while all
current callers are redirected to :mod:`template_file_repository`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from ai_hunter.app.settings import Settings, get_settings

from .storage import mysql_connection


TEMPLATE_TYPES = (
    "annual_report",
    "financial_statements",
    "notes",
    "audit_workpaper",
    "management_letter",
)

TEMPLATE_TYPE_LABELS = {
    "annual_report": "年度审计报告",
    "financial_statements": "财务报表",
    "notes": "财务报表附注",
    "audit_workpaper": "审计工作底稿",
    "management_letter": "管理建议书",
}


DEFAULT_TEMPLATE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "template_code": "annual_audit_report",
        "template_type": "annual_report",
        "name": "年度审计报告模板",
        "description": "年度财务报表审计报告草稿及交付版式",
        "version_label": "customer-audit-report-v2",
        "content": {
            "title": "年度财务报表审计报告",
            "formats": ["docx"],
            "sections": ["项目范围", "审计结果", "审计结论"],
        },
    },
    {
        "template_code": "annual_financial_statements",
        "template_type": "financial_statements",
        "name": "财务报表模板",
        "description": "年度财务报表及核心审计数据汇总模板",
        "version_label": "customer-financial-statements-v1",
        "content": {
            "title": "年度财务报表",
            "sheet_name": "财务报表",
            "formats": ["xlsx"],
        },
    },
    {
        "template_code": "annual_notes",
        "template_type": "notes",
        "name": "财务报表附注模板",
        "description": "财务报表附注交付模板",
        "version_label": "customer-notes-v1",
        "content": {
            "title": "财务报表附注",
            "formats": ["docx"],
            "sections": ["编制基础", "重要会计政策", "主要报表项目说明"],
        },
    },
    {
        "template_code": "annual_audit_workpaper",
        "template_type": "audit_workpaper",
        "name": "审计工作底稿模板",
        "description": "审计循环工作底稿模板",
        "version_label": "customer-workpaper-2023-v1",
        "content": {
            "title": "审计工作底稿",
            "formats": ["xlsx"],
            "sheet_name": "底稿",
        },
    },
    {
        "template_code": "annual_management_letter",
        "template_type": "management_letter",
        "name": "管理建议书模板",
        "description": "基于已确认审计结果的管理建议书模板",
        "version_label": "customer-management-letter-v1",
        "content": {
            "title": "管理建议书",
            "formats": ["docx"],
        },
    },
)


def _json_load(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _safe_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def template_version_ref(template: dict[str, Any]) -> str:
    """Return the immutable label stored on generated artifacts."""

    label = str(template.get("version_label") or "").strip()
    if label:
        return label
    return f"{template.get('template_code') or 'template'}-v{int(template.get('version_no') or 0)}"


def _normalize_template(row: dict[str, Any], version: dict[str, Any] | None = None) -> dict[str, Any]:
    item = {
        "id": int(row.get("id") or 0),
        "template_code": str(row.get("template_code") or ""),
        "template_type": str(row.get("template_type") or ""),
        "template_type_label": TEMPLATE_TYPE_LABELS.get(
            str(row.get("template_type") or ""), str(row.get("template_type") or "")
        ),
        "name": str(row.get("name") or ""),
        "description": str(row.get("description") or ""),
        "status": str(row.get("status") or "active"),
        "active_version_no": int(row.get("active_version_no") or 0),
        "created_by": str(row.get("created_by") or ""),
        "created_at": _safe_value(row.get("created_at")),
        "updated_at": _safe_value(row.get("updated_at")),
    }
    if version is not None:
        item["active_version"] = _normalize_version(version, item)
    return item


def _normalize_version(row: dict[str, Any], template: dict[str, Any] | None = None) -> dict[str, Any]:
    content = _json_load(row.get("content_json"), {})
    schema = _json_load(row.get("field_schema_json"), {})
    return {
        "id": int(row.get("id") or 0),
        "template_id": int(row.get("template_id") or (template or {}).get("id") or 0),
        "template_code": str(row.get("template_code") or (template or {}).get("template_code") or ""),
        "template_type": str(row.get("template_type") or (template or {}).get("template_type") or ""),
        "version_no": int(row.get("version_no") or 0),
        "version_label": str(row.get("version_label") or ""),
        "status": str(row.get("status") or "draft"),
        "content": content if isinstance(content, dict) else {},
        "field_schema": schema if isinstance(schema, (dict, list)) else {},
        "content_hash": str(row.get("content_hash") or ""),
        "created_by": str(row.get("created_by") or ""),
        "published_by": str(row.get("published_by") or ""),
        "published_at": _safe_value(row.get("published_at")),
        "created_at": _safe_value(row.get("created_at")),
    }


def get_active_template_catalog(settings: Settings | None = None) -> dict[str, dict[str, Any]]:
    """Load the active version for every template type, keyed by type."""

    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.*, v.id AS version_id, v.template_id, v.version_no,
                       v.version_label, v.status AS version_status,
                       v.content_json, v.field_schema_json, v.content_hash,
                       v.created_by AS version_created_by, v.published_by,
                       v.published_at, v.created_at AS version_created_at
                FROM annual_audit_template t
                JOIN annual_audit_template_version v
                  ON v.template_id = t.id AND v.version_no = t.active_version_no
                WHERE t.status = 'active' AND v.status = 'active'
                ORDER BY t.template_type, t.template_code
                """
            )
            rows = [dict(row) for row in cursor.fetchall()]
    catalog: dict[str, dict[str, Any]] = {}
    for row in rows:
        template = _normalize_template(row)
        version = _normalize_version(
            {
                "id": row.get("version_id"),
                "template_id": row.get("template_id"),
                "template_code": row.get("template_code"),
                "template_type": row.get("template_type"),
                "version_no": row.get("version_no"),
                "version_label": row.get("version_label"),
                "status": row.get("version_status"),
                "content_json": row.get("content_json"),
                "field_schema_json": row.get("field_schema_json"),
                "content_hash": row.get("content_hash"),
                "created_by": row.get("version_created_by"),
                "published_by": row.get("published_by"),
                "published_at": row.get("published_at"),
                "created_at": row.get("version_created_at"),
            },
            template,
        )
        template["active_version"] = version
        template["version_no"] = version["version_no"]
        template["version_label"] = version["version_label"]
        template["content"] = version["content"]
        template["field_schema"] = version["field_schema"]
        template["content_hash"] = version["content_hash"]
        catalog[template["template_type"]] = template
    return catalog


def list_templates(
    *,
    template_type: str | None = None,
    include_versions: bool = True,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            where = "WHERE 1=1"
            params: list[Any] = []
            if template_type:
                where += " AND t.template_type = %s"
                params.append(template_type)
            cursor.execute(
                f"SELECT t.* FROM annual_audit_template t {where} ORDER BY t.template_type, t.template_code",
                params,
            )
            templates = [_normalize_template(dict(row)) for row in cursor.fetchall()]
            for template in templates:
                cursor.execute(
                    """
                    SELECT v.*, t.template_code, t.template_type
                    FROM annual_audit_template_version v
                    JOIN annual_audit_template t ON t.id = v.template_id
                    WHERE v.template_id = %s
                    ORDER BY v.version_no DESC
                    """,
                    (template["id"],),
                )
                versions = [_normalize_version(dict(row), template) for row in cursor.fetchall()]
                active = next(
                    (version for version in versions if version["version_no"] == template["active_version_no"]),
                    None,
                )
                if active:
                    template["active_version"] = active
                    template["version_no"] = active["version_no"]
                    template["version_label"] = active["version_label"]
                    template["content"] = active["content"]
                if include_versions:
                    template["versions"] = versions
    return {"templates": templates, "template_types": TEMPLATE_TYPE_LABELS}


def create_template(
    *,
    template_code: str,
    template_type: str,
    name: str,
    description: str = "",
    content: dict[str, Any] | None = None,
    field_schema: dict[str, Any] | list[Any] | None = None,
    version_label: str = "v1",
    created_by: str = "system",
    settings: Settings | None = None,
) -> dict[str, Any]:
    if template_type not in TEMPLATE_TYPES:
        raise ValueError(f"template_type 必须为：{', '.join(TEMPLATE_TYPES)}")
    code = template_code.strip()
    if not code:
        raise ValueError("template_code 不能为空")
    body = content if isinstance(content, dict) else {}
    schema = field_schema if isinstance(field_schema, (dict, list)) else {}
    content_hash = hashlib.sha256(_json_dump(body).encode("utf-8")).hexdigest()
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM annual_audit_template WHERE template_code = %s", (code,))
            if cursor.fetchone():
                raise ValueError(f"模板编码已存在：{code}")
            cursor.execute(
                "SELECT template_code FROM annual_audit_template WHERE template_type = %s",
                (template_type,),
            )
            existing_type = cursor.fetchone()
            if existing_type:
                raise ValueError(
                    f"模板类型 {template_type} 已由 {existing_type.get('template_code')} 管理，请通过新增版本维护"
                )
            cursor.execute(
                """
                INSERT INTO annual_audit_template
                  (template_code, template_type, name, description, status, created_by)
                VALUES (%s, %s, %s, %s, 'active', %s)
                """,
                (code, template_type, name.strip(), description.strip(), created_by or "system"),
            )
            template_id = int(cursor.lastrowid)
            cursor.execute(
                """
                INSERT INTO annual_audit_template_version
                  (template_id, version_no, version_label, status, content_json,
                   field_schema_json, content_hash, created_by)
                VALUES (%s, 1, %s, 'draft', %s, %s, %s, %s)
                """,
                (template_id, version_label.strip() or "v1", _json_dump(body), _json_dump(schema), content_hash, created_by or "system"),
            )
        connection.commit()
    return {"template_code": code, "version_no": 1, "status": "draft", "template_id": template_id}


def create_template_version(
    template_code: str,
    *,
    content: dict[str, Any],
    field_schema: dict[str, Any] | list[Any] | None = None,
    version_label: str = "",
    created_by: str = "system",
    settings: Settings | None = None,
) -> dict[str, Any]:
    if not isinstance(content, dict):
        raise ValueError("模板内容必须是 JSON 对象")
    resolved = settings or get_settings()
    content_hash = hashlib.sha256(_json_dump(content).encode("utf-8")).hexdigest()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM annual_audit_template WHERE template_code = %s FOR UPDATE",
                (template_code.strip(),),
            )
            template = dict(cursor.fetchone() or {})
            if not template:
                raise ValueError(f"未找到模板：{template_code}")
            cursor.execute(
                "SELECT COALESCE(MAX(version_no), 0) AS latest FROM annual_audit_template_version WHERE template_id = %s",
                (int(template["id"]),),
            )
            version_no = int((cursor.fetchone() or {}).get("latest") or 0) + 1
            label = version_label.strip() or f"{template_code}-v{version_no}"
            cursor.execute(
                """
                INSERT INTO annual_audit_template_version
                  (template_id, version_no, version_label, status, content_json,
                   field_schema_json, content_hash, created_by)
                VALUES (%s, %s, %s, 'draft', %s, %s, %s, %s)
                """,
                (
                    int(template["id"]), version_no, label, _json_dump(content),
                    _json_dump(field_schema if isinstance(field_schema, (dict, list)) else {}),
                    content_hash, created_by or "system",
                ),
            )
        connection.commit()
    return {
        "template_code": template_code,
        "template_type": str(template.get("template_type") or ""),
        "version_no": version_no,
        "version_label": label,
        "status": "draft",
        "content_hash": content_hash,
    }


def activate_template_version(
    template_code: str,
    version_no: int,
    *,
    published_by: str = "system",
    settings: Settings | None = None,
) -> dict[str, Any]:
    if version_no <= 0:
        raise ValueError("version_no 必须大于 0")
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM annual_audit_template WHERE template_code = %s FOR UPDATE",
                (template_code.strip(),),
            )
            template = dict(cursor.fetchone() or {})
            if not template:
                raise ValueError(f"未找到模板：{template_code}")
            cursor.execute(
                "SELECT * FROM annual_audit_template_version WHERE template_id = %s AND version_no = %s FOR UPDATE",
                (int(template["id"]), version_no),
            )
            target = dict(cursor.fetchone() or {})
            if not target:
                raise ValueError(f"未找到模板版本：{template_code} v{version_no}")
            cursor.execute(
                "UPDATE annual_audit_template_version SET status = 'archived' WHERE template_id = %s AND status = 'active'",
                (int(template["id"]),),
            )
            cursor.execute(
                """
                UPDATE annual_audit_template_version
                SET status = 'active', published_by = %s, published_at = UTC_TIMESTAMP(6)
                WHERE id = %s
                """,
                (published_by or "system", int(target["id"])),
            )
            cursor.execute(
                "UPDATE annual_audit_template SET active_version_no = %s WHERE id = %s",
                (version_no, int(template["id"])),
            )
        connection.commit()
    return {
        "template_code": template_code,
        "template_type": str(template.get("template_type") or ""),
        "version_no": version_no,
        "version_label": str(target.get("version_label") or ""),
        "status": "active",
    }


__all__ = [
    "DEFAULT_TEMPLATE_DEFINITIONS",
    "TEMPLATE_TYPES",
    "TEMPLATE_TYPE_LABELS",
    "activate_template_version",
    "create_template",
    "create_template_version",
    "get_active_template_catalog",
    "list_templates",
    "template_version_ref",
]

# Compatibility facade for code that imported the original module name.  The
# implementations below are now file-backed; JSON content is no longer used
# to render confirmed attachments.
from .template_file_repository import (  # noqa: E402
    SUPPORTED_TEMPLATE_EXTENSIONS,
    TEMPLATE_TYPES,
    TEMPLATE_TYPE_LABELS,
    activate_template_version,
    add_template_file,
    create_template,
    create_template_version,
    delete_template_file,
    get_active_template_catalog,
    list_templates,
    template_version_ref,
)

__all__ += ["SUPPORTED_TEMPLATE_EXTENSIONS", "add_template_file", "delete_template_file"]

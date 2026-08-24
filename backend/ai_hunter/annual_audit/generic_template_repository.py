"""Generic template-version and template-file registry.

The registry is deliberately not tied to the annual-audit document types.
Annual-audit generation uses the optional ``template_usage`` value on a file
to select the relevant active file; other business lines can use the same
version/file registry without adding another table family.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ai_hunter.app.settings import Settings, get_settings

from .storage import mysql_connection


SUPPORTED_TEMPLATE_EXTENSIONS = {
    ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".pdf",
    ".md", ".markdown", ".txt", ".csv",
}

ANNUAL_TEMPLATE_USAGE_LABELS = {
    "annual_report": "年度审计报告",
    "financial_statements": "财务报表",
    "notes": "财务报表附注",
    "audit_workpaper": "审计工作底稿（过程资料）",
    "management_letter": "管理建议书",
    "confirmations": "函证模板（过程资料）",
}

# Business-line/template-type keys are intentionally shared by the generic
# registry.  Only annual_audit is wired to the current AI delivery flow; the
# other keys keep the registry ready for later business lines without making
# users type arbitrary values.
TEMPLATE_TYPE_LABELS = {
    "annual_audit": "年度审计",
    "bookkeeping": "代理记账",
    "tax_filing": "税务业务",
}

ANNUAL_TEMPLATE_BUSINESS_LINES = {
    "annual_audit",
    "年度审计",
    "年度财务报表审计",
    "年度财务报表审计业务",
}

_USAGE_ALIASES = {
    **{value: key for key, value in ANNUAL_TEMPLATE_USAGE_LABELS.items()},
    "审计报告": "annual_report",
    "报表": "financial_statements",
    "附注": "notes",
    "工作底稿": "audit_workpaper",
    "管理建议": "management_letter",
    "函证": "confirmations",
    "询证": "confirmations",
}

_TEMPLATE_TYPE_ALIASES = {
    **{label: key for key, label in TEMPLATE_TYPE_LABELS.items()},
    "annual_audit": "annual_audit",
    "年度财务报表审计": "annual_audit",
    "年度财务报表审计业务": "annual_audit",
    "代理记账业务": "bookkeeping",
    "税务申报": "tax_filing",
}


def normalize_template_usage(value: str) -> str:
    raw = str(value or "").strip()
    return _USAGE_ALIASES.get(raw, raw)


def normalize_template_type(value: str) -> str:
    raw = str(value or "").strip()
    return _TEMPLATE_TYPE_ALIASES.get(raw, raw)


def template_type_label(value: str) -> str:
    normalized = normalize_template_type(value)
    return TEMPLATE_TYPE_LABELS.get(normalized, str(value or ""))


def _template_type_aliases(value: str) -> list[str]:
    normalized = normalize_template_type(value)
    aliases = [normalized]
    aliases.extend(key for key, target in _TEMPLATE_TYPE_ALIASES.items() if target == normalized and key not in aliases)
    return aliases


def is_annual_audit_business_line(value: str) -> bool:
    normalized = normalize_template_type(value).lower()
    return normalized == "annual_audit"


def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _safe_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def template_version_ref(version: dict[str, Any]) -> str:
    label = str(version.get("version_label") or "").strip()
    return label or f"{version.get('template_code') or 'template'}-v{int(version.get('version_no') or 0)}"


def _normalize_file(row: dict[str, Any]) -> dict[str, Any]:
    file_name = str(row.get("file_name") or "")
    return {
        "id": int(row.get("file_id") or row.get("id") or 0),
        "template_version_id": int(row.get("template_version_id") or 0),
        "file_name": file_name,
        "file_ext": str(row.get("file_ext") or Path(file_name).suffix.lower()),
        "content_type": str(row.get("content_type") or "application/octet-stream"),
        "storage_ref": str(row.get("storage_ref") or ""),
        "storage_sha256": str(row.get("storage_sha256") or ""),
        "file_size": int(row.get("file_size") or 0),
        "template_usage": str(row.get("template_usage") or ""),
        "template_usage_label": ANNUAL_TEMPLATE_USAGE_LABELS.get(
            normalize_template_usage(str(row.get("template_usage") or "")),
            str(row.get("template_usage") or ""),
        ),
        "remark": str(row.get("remark") or ""),
        "status": str(row.get("file_status") or row.get("status") or "active"),
        "created_by": str(row.get("file_created_by") or row.get("created_by") or ""),
        "created_at": _safe_value(row.get("file_created_at") or row.get("created_at")),
    }


def _normalize_version(row: dict[str, Any], files: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": int(row.get("version_id") or row.get("id") or 0),
        "template_id": int(row.get("template_id") or 0),
        "template_code": str(row.get("template_code") or ""),
        "template_name": str(row.get("template_name") or row.get("name") or ""),
        "business_line": normalize_template_type(str(row.get("business_line") or "")),
        "description": str(row.get("description") or ""),
        "template_status": str(row.get("template_status") or row.get("status") or "active"),
        "active_version_no": int(row.get("active_version_no") or 0),
        "version_no": int(row.get("version_no") or 0),
        "version_label": str(row.get("version_label") or ""),
        "status": str(row.get("version_status") or row.get("status") or "draft"),
        "content_hash": str(row.get("content_hash") or ""),
        "file_count": int(row.get("file_count") or len(files or [])),
        "files": list(files or []),
        "created_by": str(row.get("version_created_by") or row.get("created_by") or ""),
        "published_by": str(row.get("published_by") or ""),
        "published_at": _safe_value(row.get("published_at")),
        "created_at": _safe_value(row.get("version_created_at") or row.get("created_at")),
    }


def _files_for_version(cursor: Any, version_id: int) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT id AS file_id, template_version_id, file_name, file_ext,
               content_type, storage_ref, storage_sha256, file_size,
               template_usage, remark, status AS file_status,
               created_by AS file_created_by, created_at AS file_created_at
        FROM annual_audit_template_file
        WHERE template_version_id = %s AND status = 'active'
        ORDER BY id
        """,
        (version_id,),
    )
    return [_normalize_file(dict(row)) for row in cursor.fetchall()]


def list_template_versions(*, settings: Settings | None = None) -> dict[str, Any]:
    """Return a flat version list for the generic template-management menu."""

    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.id AS template_id, t.template_code, t.name AS template_name,
                       t.business_line, t.description, t.status AS template_status,
                       t.active_version_no, v.id AS version_id, v.version_no,
                       v.version_label, v.status AS version_status, v.content_hash,
                       v.created_by AS version_created_by, v.published_by,
                       v.published_at, v.created_at AS version_created_at,
                       (SELECT COUNT(*) FROM annual_audit_template_file f
                        WHERE f.template_version_id = v.id AND f.status = 'active') AS file_count
                FROM annual_audit_template t
                JOIN annual_audit_template_version v ON v.template_id = t.id
                WHERE t.status <> 'deleted' AND v.status <> 'deleted'
                ORDER BY v.created_at DESC, v.id DESC
                """
            )
            versions = [_normalize_version(dict(row)) for row in cursor.fetchall()]
    return {
        "versions": versions,
        "business_lines": sorted({item["business_line"] for item in versions if item["business_line"]}),
        "template_types": TEMPLATE_TYPE_LABELS,
        "template_usage_labels": ANNUAL_TEMPLATE_USAGE_LABELS,
    }


def get_template_version(
    template_code: str,
    version_no: int,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.id AS template_id, t.template_code, t.name AS template_name,
                       t.business_line, t.description, t.status AS template_status,
                       t.active_version_no, v.id AS version_id, v.version_no,
                       v.version_label, v.status AS version_status, v.content_hash,
                       v.created_by AS version_created_by, v.published_by,
                       v.published_at, v.created_at AS version_created_at
                FROM annual_audit_template t
                JOIN annual_audit_template_version v ON v.template_id = t.id
                WHERE t.template_code = %s AND v.version_no = %s
                """,
                (template_code.strip(), version_no),
            )
            row = dict(cursor.fetchone() or {})
            if not row:
                raise ValueError(f"未找到模板版本：{template_code} v{version_no}")
            return _normalize_version(row, _files_for_version(cursor, int(row["version_id"])))


def create_template_version_record(
    *,
    template_name: str,
    business_line: str,
    version_label: str = "",
    template_code: str = "",
    description: str = "",
    created_by: str = "system",
    settings: Settings | None = None,
) -> dict[str, Any]:
    name = template_name.strip()
    if not name:
        raise ValueError("模板名称不能为空")
    line = normalize_template_type(business_line)
    if not line:
        raise ValueError("业务线不能为空")
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            code = template_code.strip()
            if code:
                cursor.execute("SELECT * FROM annual_audit_template WHERE template_code = %s FOR UPDATE", (code,))
                template = dict(cursor.fetchone() or {})
                if not template:
                    cursor.execute(
                        """
                        INSERT INTO annual_audit_template
                          (template_code, template_type, name, business_line, description, status, created_by)
                        VALUES (%s, %s, %s, %s, %s, 'active', %s)
                        """,
                        (code, line, name, line, description.strip(), created_by or "system"),
                    )
                    template = {"id": int(cursor.lastrowid), "template_code": code}
            else:
                aliases = _template_type_aliases(line)
                placeholders = ", ".join(["%s"] * len(aliases))
                cursor.execute(
                    f"""
                    SELECT * FROM annual_audit_template
                    WHERE business_line IN ({placeholders}) AND status <> 'deleted'
                    ORDER BY CASE WHEN active_version_no IS NULL THEN 1 ELSE 0 END, id
                    LIMIT 1 FOR UPDATE
                    """,
                    tuple(aliases),
                )
                template = dict(cursor.fetchone() or {})
                if not template:
                    digest = hashlib.sha1(line.encode()).hexdigest()[:16]
                    code = f"template_{digest}"
                    cursor.execute(
                        """
                        INSERT INTO annual_audit_template
                          (template_code, template_type, name, business_line, description, status, created_by)
                        VALUES (%s, %s, %s, %s, %s, 'active', %s)
                        """,
                        (code, line, name, line, description.strip(), created_by or "system"),
                    )
                    template = {"id": int(cursor.lastrowid), "template_code": code}
                else:
                    code = str(template["template_code"])
            cursor.execute(
                "SELECT COALESCE(MAX(version_no), 0) AS latest FROM annual_audit_template_version WHERE template_id = %s",
                (int(template["id"]),),
            )
            version_no = int((cursor.fetchone() or {}).get("latest") or 0) + 1
            label = version_label.strip() or f"v{version_no}"
            content_hash = hashlib.sha256(b"{}").hexdigest()
            cursor.execute(
                """
                INSERT INTO annual_audit_template_version
                  (template_id, version_no, version_label, status, content_json,
                   field_schema_json, content_hash, created_by)
                VALUES (%s, %s, %s, 'draft', %s, %s, %s, %s)
                """,
                (int(template["id"]), version_no, label, _json_dump({}), _json_dump({}), content_hash, created_by or "system"),
            )
        connection.commit()
    return {"template_code": code, "template_name": name, "business_line": line, "version_no": version_no, "version_label": label, "status": "draft", "file_count": 0}


def add_template_file(
    template_code: str,
    version_no: int,
    *,
    file_name: str,
    file_ext: str,
    content_type: str,
    storage_ref: str,
    storage_sha256: str,
    file_size: int,
    template_usage: str = "",
    remark: str = "",
    created_by: str = "system",
    settings: Settings | None = None,
) -> dict[str, Any]:
    normalized_name = Path(file_name or "").name.strip()
    normalized_ext = (file_ext or Path(normalized_name).suffix).lower()
    if not normalized_name or normalized_name in {".", ".."}:
        raise ValueError("模板文件名不能为空")
    if normalized_ext not in SUPPORTED_TEMPLATE_EXTENSIONS:
        raise ValueError(f"不支持的模板文件格式：{normalized_ext or normalized_name}")
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT v.id, v.status, t.business_line FROM annual_audit_template_version v
                JOIN annual_audit_template t ON t.id = v.template_id
                WHERE t.template_code = %s AND v.version_no = %s FOR UPDATE
                """,
                (template_code.strip(), version_no),
            )
            version = dict(cursor.fetchone() or {})
            if not version:
                raise ValueError(f"未找到模板版本：{template_code} v{version_no}")
            if version.get("status") != "draft":
                raise ValueError("已激活或已归档的版本不可修改，请新建版本")
            normalized_usage = normalize_template_usage(template_usage)
            if is_annual_audit_business_line(str(version.get("business_line") or "")) and not normalized_usage:
                raise ValueError("年度审计模板文件必须填写模板用途")
            cursor.execute(
                """
                INSERT INTO annual_audit_template_file
                  (template_version_id, file_name, file_ext, content_type,
                   storage_ref, storage_sha256, file_size, template_usage,
                   remark, status, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)
                """,
                (int(version["id"]), normalized_name, normalized_ext, content_type or "application/octet-stream", storage_ref, storage_sha256, int(file_size), normalized_usage, remark.strip(), created_by or "system"),
            )
            file_id = int(cursor.lastrowid)
            _refresh_version_content_hash(cursor, int(version["id"]))
        connection.commit()
    return {"id": file_id, "template_code": template_code, "version_no": version_no, "file_name": normalized_name, "file_ext": normalized_ext, "content_type": content_type or "application/octet-stream", "storage_ref": storage_ref, "storage_sha256": storage_sha256, "file_size": int(file_size), "template_usage": normalize_template_usage(template_usage), "remark": remark.strip(), "status": "active"}


def delete_template_file(file_id: int, *, deleted_by: str = "system", settings: Settings | None = None) -> dict[str, Any]:
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT f.*, v.status AS version_status, t.template_code, v.version_no
                FROM annual_audit_template_file f
                JOIN annual_audit_template_version v ON v.id = f.template_version_id
                JOIN annual_audit_template t ON t.id = v.template_id
                WHERE f.id = %s FOR UPDATE
                """,
                (file_id,),
            )
            row = dict(cursor.fetchone() or {})
            if not row:
                raise ValueError(f"未找到模板文件：{file_id}")
            if row.get("version_status") != "draft":
                raise ValueError("已激活或已归档版本的文件不可删除，请新建版本")
            cursor.execute("DELETE FROM annual_audit_template_file WHERE id = %s", (file_id,))
            _refresh_version_content_hash(cursor, int(row["template_version_id"]))
        connection.commit()
    return {"id": file_id, "template_code": row.get("template_code"), "version_no": int(row.get("version_no") or 0), "storage_ref": row.get("storage_ref"), "status": "deleted", "deleted_by": deleted_by}


def delete_template_version(template_code: str, version_no: int, *, deleted_by: str = "system", settings: Settings | None = None) -> dict[str, Any]:
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.id AS template_id, t.active_version_no, v.id AS version_id,
                       v.version_label, v.status AS version_status
                FROM annual_audit_template t
                JOIN annual_audit_template_version v ON v.template_id = t.id
                WHERE t.template_code = %s AND v.version_no = %s FOR UPDATE
                """,
                (template_code.strip(), version_no),
            )
            version = dict(cursor.fetchone() or {})
            if not version:
                raise ValueError(f"未找到模板版本：{template_code} v{version_no}")
            cursor.execute("SELECT storage_ref FROM annual_audit_template_file WHERE template_version_id = %s", (int(version["version_id"]),))
            refs = [str(row.get("storage_ref") or "") for row in cursor.fetchall() if row.get("storage_ref")]
            cursor.execute("DELETE FROM annual_audit_template_file WHERE template_version_id = %s", (int(version["version_id"]),))
            cursor.execute("DELETE FROM annual_audit_template_version WHERE id = %s", (int(version["version_id"]),))
            if int(version.get("active_version_no") or 0) == version_no:
                cursor.execute("UPDATE annual_audit_template SET active_version_no = NULL WHERE id = %s", (int(version["template_id"]),))
            cursor.execute("SELECT COUNT(*) AS remaining FROM annual_audit_template_version WHERE template_id = %s", (int(version["template_id"]),))
            if int((cursor.fetchone() or {}).get("remaining") or 0) == 0:
                cursor.execute("DELETE FROM annual_audit_template WHERE id = %s", (int(version["template_id"]),))
        connection.commit()
    return {"template_code": template_code, "version_no": version_no, "version_label": version.get("version_label"), "storage_refs": refs, "status": "deleted", "deleted_by": deleted_by}


def activate_template_version(template_code: str, version_no: int, *, published_by: str = "system", settings: Settings | None = None) -> dict[str, Any]:
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM annual_audit_template WHERE template_code = %s FOR UPDATE", (template_code.strip(),))
            template = dict(cursor.fetchone() or {})
            if not template:
                raise ValueError(f"未找到模板：{template_code}")
            cursor.execute("SELECT * FROM annual_audit_template_version WHERE template_id = %s AND version_no = %s FOR UPDATE", (int(template["id"]), version_no))
            target = dict(cursor.fetchone() or {})
            if not target:
                raise ValueError(f"未找到模板版本：{template_code} v{version_no}")
            cursor.execute("SELECT COUNT(*) AS file_count FROM annual_audit_template_file WHERE template_version_id = %s AND status = 'active'", (int(target["id"]),))
            file_count = int((cursor.fetchone() or {}).get("file_count") or 0)
            if not file_count:
                raise ValueError("版本至少上传一个文件后才能激活")
            aliases = _template_type_aliases(str(template.get("business_line") or ""))
            placeholders = ", ".join(["%s"] * len(aliases))
            cursor.execute(
                f"SELECT id FROM annual_audit_template WHERE business_line IN ({placeholders}) AND status <> 'deleted' FOR UPDATE",
                tuple(aliases),
            )
            type_template_ids = [int(row["id"]) for row in cursor.fetchall()]
            id_placeholders = ", ".join(["%s"] * len(type_template_ids))
            cursor.execute(
                f"UPDATE annual_audit_template_version SET status = 'archived' WHERE template_id IN ({id_placeholders}) AND status = 'active'",
                tuple(type_template_ids),
            )
            cursor.execute(
                f"UPDATE annual_audit_template SET active_version_no = NULL WHERE id IN ({id_placeholders})",
                tuple(type_template_ids),
            )
            cursor.execute("UPDATE annual_audit_template_version SET status = 'active', published_by = %s, published_at = UTC_TIMESTAMP(6) WHERE id = %s", (published_by or "system", int(target["id"])))
            cursor.execute("UPDATE annual_audit_template SET active_version_no = %s WHERE id = %s", (version_no, int(template["id"])))
        connection.commit()
    return {"template_code": template_code, "version_no": version_no, "version_label": target.get("version_label"), "status": "active", "file_count": file_count}


def _refresh_version_content_hash(cursor: Any, version_id: int) -> str:
    """Make the version hash describe the uploaded file set, not an empty JSON body."""

    cursor.execute(
        """
        SELECT storage_sha256
        FROM annual_audit_template_file
        WHERE template_version_id = %s AND status = 'active'
        ORDER BY id
        """,
        (version_id,),
    )
    hashes = [str(row.get("storage_sha256") or "") for row in cursor.fetchall()]
    content_hash = hashlib.sha256("\n".join(hashes).encode("utf-8")).hexdigest()
    cursor.execute(
        "UPDATE annual_audit_template_version SET content_hash = %s WHERE id = %s",
        (content_hash, version_id),
    )
    return content_hash


def get_active_template_catalog(
    settings: Settings | None = None,
    *,
    business_line: str | None = "年度审计",
) -> dict[str, dict[str, Any]]:
    """Map active generic template files to annual-audit usages.

    The generic registry is shared by business lines.  Annual-audit
    generation must not accidentally consume a similarly named file from an
    unrelated business line, so the default is intentionally scoped to the
    annual-audit business-line aliases.
    """

    catalog: dict[str, dict[str, Any]] = {}
    versions = list_template_versions(settings=settings).get("versions") or []
    for summary in versions:
        actual_business_line = str(summary.get("business_line") or "")
        if business_line:
            if is_annual_audit_business_line(business_line):
                if not is_annual_audit_business_line(actual_business_line):
                    continue
            elif normalize_template_type(actual_business_line) != normalize_template_type(business_line):
                continue
        if summary.get("status") != "active" or summary.get("active_version_no") != summary.get("version_no"):
            continue
        detail = get_template_version(summary["template_code"], summary["version_no"], settings=settings)
        files_by_usage: dict[str, list[dict[str, Any]]] = {}
        for file in detail.get("files") or []:
            usage = normalize_template_usage(str(file.get("template_usage") or ""))
            if usage not in ANNUAL_TEMPLATE_USAGE_LABELS:
                continue
            files_by_usage.setdefault(usage, []).append(file)
        for usage, files in files_by_usage.items():
            if usage in catalog:
                continue
            catalog[usage] = {
                **detail,
                "template_type": usage,
                "template_type_label": ANNUAL_TEMPLATE_USAGE_LABELS[usage],
                "version_label": detail.get("version_label") or template_version_ref(detail),
                "version_no": detail.get("version_no"),
                "files": files,
                "content_hash": detail.get("content_hash") or "",
            }
    return catalog


__all__ = [
    "ANNUAL_TEMPLATE_USAGE_LABELS",
    "ANNUAL_TEMPLATE_BUSINESS_LINES",
    "TEMPLATE_TYPE_LABELS",
    "SUPPORTED_TEMPLATE_EXTENSIONS",
    "activate_template_version",
    "add_template_file",
    "create_template_version_record",
    "delete_template_file",
    "delete_template_version",
    "get_active_template_catalog",
    "get_template_version",
    "is_annual_audit_business_line",
    "list_template_versions",
    "normalize_template_usage",
    "normalize_template_type",
    "template_type_label",
    "template_version_ref",
]

"""Governed knowledge and rule-version management for annual audits.

This repository deliberately does not reuse case-material vector search for
laws or methodology. A customer file, historical workpaper or AI answer is
not authoritative unless it has been classified, source-hashed, reviewed and
published through this workflow.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from ai_hunter.app.settings import Settings, get_settings

from .storage import postgres_connection


AUTHORITY_TYPES = {
    "law",
    "accounting_standard",
    "auditing_standard",
    "regulatory_guidance",
    "firm_methodology",
    "industry_guidance",
    "case_reference",
}
RULE_TYPES = {
    "mandatory_requirement",
    "firm_methodology",
    "data_check",
    "risk_signal",
}


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _loads(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _text(value: Any) -> str:
    return str(value or "").strip()


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("日期必须为 YYYY-MM-DD") from exc


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_hash(value: Any) -> bool:
    text = _text(value).lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _effective(start: Any, end: Any, at: date) -> bool:
    start_date = _date(start)
    end_date = _date(end)
    return (start_date is None or start_date <= at) and (
        end_date is None or at <= end_date
    )


def split_knowledge_chunks(
    content_text: str,
    *,
    max_chars: int = 1200,
) -> list[dict[str, Any]]:
    """Split by non-empty paragraphs while preserving a stable ordinal locator."""

    text = _text(content_text)
    if not text:
        return []
    max_chars = max(200, min(max_chars, 8000))
    paragraphs = [part.strip() for part in text.replace("\r\n", "\n").split("\n") if part.strip()]
    chunks: list[dict[str, Any]] = []
    current: list[str] = []
    current_size = 0
    for paragraph in paragraphs or [text]:
        if current and current_size + len(paragraph) + 1 > max_chars:
            body = "\n".join(current)
            chunks.append(
                {
                    "locator": f"段落 {len(chunks) + 1}",
                    "heading": current[0][:120] if current[0].startswith(("第", "一、", "（")) else "",
                    "content_text": body,
                }
            )
            current = []
            current_size = 0
        if len(paragraph) > max_chars:
            for offset in range(0, len(paragraph), max_chars):
                fragment = paragraph[offset : offset + max_chars]
                if current:
                    current.append(fragment)
                    current_size += len(fragment)
                else:
                    chunks.append(
                        {
                            "locator": f"段落 {len(chunks) + 1}",
                            "heading": "",
                            "content_text": fragment,
                        }
                    )
            continue
        current.append(paragraph)
        current_size += len(paragraph) + 1
    if current:
        body = "\n".join(current)
        chunks.append(
            {
                "locator": f"段落 {len(chunks) + 1}",
                "heading": current[0][:120] if current[0].startswith(("第", "一、", "（")) else "",
                "content_text": body,
            }
        )
    return chunks


def create_knowledge_version(
    payload: dict[str, Any],
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Register a sourced document and a new unapproved content version."""

    resolved = settings or get_settings()
    document_code = _text(payload.get("document_code"))
    title = _text(payload.get("title"))
    authority_type = _text(payload.get("authority_type"))
    source_issuer = _text(payload.get("source_issuer"))
    source_url = _text(payload.get("source_url"))
    source_hash = _text(payload.get("source_hash")).lower()
    content_text = _text(payload.get("content_text"))
    if not document_code or not title or not source_issuer or not content_text:
        raise ValueError("document_code、title、source_issuer 和 content_text 不能为空")
    if authority_type not in AUTHORITY_TYPES:
        raise ValueError(f"authority_type 必须为：{', '.join(sorted(AUTHORITY_TYPES))}")
    if not source_url or not _valid_hash(source_hash):
        raise ValueError("知识资料必须保留 source_url 和原始来源 SHA-256")
    scope = payload.get("scope") or {}
    if not isinstance(scope, (dict, list)):
        raise ValueError("scope 必须为对象或数组")
    chunks = payload.get("chunks")
    if chunks is None:
        chunks = split_knowledge_chunks(content_text)
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("知识版本至少需要一个可检索的条款/段落")
    normalized_chunks: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict) or not _text(chunk.get("content_text")):
            raise ValueError(f"第 {index} 个知识块缺少 content_text")
        normalized_chunks.append(
            {
                "locator": _text(chunk.get("locator")) or f"段落 {index}",
                "heading": _text(chunk.get("heading")),
                "content_text": _text(chunk.get("content_text")),
                "metadata": chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {},
            }
        )
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM annual_knowledge_document WHERE document_code = %s FOR UPDATE",
                (document_code,),
            )
            document = dict(cursor.fetchone() or {})
            if not document:
                cursor.execute(
                    """
                    INSERT INTO annual_knowledge_document (
                      document_code, title, authority_type, source_issuer, source_url,
                      source_hash, scope_json, status, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'draft', %s)
                    RETURNING id
                    """,
                    (
                        document_code,
                        title,
                        authority_type,
                        source_issuer,
                        source_url,
                        source_hash,
                        _dump(scope),
                        _text(actor_user_id) or "system",
                    ),
                )
                document_id = _integer((cursor.fetchone() or {}).get("id"))
            else:
                document_id = _integer(document.get("id"))
                if str(document.get("authority_type") or "") != authority_type:
                    raise ValueError("同一 document_code 不能改变知识资料层级")
                cursor.execute(
                    """
                    UPDATE annual_knowledge_document
                    SET title = %s, source_issuer = %s, source_url = %s,
                        source_hash = %s, scope_json = %s
                    WHERE id = %s
                    """,
                    (title, source_issuer, source_url, source_hash, _dump(scope), document_id),
                )
            cursor.execute(
                """
                SELECT COALESCE(MAX(version_no), 0) AS latest_version
                FROM annual_knowledge_version
                WHERE document_id = %s
                """,
                (document_id,),
            )
            version_no = _integer(cursor.fetchone().get("latest_version")) + 1
            content_hash = _hash(content_text)
            cursor.execute(
                """
                INSERT INTO annual_knowledge_version (
                  document_id, version_no, source_url, source_hash,
                  publication_date, effective_from, effective_to,
                  supersedes_version_id, content_text, content_hash, review_status,
                  change_summary, created_by
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s,
                  (SELECT id FROM (
                    SELECT id FROM annual_knowledge_version
                    WHERE document_id = %s ORDER BY version_no DESC LIMIT 1
                  ) AS previous_version),
                  %s, %s, 'draft', %s, %s
                )
                RETURNING id
                """,
                (
                    document_id,
                    version_no,
                    source_url,
                    source_hash,
                    _date(payload.get("publication_date")),
                    _date(payload.get("effective_from")),
                    _date(payload.get("effective_to")),
                    document_id,
                    content_text,
                    content_hash,
                    _text(payload.get("change_summary")) or None,
                    _text(actor_user_id) or "system",
                ),
            )
            knowledge_version_id = _integer((cursor.fetchone() or {}).get("id"))
            for index, chunk in enumerate(normalized_chunks, start=1):
                cursor.execute(
                    """
                    INSERT INTO annual_knowledge_chunk (
                      knowledge_version_id, chunk_no, locator, heading, content_text,
                      content_hash, metadata_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        knowledge_version_id,
                        index,
                        chunk["locator"],
                        chunk["heading"] or None,
                        chunk["content_text"],
                        _hash(chunk["content_text"]),
                        _dump(chunk["metadata"]),
                    ),
                )
            cursor.execute(
                """
                INSERT INTO ata_audit_log (
                  actor_user_id, action, target_type, target_id, details_json
                ) VALUES (%s, 'create_knowledge_version', 'annual_knowledge_version', %s, %s)
                """,
                (
                    _text(actor_user_id) or "system",
                    str(knowledge_version_id),
                    _dump(
                        {
                            "document_code": document_code,
                            "version_no": version_no,
                            "authority_type": authority_type,
                            "source_hash": source_hash,
                        }
                    ),
                ),
            )
        connection.commit()
    return {
        "document_code": document_code,
        "knowledge_version_id": knowledge_version_id,
        "version_no": version_no,
        "review_status": "draft",
        "chunk_count": len(normalized_chunks),
    }


def review_knowledge_version(
    knowledge_version_id: int,
    payload: dict[str, Any],
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Move a knowledge version through reviewer and approver controls."""

    resolved = settings or get_settings()
    action = _text(payload.get("action"))
    if action not in {"review", "approve", "reject"}:
        raise ValueError("action 必须为 review、approve 或 reject")
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM annual_knowledge_version WHERE id = %s FOR UPDATE",
                (knowledge_version_id,),
            )
            version = dict(cursor.fetchone() or {})
            if not version:
                raise ValueError("知识版本不存在")
            current = str(version.get("review_status") or "draft")
            if action == "review":
                if current not in {"draft", "rejected"}:
                    raise ValueError("只有草稿或已退回版本可以送审")
                cursor.execute(
                    """
                    UPDATE annual_knowledge_version
                    SET review_status = 'reviewed', reviewed_by = %s, reviewed_at = CURRENT_TIMESTAMP(6)
                    WHERE id = %s
                    """,
                    (_text(actor_user_id) or "system", knowledge_version_id),
                )
                status = "reviewed"
            elif action == "approve":
                if current != "reviewed":
                    raise ValueError("知识版本必须先经复核才能批准")
                cursor.execute(
                    """
                    UPDATE annual_knowledge_version
                    SET review_status = 'approved', approved_by = %s, approved_at = CURRENT_TIMESTAMP(6)
                    WHERE id = %s
                    """,
                    (_text(actor_user_id) or "system", knowledge_version_id),
                )
                status = "approved"
            else:
                cursor.execute(
                    """
                    UPDATE annual_knowledge_version
                    SET review_status = 'rejected', change_summary = %s
                    WHERE id = %s
                    """,
                    (_text(payload.get("note")) or "已退回修改", knowledge_version_id),
                )
                status = "rejected"
        connection.commit()
    return {"knowledge_version_id": knowledge_version_id, "review_status": status}


def create_knowledge_release(
    payload: dict[str, Any],
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Create a draft, immutable candidate release from approved knowledge versions."""

    resolved = settings or get_settings()
    release_code = _text(payload.get("release_code"))
    release_version = _text(payload.get("release_version"))
    version_ids = sorted({_integer(item) for item in payload.get("knowledge_version_ids") or [] if _integer(item)})
    if not release_code or not release_version or not version_ids:
        raise ValueError("release_code、release_version 和 knowledge_version_ids 不能为空")
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            placeholders = ", ".join(["%s"] * len(version_ids))
            cursor.execute(
                f"""
                SELECT id, review_status
                FROM annual_knowledge_version
                WHERE id IN ({placeholders})
                """,
                tuple(version_ids),
            )
            versions = {int(row["id"]): str(row["review_status"]) for row in cursor.fetchall()}
            missing = [item for item in version_ids if item not in versions]
            unapproved = [item for item in version_ids if versions.get(item) != "approved"]
            if missing or unapproved:
                raise ValueError(
                    f"知识发布只能包含已批准版本；缺失={missing}，未批准={unapproved}"
                )
            cursor.execute(
                """
                INSERT INTO annual_knowledge_release (
                  release_code, release_version, status, effective_from, effective_to,
                  approval_note, created_by
                ) VALUES (%s, %s, 'draft', %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    release_code,
                    release_version,
                    _date(payload.get("effective_from")),
                    _date(payload.get("effective_to")),
                    _text(payload.get("approval_note")) or None,
                    _text(actor_user_id) or "system",
                ),
            )
            release_id = _integer((cursor.fetchone() or {}).get("id"))
            for version_id in version_ids:
                cursor.execute(
                    """
                    INSERT INTO annual_knowledge_release_item (release_id, knowledge_version_id)
                    VALUES (%s, %s)
                    """,
                    (release_id, version_id),
                )
        connection.commit()
    return {
        "release_id": release_id,
        "release_code": release_code,
        "release_version": release_version,
        "status": "draft",
        "knowledge_version_ids": version_ids,
    }


def publish_knowledge_release(
    release_id: int,
    payload: dict[str, Any],
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Publish only a release whose included versions are still approved."""

    resolved = settings or get_settings()
    at_date = _date(payload.get("effective_from")) or date.today()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM annual_knowledge_release WHERE id = %s FOR UPDATE",
                (release_id,),
            )
            release = dict(cursor.fetchone() or {})
            if not release:
                raise ValueError("知识发布不存在")
            if str(release.get("status") or "") != "draft":
                raise ValueError("只有草稿知识发布可以发布")
            cursor.execute(
                """
                SELECT v.id, v.review_status, v.effective_from, v.effective_to
                FROM annual_knowledge_release_item item
                JOIN annual_knowledge_version v ON v.id = item.knowledge_version_id
                WHERE item.release_id = %s
                """,
                (release_id,),
            )
            versions = [dict(row) for row in cursor.fetchall()]
            if not versions:
                raise ValueError("知识发布不包含知识版本")
            invalid = [
                _integer(item.get("id"))
                for item in versions
                if str(item.get("review_status") or "") != "approved"
                or not _effective(item.get("effective_from"), item.get("effective_to"), at_date)
            ]
            if invalid:
                raise ValueError(f"知识发布含有未批准或无效版本：{invalid}")
            cursor.execute(
                """
                UPDATE annual_knowledge_release
                SET status = 'published', effective_from = %s, effective_to = %s,
                    approval_note = %s, approved_by = %s, approved_at = CURRENT_TIMESTAMP(6)
                WHERE id = %s
                """,
                (
                    _date(payload.get("effective_from")) or release.get("effective_from"),
                    _date(payload.get("effective_to")) or release.get("effective_to"),
                    _text(payload.get("approval_note")) or release.get("approval_note"),
                    _text(actor_user_id) or "system",
                    release_id,
                ),
            )
        connection.commit()
    return {"release_id": release_id, "status": "published"}


def create_ruleset(
    payload: dict[str, Any],
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Create a draft rule-set. Rules must be reviewed separately before release."""

    resolved = settings or get_settings()
    ruleset_code = _text(payload.get("ruleset_code"))
    version = _text(payload.get("version"))
    name = _text(payload.get("name"))
    scope = payload.get("scope") or {}
    if not ruleset_code or not version or not name:
        raise ValueError("ruleset_code、version 和 name 不能为空")
    if not isinstance(scope, (dict, list)):
        raise ValueError("scope 必须为对象或数组")
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO annual_audit_ruleset (
                  ruleset_code, version, name, scope_json, status,
                  effective_from, effective_to, created_by
                ) VALUES (%s, %s, %s, %s, 'draft', %s, %s, %s)
                RETURNING id
                """,
                (
                    ruleset_code,
                    version,
                    name,
                    _dump(scope),
                    _date(payload.get("effective_from")),
                    _date(payload.get("effective_to")),
                    _text(actor_user_id) or "system",
                ),
            )
            ruleset_id = _integer((cursor.fetchone() or {}).get("id"))
        connection.commit()
    return {
        "ruleset_id": ruleset_id,
        "ruleset_code": ruleset_code,
        "version": version,
        "status": "draft",
    }


def upsert_rule(
    ruleset_id: int,
    payload: dict[str, Any],
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Add or revise a rule with its authority, scope and evidence requirements."""

    resolved = settings or get_settings()
    rule_code = _text(payload.get("rule_code"))
    rule_type = _text(payload.get("rule_type"))
    name = _text(payload.get("name"))
    authority_locator = _text(payload.get("authority_locator"))
    knowledge_version_id = _integer(payload.get("knowledge_version_id"))
    if not rule_code or not name or rule_type not in RULE_TYPES:
        raise ValueError("rule_code、name 和有效的 rule_type 不能为空")
    if rule_type == "mandatory_requirement" and (knowledge_version_id <= 0 or not authority_locator):
        raise ValueError("强制性要求规则必须绑定已批准知识版本及条款定位")
    json_fields = {
        "applicability": payload.get("applicability") or {},
        "preconditions": payload.get("preconditions") or {},
        "evidence_requirements": payload.get("evidence_requirements") or {},
        "logic": payload.get("logic") or {},
        "exception_handling": payload.get("exception_handling") or {},
    }
    if any(not isinstance(value, (dict, list)) for value in json_fields.values()):
        raise ValueError("规则配置字段必须为对象或数组")
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM annual_audit_ruleset WHERE id = %s FOR UPDATE",
                (ruleset_id,),
            )
            ruleset = cursor.fetchone()
            if not ruleset:
                raise ValueError("规则集不存在")
            if str(ruleset.get("status") or "") != "draft":
                raise ValueError("已发布规则集不可直接修改，请创建新版本")
            if knowledge_version_id:
                cursor.execute(
                    "SELECT review_status FROM annual_knowledge_version WHERE id = %s",
                    (knowledge_version_id,),
                )
                knowledge = cursor.fetchone()
                if not knowledge or str(knowledge.get("review_status") or "") != "approved":
                    raise ValueError("规则引用的知识版本必须已批准")
            cursor.execute(
                """
                INSERT INTO annual_audit_rule (
                  ruleset_id, rule_code, rule_type, name, authority_locator,
                  knowledge_version_id, applicability_json, preconditions_json,
                  evidence_requirements_json, logic_json, exception_handling_json, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft')
                ON CONFLICT (ruleset_id, rule_code) DO UPDATE SET
                  rule_type = EXCLUDED.rule_type, name = EXCLUDED.name,
                  authority_locator = EXCLUDED.authority_locator,
                  knowledge_version_id = EXCLUDED.knowledge_version_id,
                  applicability_json = EXCLUDED.applicability_json,
                  preconditions_json = EXCLUDED.preconditions_json,
                  evidence_requirements_json = EXCLUDED.evidence_requirements_json,
                  logic_json = EXCLUDED.logic_json,
                  exception_handling_json = EXCLUDED.exception_handling_json,
                  status = 'draft'
                RETURNING id
                """,
                (
                    ruleset_id,
                    rule_code,
                    rule_type,
                    name,
                    authority_locator or None,
                    knowledge_version_id or None,
                    _dump(json_fields["applicability"]),
                    _dump(json_fields["preconditions"]),
                    _dump(json_fields["evidence_requirements"]),
                    _dump(json_fields["logic"]),
                    _dump(json_fields["exception_handling"]),
                ),
            )
            rule_id = _integer((cursor.fetchone() or {}).get("id"))
        connection.commit()
    return {"ruleset_id": ruleset_id, "rule_id": rule_id, "rule_code": rule_code, "status": "draft"}


def review_rule(
    rule_id: int,
    payload: dict[str, Any],
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Approve or return a rule before its ruleset can be published."""

    resolved = settings or get_settings()
    action = _text(payload.get("action"))
    if action not in {"approve", "reject"}:
        raise ValueError("action 必须为 approve 或 reject")
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM annual_audit_rule WHERE id = %s FOR UPDATE", (rule_id,))
            rule = dict(cursor.fetchone() or {})
            if not rule:
                raise ValueError("规则不存在")
            cursor.execute(
                "SELECT status FROM annual_audit_ruleset WHERE id = %s",
                (_integer(rule.get("ruleset_id")),),
            )
            ruleset = cursor.fetchone()
            if not ruleset or str(ruleset.get("status") or "") != "draft":
                raise ValueError("只有草稿规则集的规则可以复核")
            status = "approved" if action == "approve" else "rejected"
            cursor.execute(
                "UPDATE annual_audit_rule SET status = %s WHERE id = %s",
                (status, rule_id),
            )
        connection.commit()
    return {"rule_id": rule_id, "status": status}


def publish_ruleset(
    ruleset_id: int,
    payload: dict[str, Any],
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Publish a complete reviewed rule-set and freeze its effective window."""

    resolved = settings or get_settings()
    effective_from = _date(payload.get("effective_from")) or date.today()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM annual_audit_ruleset WHERE id = %s FOR UPDATE",
                (ruleset_id,),
            )
            ruleset = dict(cursor.fetchone() or {})
            if not ruleset:
                raise ValueError("规则集不存在")
            if str(ruleset.get("status") or "") != "draft":
                raise ValueError("只有草稿规则集可以发布")
            cursor.execute(
                """
                SELECT id, status
                FROM annual_audit_rule
                WHERE ruleset_id = %s
                """,
                (ruleset_id,),
            )
            rules = [dict(row) for row in cursor.fetchall()]
            incomplete = [
                _integer(rule.get("id"))
                for rule in rules
                if str(rule.get("status") or "") != "approved"
            ]
            if not rules or incomplete:
                raise ValueError(f"规则集必须至少包含一条已批准规则；未批准={incomplete}")
            cursor.execute(
                """
                UPDATE annual_audit_ruleset
                SET status = 'published', effective_from = %s, effective_to = %s,
                    approved_by = %s, approved_at = CURRENT_TIMESTAMP(6)
                WHERE id = %s
                """,
                (
                    effective_from,
                    _date(payload.get("effective_to")) or ruleset.get("effective_to"),
                    _text(actor_user_id) or "system",
                    ruleset_id,
                ),
            )
        connection.commit()
    return {"ruleset_id": ruleset_id, "status": "published"}


def search_published_knowledge(
    query: str,
    *,
    as_of_date: date | str | None = None,
    authority_types: list[str] | None = None,
    limit: int = 12,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Search only published releases containing approved, applicable versions."""

    resolved = settings or get_settings()
    term = _text(query)
    if not term:
        raise ValueError("query 不能为空")
    date_filter = _date(as_of_date) or date.today()
    valid_types = [
        item for item in (authority_types or []) if item in AUTHORITY_TYPES
    ]
    limit = max(1, min(int(limit), 50))
    where = [
        "r.status = 'published'",
        "v.review_status = 'approved'",
        "(r.effective_from IS NULL OR r.effective_from <= %s)",
        "(r.effective_to IS NULL OR r.effective_to >= %s)",
        "(v.effective_from IS NULL OR v.effective_from <= %s)",
        "(v.effective_to IS NULL OR v.effective_to >= %s)",
        "(d.title LIKE %s OR c.heading LIKE %s OR c.content_text LIKE %s)",
    ]
    params: list[Any] = [date_filter, date_filter, date_filter, date_filter]
    pattern = f"%{term}%"
    params.extend([pattern, pattern, pattern])
    if valid_types:
        placeholders = ", ".join(["%s"] * len(valid_types))
        where.append(f"d.authority_type IN ({placeholders})")
        params.extend(valid_types)
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT DISTINCT
                  d.document_code, d.title, d.authority_type, d.source_issuer, v.source_url,
                  v.source_hash, v.id AS knowledge_version_id, v.version_no,
                  v.publication_date, v.effective_from, v.effective_to,
                  c.id AS chunk_id, c.locator, c.heading, c.content_text,
                  r.release_code, r.release_version
                FROM annual_knowledge_release r
                JOIN annual_knowledge_release_item ri ON ri.release_id = r.id
                JOIN annual_knowledge_version v ON v.id = ri.knowledge_version_id
                JOIN annual_knowledge_document d ON d.id = v.document_id
                JOIN annual_knowledge_chunk c ON c.knowledge_version_id = v.id
                WHERE {' AND '.join(where)}
                ORDER BY CASE d.authority_type
                  WHEN 'law' THEN 1
                  WHEN 'accounting_standard' THEN 2
                  WHEN 'auditing_standard' THEN 3
                  WHEN 'regulatory_guidance' THEN 4
                  WHEN 'firm_methodology' THEN 5
                  WHEN 'industry_guidance' THEN 6
                  WHEN 'case_reference' THEN 7
                  ELSE 8
                END,
                  v.effective_from DESC, c.id
                LIMIT %s
                """,
                tuple([*params, limit]),
            )
            rows = [dict(row) for row in cursor.fetchall()]
    return {
        "query": term,
        "as_of_date": date_filter.isoformat(),
        "results": [
            {
                "document_code": str(row.get("document_code") or ""),
                "title": str(row.get("title") or ""),
                "authority_type": str(row.get("authority_type") or ""),
                "source_issuer": str(row.get("source_issuer") or ""),
                "source_url": str(row.get("source_url") or ""),
                "source_hash": str(row.get("source_hash") or ""),
                "knowledge_version_id": _integer(row.get("knowledge_version_id")),
                "version_no": _integer(row.get("version_no")),
                "effective_from": (
                    row["effective_from"].isoformat() if row.get("effective_from") else None
                ),
                "effective_to": (
                    row["effective_to"].isoformat() if row.get("effective_to") else None
                ),
                "locator": str(row.get("locator") or ""),
                "heading": str(row.get("heading") or ""),
                "content_text": str(row.get("content_text") or ""),
                "release_code": str(row.get("release_code") or ""),
                "release_version": str(row.get("release_version") or ""),
            }
            for row in rows
        ],
    }


def list_policy_catalog(
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """List approved releases and rule-sets that may be frozen to a project."""

    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, release_code, release_version, status, effective_from, effective_to
                FROM annual_knowledge_release
                ORDER BY approved_at DESC, id DESC
                """
            )
            releases = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT id, ruleset_code, version, name, status, effective_from, effective_to
                FROM annual_audit_ruleset
                ORDER BY approved_at DESC, id DESC
                """
            )
            rulesets = [dict(row) for row in cursor.fetchall()]
    return {
        "knowledge_releases": [
            {
                **row,
                "id": _integer(row.get("id")),
                "effective_from": (
                    row["effective_from"].isoformat() if row.get("effective_from") else None
                ),
                "effective_to": (
                    row["effective_to"].isoformat() if row.get("effective_to") else None
                ),
            }
            for row in releases
        ],
        "rulesets": [
            {
                **row,
                "id": _integer(row.get("id")),
                "effective_from": (
                    row["effective_from"].isoformat() if row.get("effective_from") else None
                ),
                "effective_to": (
                    row["effective_to"].isoformat() if row.get("effective_to") else None
                ),
            }
            for row in rulesets
        ],
    }


__all__ = [
    "AUTHORITY_TYPES",
    "RULE_TYPES",
    "create_knowledge_release",
    "create_knowledge_version",
    "create_ruleset",
    "list_policy_catalog",
    "publish_knowledge_release",
    "publish_ruleset",
    "review_knowledge_version",
    "review_rule",
    "search_published_knowledge",
    "split_knowledge_chunks",
    "upsert_rule",
]

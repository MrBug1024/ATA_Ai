"""Extract entities, relations, and claims from stored chunks."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError
import yaml

from ...services.kg_service import get_kg_service
from ...services.graph_identity import (
    DEFAULT_GRAPH_STATUS,
    build_entity_key,
    build_relation_key,
    normalize_entity_name,
)
from ...settings import get_settings
from ..context_loader import resolve_aggregated_text
from ..heavy_state import get_heavy_payload
from ..llm import build_agent_llm
from ..prompting import load_prompt
from ..schemas import ExtractionBundleModel
from ..state import AuditGraphState


MAX_EXTRACTION_CHUNKS = 24
MAX_CHUNK_TEXT_CHARS = 1200
PROMPT_VERSION = "annual-audit-kg-extraction-v1"


def extract_entities_relations(state: AuditGraphState) -> AuditGraphState:
    """Extract graph entities, relations, and claims from chunked case material."""
    case_id = state.get("current_case_id", 0)
    chunk_ids = state.get("chunk_ids", [])
    if not chunk_ids:
        return {}

    available_chunk_ids = {str(chunk_id) for chunk_id in chunk_ids}
    source_chunks, source_file_ids = _load_source_chunks(state)
    extraction_input = _build_extraction_input(state, source_chunks)
    if not extraction_input.strip():
        return {"kg_entities": [], "kg_relations": [], "kg_claims": []}

    settings = get_settings()
    llm_config = settings.get_llm_config("agent")
    run_id = _create_extraction_run(case_id=case_id, source_file_ids=source_file_ids, chunk_count=len(chunk_ids))
    if llm_config["api_key"]:
        prompt = load_prompt("annual_audit_extract_entities_relations.txt")
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(
                content=(
                    f"年审项目编号: {case_id}\n"
                    f"被审计单位: {state.get('current_entity_name', '') or '未知'}\n"
                    f"可用 chunk_id 列表: {', '.join(chunk_ids)}\n\n"
                    f"材料片段:\n{extraction_input}"
                )
            ),
        ]
        try:
            llm = build_agent_llm()
            structured_llm = llm.with_structured_output(ExtractionBundleModel)
            result = structured_llm.invoke(messages)
            normalized = _normalize_bundle(
                result.model_dump(),
                available_chunk_ids=available_chunk_ids,
            )
            if not _has_traceable_evidence(normalized):
                raise ValueError("KG extraction output is missing valid evidence_chunk_ids")
            _complete_extraction_run(run_id)
            return {
                "kg_extraction_run_id": run_id,
                "kg_entities": normalized["entities"],
                "kg_relations": normalized["relations"],
                "kg_claims": normalized["claims"],
            }
        except Exception as exc:
            recovered = _recover_bundle_from_exception(
                exc,
                available_chunk_ids=available_chunk_ids,
            )
            if recovered is None:
                recovered = _recover_bundle_from_raw_output(
                    llm=llm,
                    messages=messages,
                    available_chunk_ids=available_chunk_ids,
                )
            if recovered is not None and not _has_traceable_evidence(recovered):
                recovered = None
            if recovered is not None:
                _complete_extraction_run(run_id)
                return {
                    "kg_extraction_run_id": run_id,
                    "kg_entities": recovered["entities"],
                    "kg_relations": recovered["relations"],
                    "kg_claims": recovered["claims"],
                }
            _fail_extraction_run(run_id, str(exc))

    fallback = _build_fallback_bundle(state, chunk_ids)
    return {
        "kg_extraction_run_id": run_id,
        "kg_entities": fallback["entities"],
        "kg_relations": fallback["relations"],
        "kg_claims": fallback["claims"],
    }


def _load_source_chunks(state: AuditGraphState) -> tuple[list[dict[str, Any]], list[int]]:
    payload = get_heavy_payload(state.get("chunk_batch_ref", ""))
    if not isinstance(payload, dict):
        return [], []
    source_chunks = [chunk for chunk in payload.get("chunks", []) if isinstance(chunk, dict)]
    source_file_ids = [
        int(file_row["id"])
        for file_row in payload.get("files", [])
        if isinstance(file_row, dict) and int(file_row.get("id", 0) or 0) > 0
    ]
    return source_chunks, source_file_ids


def _build_extraction_input(state: AuditGraphState, source_chunks: list[dict[str, Any]]) -> str:
    if source_chunks:
        parts = []
        for chunk in source_chunks[:MAX_EXTRACTION_CHUNKS]:
            chunk_id = str(chunk.get("chunk_id", ""))
            page_no = int(chunk.get("page_no", 0) or 0)
            chunk_type = str(chunk.get("chunk_type", "text") or "text")
            chunk_text = str(chunk.get("chunk_text", "") or "").strip()
            if not chunk_id or not chunk_text:
                continue
            if len(chunk_text) > MAX_CHUNK_TEXT_CHARS:
                chunk_text = f"{chunk_text[:MAX_CHUNK_TEXT_CHARS]}..."
            parts.append(f"[chunk_id={chunk_id}][page={page_no}][type={chunk_type}]\n{chunk_text}")
        if parts:
            return "\n\n".join(parts)
    return resolve_aggregated_text(state).strip()


def _normalize_bundle(
    bundle: dict[str, Any],
    *,
    available_chunk_ids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    entities = []
    for entity in bundle.get("entities", []):
        entity_dict = entity if isinstance(entity, dict) else entity.model_dump()
        entity_dict["evidence_chunk_ids"] = _normalize_evidence_ids(
            entity_dict.get("evidence_chunk_ids", []),
            available_chunk_ids,
        )
        entity_dict["first_seen_chunk_id"] = str(
            entity_dict.get("first_seen_chunk_id") or (entity_dict["evidence_chunk_ids"][0] if entity_dict["evidence_chunk_ids"] else "")
        )
        entity_dict["source_count"] = int(
            entity_dict.get("source_count") or len(entity_dict["evidence_chunk_ids"]) or 1
        )
        entity_dict["human_verified"] = bool(entity_dict.get("human_verified", False))
        entity_dict["status"] = str(entity_dict.get("status") or DEFAULT_GRAPH_STATUS)
        entities.append(entity_dict)

    relations = []
    for relation in bundle.get("relations", []):
        relation_dict = relation if isinstance(relation, dict) else relation.model_dump()
        relation_dict["evidence_chunk_ids"] = _normalize_evidence_ids(
            relation_dict.get("evidence_chunk_ids", []),
            available_chunk_ids,
        )
        relation_dict["direction"] = str(relation_dict.get("direction") or "directed")
        relation_dict["source_count"] = int(
            relation_dict.get("source_count") or len(relation_dict["evidence_chunk_ids"]) or 1
        )
        relation_dict["human_verified"] = bool(relation_dict.get("human_verified", False))
        relation_dict["status"] = str(relation_dict.get("status") or DEFAULT_GRAPH_STATUS)
        relations.append(relation_dict)

    claims = []
    for claim in bundle.get("claims", []):
        claim_dict = claim if isinstance(claim, dict) else claim.model_dump()
        claim_dict["evidence_chunk_ids"] = _normalize_evidence_ids(
            claim_dict.get("evidence_chunk_ids", []),
            available_chunk_ids,
        )
        claim_dict["claim_type"] = _normalize_claim_type(
            claim_dict.get("claim_type"),
            claim_text=str(claim_dict.get("claim_text", "") or ""),
            relation_temp_id=claim_dict.get("relation_temp_id"),
        )
        claim_dict["status"] = str(claim_dict.get("status") or DEFAULT_GRAPH_STATUS)
        claim_dict["review_status"] = str(claim_dict.get("review_status") or "pending")
        claims.append(claim_dict)
    return {"entities": entities, "relations": relations, "claims": claims}


def _normalize_evidence_ids(raw_ids: list[str], available_chunk_ids: set[str]) -> list[str]:
    normalized = [str(chunk_id) for chunk_id in raw_ids if str(chunk_id) in available_chunk_ids]
    return normalized[:8]


def _has_traceable_evidence(bundle: dict[str, list[dict[str, Any]]]) -> bool:
    """Require every persisted graph item to cite at least one available source chunk."""
    claims = list(bundle.get("claims", []) or [])
    all_items = [
        *list(bundle.get("entities", []) or []),
        *list(bundle.get("relations", []) or []),
        *claims,
    ]
    return bool(claims) and all(
        bool(item.get("evidence_chunk_ids"))
        for item in all_items
        if isinstance(item, dict)
    )


def _normalize_claim_type(raw_claim_type: Any, *, claim_text: str, relation_temp_id: Any) -> str:
    normalized = str(raw_claim_type or "").strip().lower()
    family = _claim_semantic_family(claim_text)
    if relation_temp_id:
        return "relation_fact"
    if family in {"risk", "exception"}:
        return "risk_signal"
    if normalized in {"entity_fact", "relation_fact", "risk_signal"}:
        return normalized
    return "entity_fact"


def _claim_semantic_family(claim_text: str) -> str:
    normalized = _normalize_claim_text(claim_text)
    if not normalized:
        return "generic"
    if any(marker in normalized for marker in ("营业收入", "收入确认", "截止性", "截止测试", "跨期")):
        return "revenue_recognition"
    if any(marker in normalized for marker in ("应收账款", "账龄", "坏账准备", "函证", "总账")):
        return "receivable_aging"
    if any(marker in normalized for marker in ("银行流水", "银行账户", "对账单", "未达账项")):
        return "bank_transaction"
    if any(marker in normalized for marker in ("关联方", "控制", "股东")):
        return "related_party"
    if any(marker in normalized for marker in ("开户行", "账号")):
        return "bank_account"
    if any(marker in normalized for marker in ("凭证", "分录", "科目")):
        return "journal_entry"
    if "发票" in normalized:
        return "invoice"
    if "合同" in normalized:
        return "contract"
    if any(marker in normalized for marker in ("异常", "错报", "差异", "不一致")):
        return "exception"
    return "generic"


def _normalize_claim_text(value: str) -> str:
    return "".join(str(value or "").strip().lower().split())


def _recover_bundle_from_raw_output(
    *,
    llm: Any,
    messages: list[Any],
    available_chunk_ids: set[str],
) -> dict[str, list[dict[str, Any]]] | None:
    """Retry extraction with plain text output and salvage JSON-like content when possible."""
    try:
        raw_result = llm.invoke(messages)
    except Exception:
        return None
    raw_text = _extract_message_text(raw_result)
    if not raw_text.strip():
        return None
    bundle = _salvage_bundle_from_text(raw_text)
    if bundle is None:
        return None
    return _normalize_bundle(bundle, available_chunk_ids=available_chunk_ids)


def _recover_bundle_from_exception(
    exc: Exception,
    *,
    available_chunk_ids: set[str],
) -> dict[str, list[dict[str, Any]]] | None:
    """Salvage bundle text embedded inside parser/validation exceptions."""
    for text in _extract_exception_text_candidates(exc):
        bundle = _salvage_bundle_from_text(text)
        if bundle is not None:
            return _normalize_bundle(bundle, available_chunk_ids=available_chunk_ids)
    return None


def _extract_message_text(raw_result: Any) -> str:
    """Flatten common LangChain message/result shapes into plain text."""
    if isinstance(raw_result, str):
        return raw_result
    content = getattr(raw_result, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _salvage_bundle_from_text(text: str) -> dict[str, Any] | None:
    """Recover a bundle from raw model text, fenced JSON, or sectioned JSON fragments."""
    for candidate in _iter_json_candidates(text):
        bundle = _coerce_bundle_candidate(candidate)
        if bundle is not None:
            return bundle
    inline = _parse_inline_keyed_bundle(text)
    if inline is not None:
        return inline
    sectioned = _parse_sectioned_bundle(text)
    if sectioned is not None:
        return sectioned
    return _parse_yaml_like_bundle(text)


def _extract_exception_text_candidates(exc: Exception) -> list[str]:
    """Pull raw model output candidates out of validation exceptions and their string forms."""
    candidates: list[str] = []
    seen: set[str] = set()

    def push(value: Any) -> None:
        if not isinstance(value, str):
            return
        normalized = value.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    push(str(exc))
    errors_method = getattr(exc, "errors", None)
    if callable(errors_method):
        try:
            errors = errors_method()
        except TypeError:
            errors = []
        except Exception:
            errors = []
        for item in errors:
            if not isinstance(item, dict):
                continue
            push(item.get("input"))
            push(item.get("input_value"))

    for match in re.finditer(r"input_value='((?:\\'|[^'])*)'", str(exc), flags=re.DOTALL):
        decoded = (
            match.group(1)
            .replace("\\r", "\r")
            .replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace('\\"', '"')
            .replace("\\'", "'")
            .replace("\\\\", "\\")
        )
        push(decoded)
    return candidates


def _iter_json_candidates(text: str) -> list[Any]:
    """Decode likely JSON candidates from the raw response in most-promising order."""
    candidates: list[Any] = []
    seen: set[str] = set()
    for fragment in _iter_json_fragments(text):
        normalized_fragment = fragment.strip()
        if not normalized_fragment or normalized_fragment in seen:
            continue
        seen.add(normalized_fragment)
        try:
            candidates.append(json.loads(normalized_fragment))
        except json.JSONDecodeError:
            continue
    return candidates


def _iter_json_fragments(text: str) -> list[str]:
    """Collect raw fragments that could plausibly decode as JSON."""
    fragments = [text]
    for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE):
        fragments.append(match.group(1))
    fragments.extend(_extract_balanced_json_blocks(text, "{", "}"))
    fragments.extend(_extract_balanced_json_blocks(text, "[", "]"))
    return fragments


def _extract_balanced_json_blocks(text: str, open_char: str, close_char: str) -> list[str]:
    """Extract balanced JSON-like blocks while ignoring braces inside strings."""
    blocks: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == open_char:
            if depth == 0:
                start = index
            depth += 1
        elif char == close_char and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                blocks.append(text[start : index + 1])
                start = -1
    return blocks


def _coerce_bundle_candidate(candidate: Any) -> dict[str, Any] | None:
    """Normalize one decoded JSON payload into the bundle schema."""
    if not isinstance(candidate, dict):
        return None
    bundle = _normalize_bundle_aliases(
        {
            "entities": _coerce_item_list(candidate.get("entities")),
            "relations": _coerce_item_list(candidate.get("relations")),
            "claims": _coerce_item_list(candidate.get("claims")),
        }
    )
    if not any(bundle.values()):
        return None
    try:
        validated = ExtractionBundleModel.model_validate(bundle)
    except ValidationError:
        return None
    return validated.model_dump()


def _coerce_item_list(value: Any) -> list[dict[str, Any]]:
    """Accept either a list of objects or a single object for one bundle section."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _parse_sectioned_bundle(text: str) -> dict[str, Any] | None:
    """Recover outputs shaped like `entities ... relations ... claims ...` without outer JSON."""
    sections: dict[str, list[dict[str, Any]]] = {"entities": [], "relations": [], "claims": []}
    pattern = re.compile(
        r"(?ims)^\s*(entities|relations|claims)\s*:?\s*$\n(.*?)(?=^\s*(?:entities|relations|claims)\s*:?\s*$|\Z)"
    )
    for match in pattern.finditer(text):
        section_name = match.group(1).lower()
        parsed_items = _parse_section_items(match.group(2))
        if parsed_items:
            sections[section_name].extend(parsed_items)

    sections = _normalize_bundle_aliases(sections)
    if not any(sections.values()):
        return None
    try:
        validated = ExtractionBundleModel.model_validate(sections)
    except ValidationError:
        return None
    return validated.model_dump()


def _parse_inline_keyed_bundle(text: str) -> dict[str, Any] | None:
    """Parse outputs shaped like `entities:[...] relations:[...] claims:[...]`."""
    pattern = re.compile(
        r"(?is)(entities|relations|claims)\s*:\s*(\[.*?\]|\{.*?\})(?=\s*(?:entities|relations|claims)\s*:|\s*\Z)"
    )
    sections: dict[str, list[dict[str, Any]]] = {"entities": [], "relations": [], "claims": []}
    for match in pattern.finditer(text.strip()):
        section_name = match.group(1).lower()
        parsed_items = _parse_section_items(match.group(2))
        if parsed_items:
            sections[section_name].extend(parsed_items)
    sections = _normalize_bundle_aliases(sections)
    if not any(sections.values()):
        return None
    try:
        validated = ExtractionBundleModel.model_validate(sections)
    except ValidationError:
        return None
    return validated.model_dump()


def _parse_section_items(section_text: str) -> list[dict[str, Any]]:
    """Parse one section body as a JSON array, one object, or many sibling objects."""
    text = section_text.strip()
    if not text:
        return []
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, list):
        return [item for item in decoded if isinstance(item, dict)]
    if isinstance(decoded, dict):
        return [decoded]

    items: list[dict[str, Any]] = []
    for block in _extract_balanced_json_blocks(text, "{", "}"):
        try:
            decoded_item = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded_item, dict):
            items.append(decoded_item)
    return items


def _parse_yaml_like_bundle(text: str) -> dict[str, Any] | None:
    """Parse YAML-like provider output and remap common field aliases into our schema."""
    try:
        decoded = yaml.safe_load(text)
    except Exception:
        return None
    if not isinstance(decoded, dict):
        return None

    bundle = _normalize_bundle_aliases(
        {
        "entities": [_normalize_yaml_entity(item) for item in decoded.get("entities", []) if isinstance(item, dict)],
        "relations": [_normalize_yaml_relation(item) for item in decoded.get("relations", []) if isinstance(item, dict)],
        "claims": [_normalize_yaml_claim(item) for item in decoded.get("claims", []) if isinstance(item, dict)],
        }
    )
    bundle["entities"] = [item for item in bundle["entities"] if item]
    bundle["relations"] = [item for item in bundle["relations"] if item]
    bundle["claims"] = [item for item in bundle["claims"] if item]
    if not any(bundle.values()):
        return None
    try:
        validated = ExtractionBundleModel.model_validate(bundle)
    except ValidationError:
        return None
    return validated.model_dump()


def _normalize_bundle_aliases(bundle: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Map common provider aliases into the canonical extraction bundle schema."""
    return {
        "entities": [_normalize_generic_entity(item) for item in bundle.get("entities", []) if isinstance(item, dict)],
        "relations": [_normalize_generic_relation(item) for item in bundle.get("relations", []) if isinstance(item, dict)],
        "claims": [_normalize_generic_claim(item) for item in bundle.get("claims", []) if isinstance(item, dict)],
    }


def _normalize_generic_entity(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one entity record from JSON/YAML/provider alias keys."""
    if _looks_like_canonical_entity(item):
        return item
    attributes = item.get("attributes", {})
    if isinstance(attributes, str):
        attributes = {"summary": attributes}
    elif not isinstance(attributes, dict):
        attributes = {}
    return {
        "entity_temp_id": str(item.get("entity_temp_id") or item.get("entity_id") or ""),
        "entity_type": str(item.get("entity_type") or "unknown"),
        "name": str(item.get("name") or item.get("entity_name") or item.get("canonical_name") or ""),
        "aliases": item.get("aliases") if isinstance(item.get("aliases"), list) else [],
        "attributes": attributes,
        "evidence_chunk_ids": _coerce_string_list(item.get("evidence_chunk_ids") or item.get("chunk_ids")),
        "confidence": _coerce_confidence(item.get("confidence"), default=0.8),
    }


def _normalize_generic_relation(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one relation record from JSON/YAML/provider alias keys."""
    if _looks_like_canonical_relation(item):
        return item
    attributes = item.get("attributes", {})
    if isinstance(attributes, str):
        attributes = {"summary": attributes}
    elif not isinstance(attributes, dict):
        attributes = {}
    relation_type = str(item.get("relation_type") or "related_to")
    return {
        "relation_temp_id": str(item.get("relation_temp_id") or item.get("relation_id") or ""),
        "from_entity_temp_id": str(item.get("from_entity_temp_id") or item.get("from_entity_id") or ""),
        "to_entity_temp_id": str(item.get("to_entity_temp_id") or item.get("to_entity_id") or ""),
        "relation_type": relation_type,
        "relation_label": str(item.get("relation_label") or relation_type),
        "amount": _coerce_optional_float(item.get("amount")),
        "amount_currency": str(item.get("amount_currency") or "CNY"),
        "event_date": _coerce_optional_str(item.get("event_date")),
        "attributes": attributes,
        "evidence_chunk_ids": _coerce_string_list(item.get("evidence_chunk_ids") or item.get("chunk_ids")),
        "confidence": _coerce_confidence(item.get("confidence"), default=0.8),
    }


def _normalize_generic_claim(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one claim record from JSON/YAML/provider alias keys."""
    if _looks_like_canonical_claim(item):
        return item
    return {
        "claim_type": str(item.get("claim_type") or "entity_fact"),
        "claim_text": str(item.get("claim_text") or item.get("text") or ""),
        "entity_temp_id": _coerce_optional_str(item.get("entity_temp_id") or item.get("entity_id")),
        "relation_temp_id": _coerce_optional_str(item.get("relation_temp_id") or item.get("relation_id")),
        "claim_value": item.get("claim_value") if isinstance(item.get("claim_value"), dict) else {},
        "evidence_chunk_ids": _coerce_string_list(item.get("evidence_chunk_ids") or item.get("chunk_ids")),
        "confidence": _coerce_confidence(item.get("confidence"), default=0.8),
        "status": str(item.get("status") or DEFAULT_GRAPH_STATUS),
        "review_status": str(item.get("review_status") or "pending"),
    }


def _looks_like_canonical_entity(item: dict[str, Any]) -> bool:
    """Detect whether one entity dict already matches our canonical schema keys."""
    return "name" in item and "entity_type" in item and "confidence" in item


def _looks_like_canonical_relation(item: dict[str, Any]) -> bool:
    """Detect whether one relation dict already matches our canonical schema keys."""
    return "from_entity_temp_id" in item and "to_entity_temp_id" in item and "confidence" in item


def _looks_like_canonical_claim(item: dict[str, Any]) -> bool:
    """Detect whether one claim dict already matches our canonical schema keys."""
    return "claim_type" in item and "claim_text" in item and "confidence" in item


def _normalize_yaml_entity(item: dict[str, Any]) -> dict[str, Any]:
    """Map provider-specific entity keys into ExtractionBundleModel fields."""
    attributes = item.get("attributes", {})
    if isinstance(attributes, str):
        attributes = {"summary": attributes}
    elif not isinstance(attributes, dict):
        attributes = {}
    return {
        "entity_temp_id": str(item.get("entity_temp_id") or item.get("entity_id") or ""),
        "entity_type": str(item.get("entity_type") or "unknown"),
        "name": str(item.get("name") or ""),
        "aliases": item.get("aliases") if isinstance(item.get("aliases"), list) else [],
        "attributes": attributes,
        "evidence_chunk_ids": _coerce_string_list(item.get("evidence_chunk_ids") or item.get("chunk_ids")),
        "confidence": _coerce_confidence(item.get("confidence"), default=0.8),
    }


def _normalize_yaml_relation(item: dict[str, Any]) -> dict[str, Any]:
    """Map provider-specific relation keys into ExtractionBundleModel fields."""
    attributes = item.get("attributes", {})
    if isinstance(attributes, str):
        attributes = {"summary": attributes}
    elif not isinstance(attributes, dict):
        attributes = {}
    relation_type = str(item.get("relation_type") or "related_to")
    return {
        "relation_temp_id": str(item.get("relation_temp_id") or item.get("relation_id") or ""),
        "from_entity_temp_id": str(item.get("from_entity_temp_id") or item.get("from_entity_id") or ""),
        "to_entity_temp_id": str(item.get("to_entity_temp_id") or item.get("to_entity_id") or ""),
        "relation_type": relation_type,
        "relation_label": str(item.get("relation_label") or relation_type),
        "amount": _coerce_optional_float(item.get("amount")),
        "amount_currency": str(item.get("amount_currency") or "CNY"),
        "event_date": _coerce_optional_str(item.get("event_date")),
        "attributes": attributes,
        "evidence_chunk_ids": _coerce_string_list(item.get("evidence_chunk_ids") or item.get("chunk_ids")),
        "confidence": _coerce_confidence(item.get("confidence"), default=0.8),
    }


def _normalize_yaml_claim(item: dict[str, Any]) -> dict[str, Any]:
    """Map provider-specific claim keys into ExtractionBundleModel fields."""
    return {
        "claim_type": str(item.get("claim_type") or "entity_fact"),
        "claim_text": str(item.get("claim_text") or ""),
        "entity_temp_id": _coerce_optional_str(item.get("entity_temp_id") or item.get("entity_id")),
        "relation_temp_id": _coerce_optional_str(item.get("relation_temp_id") or item.get("relation_id")),
        "claim_value": item.get("claim_value") if isinstance(item.get("claim_value"), dict) else {},
        "evidence_chunk_ids": _coerce_string_list(item.get("evidence_chunk_ids") or item.get("chunk_ids")),
        "confidence": _coerce_confidence(item.get("confidence"), default=0.8),
        "status": str(item.get("status") or DEFAULT_GRAPH_STATUS),
        "review_status": str(item.get("review_status") or "pending"),
    }


def _coerce_string_list(value: Any) -> list[str]:
    """Normalize one field into a list of non-empty strings."""
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _coerce_confidence(value: Any, *, default: float) -> float:
    """Normalize confidence-like values into bounded floats."""
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        normalized = default
    return max(0.0, min(1.0, normalized))


def _coerce_optional_float(value: Any) -> float | None:
    """Best-effort float coercion for optional numeric fields."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_str(value: Any) -> str | None:
    """Return a stripped string or None for empty values."""
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _build_fallback_bundle(state: AuditGraphState, chunk_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    entity_name = state.get("current_entity_name", "")
    entity_temp_id = "entity_audited_1"
    relation_temp_id = "relation_placeholder_1"
    first_chunk_id = chunk_ids[0]
    case_id = int(state.get("current_case_id", 0) or 0)
    canonical_name = entity_name or "未知被审计单位"
    normalized_name = normalize_entity_name(canonical_name)
    entity_key = build_entity_key(case_id=case_id, entity_type="company", normalized_name=normalized_name)
    relation_key = build_relation_key(
        case_id=case_id,
        relation_type="audited_entity",
        from_entity_key=entity_key,
        to_entity_key=entity_key,
        relation_label="被审计单位",
    )
    return {
        "entities": [
            {
                "entity_temp_id": entity_temp_id,
                "entity_key": entity_key,
                "entity_type": "company",
                "name": canonical_name,
                "canonical_name": canonical_name,
                "aliases": [],
                "normalized_name": normalized_name,
                "attributes": {},
                "first_seen_chunk_id": first_chunk_id,
                "evidence_chunk_ids": [first_chunk_id],
                "confidence": 0.6,
                "source_count": 1,
                "human_verified": False,
                "status": DEFAULT_GRAPH_STATUS,
            }
        ],
        "relations": [
            {
                "relation_temp_id": relation_temp_id,
                "relation_key": relation_key,
                "from_entity_temp_id": entity_temp_id,
                "to_entity_temp_id": entity_temp_id,
                "relation_type": "audited_entity",
                "relation_label": "被审计单位",
                "direction": "directed",
                "amount": None,
                "amount_currency": "CNY",
                "event_date": None,
                "attributes": {"placeholder": True},
                "evidence_chunk_ids": [first_chunk_id],
                "confidence": 0.3,
                "source_count": 1,
                "human_verified": False,
                "status": DEFAULT_GRAPH_STATUS,
            }
        ],
        "claims": [
            {
                "claim_type": "entity_fact",
                "claim_text": f"当前资料对应被审计单位：{entity_name or '未知被审计单位'}",
                "entity_temp_id": entity_temp_id,
                "relation_temp_id": relation_temp_id,
                "claim_value": {},
                "evidence_chunk_ids": [first_chunk_id],
                "confidence": 0.5,
                "status": DEFAULT_GRAPH_STATUS,
                "review_status": "pending",
            }
        ],
    }


def _create_extraction_run(case_id: int, source_file_ids: list[int], chunk_count: int) -> int:
    if case_id <= 0:
        return 0
    try:
        settings = get_settings()
        config = settings.get_llm_config("agent")
        return get_kg_service().create_extraction_run(
            case_id=case_id,
            run_type="ingest",
            trigger_source="system",
            source_file_ids=source_file_ids,
            chunk_count=chunk_count,
            prompt_version=PROMPT_VERSION,
            model_provider=config["provider"],
            model_name=config["model"],
            status="running",
        )
    except Exception:
        return 0


def _complete_extraction_run(run_id: int) -> None:
    if run_id <= 0:
        return
    try:
        get_kg_service().complete_extraction_run(run_id)
    except Exception:
        pass


def _fail_extraction_run(run_id: int, error_message: str) -> None:
    if run_id <= 0:
        return
    try:
        get_kg_service().fail_extraction_run(run_id, error_message[:1000])
    except Exception:
        pass

import json
import logging
import re

from ...services.kg_service import get_kg_service
from ...settings import get_settings
from ..context_loader import (
    build_report_citation_id,
    resolve_computed_metrics,
    resolve_kg_trace_summary,
    resolve_report_part_a,
    resolve_report_part_b,
    resolve_report_section,
    resolve_trace_items,
)
from ..report_sections import SECTION_IDS
from ..heavy_state import put_heavy_payload
from ..llm import build_zero_temp_router_llm
from ..schemas import TaskExtractionModel, TaskItemModel
from ..state import AuditGraphState

LOGGER = logging.getLogger(__name__)


INLINE_CITATION_PATTERN = re.compile(r"\[\[CLM-(\d+)\]\]")
OUTWARD_CITATION_PATTERN = re.compile(r"\[(\d+)\]")
JSON_BLOCK_PATTERN = re.compile(
    r"```json\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)
TABLE_SEPARATOR_PATTERN = re.compile(r"^\|\s*[:\-|\s]+\|?\s*$")
LATIN_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%-]{1,}")
TRAILING_PUNCTUATION = "。；;，,：:）)]》\"'"


def _parse_task_json_block(text: str) -> list[TaskItemModel]:
    match = JSON_BLOCK_PATTERN.search(text)
    if not match:
        return []

    try:
        payload = json.loads(match.group(1))
        parsed = TaskExtractionModel.model_validate(payload)
        return parsed.tasks
    except Exception:
        return []


def _extract_tasks_with_llm(text: str) -> list[TaskItemModel]:
    settings = get_settings()
    if not settings.get_llm_config("report_b")["api_key"]:
        return []

    try:
        llm = build_zero_temp_router_llm()
        structured_llm = llm.with_structured_output(TaskExtractionModel)
        result = structured_llm.invoke(f"提取以下文本中的督办任务：\n{text}")
        return result.tasks
    except Exception:
        return []


def _fallback_extract_tasks(text: str) -> list[TaskItemModel]:
    pattern = re.compile(
        r"任务\s*\d+[：:]\s*(?P<action>.+?)\n"
        r".*?(?:执行角色|责任人)[：:]\s*(?P<role>.+?)\n"
        r".*?(?:推荐时限|时限)[：:]\s*(?P<deadline>.+?)\n"
        r".*?(?:验收交付物|交付标准)[：:]\s*(?P<deliverable>.+?)(?:\n|$)",
        re.DOTALL,
    )
    tasks: list[TaskItemModel] = []
    for match in pattern.finditer(text):
        action = match.group("action").strip(" *")
        priority = "高" if any(k in action for k in ("刑事", "保全", "查封", "冻结", "撤销")) else "中"
        tasks.append(
            TaskItemModel(
                action=action,
                role=match.group("role").strip(" *"),
                deadline=match.group("deadline").strip(" *"),
                deliverable=match.group("deliverable").strip(" *"),
                priority=priority,
            )
        )
    return tasks


def _extract_tasks(text: str) -> list[TaskItemModel]:
    for extractor in (_parse_task_json_block, _extract_tasks_with_llm, _fallback_extract_tasks):
        tasks = extractor(text)
        if tasks:
            return tasks
    return []


def _apply_inline_citations(
    text: str,
    *,
    citation_id_by_claim_id: dict[int, str],
) -> tuple[str, set[int]]:
    """Convert LLM placeholders like [[CLM-31]] into outward-facing [1] citations."""
    used_claim_ids: set[int] = set()

    def _replace(match: re.Match[str]) -> str:
        claim_id = int(match.group(1) or 0)
        citation_id = citation_id_by_claim_id.get(claim_id, "")
        if not citation_id:
            return ""
        used_claim_ids.add(claim_id)
        return f"[{citation_id}]"

    return INLINE_CITATION_PATTERN.sub(_replace, text), used_claim_ids


def _normalize_match_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _extract_cjk_bigrams(text: str) -> set[str]:
    normalized = _normalize_match_text(text)
    cjk_only = "".join(ch for ch in normalized if "\u4e00" <= ch <= "\u9fff")
    return {cjk_only[index : index + 2] for index in range(len(cjk_only) - 1)}


def _extract_latin_tokens(text: str) -> set[str]:
    return {token.lower() for token in LATIN_TOKEN_PATTERN.findall(text or "")}


def _build_claim_match_index(trace_items: list[dict[str, object]]) -> list[dict[str, object]]:
    index: list[dict[str, object]] = []
    for item in trace_items:
        citation_id = str(item.get("citation_id", "") or "")
        claim_text = str(item.get("claim_text", "") or "").strip()
        if not citation_id or not claim_text:
            continue
        evidence_quotes = []
        for evidence in item.get("evidences", []):
            if not isinstance(evidence, dict):
                continue
            quote_text = str(evidence.get("quote_text", "") or "").strip()
            if quote_text:
                evidence_quotes.append(quote_text)
        corpus = "\n".join([claim_text, *evidence_quotes])
        index.append(
            {
                "citation_id": citation_id,
                "claim_text": claim_text,
                "corpus": corpus,
                "cjk_bigrams": _extract_cjk_bigrams(corpus),
                "latin_tokens": _extract_latin_tokens(corpus),
            }
        )
    return index


def _score_line_for_citation(line: str, claim_entry: dict[str, object]) -> int:
    normalized_line = _normalize_match_text(line)
    normalized_claim = _normalize_match_text(str(claim_entry.get("claim_text", "") or ""))
    if not normalized_line or not normalized_claim:
        return 0
    if normalized_claim in normalized_line or normalized_line in normalized_claim:
        return 100

    line_bigrams = _extract_cjk_bigrams(line)
    line_tokens = _extract_latin_tokens(line)
    claim_bigrams = claim_entry.get("cjk_bigrams", set())
    claim_tokens = claim_entry.get("latin_tokens", set())
    shared_bigrams = len(line_bigrams & claim_bigrams)
    shared_tokens = len(line_tokens & claim_tokens)
    digit_bonus = 1 if re.search(r"\d", line) and shared_tokens > 0 else 0
    return shared_bigrams + (shared_tokens * 2) + digit_bonus


def _line_needs_autocite(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("```"):
        return False
    if stripped.startswith("#"):
        return False
    if OUTWARD_CITATION_PATTERN.search(stripped):
        return False
    if TABLE_SEPARATOR_PATTERN.match(stripped):
        return False
    if stripped.startswith("|"):
        return True
    if stripped.startswith(("- ", "* ")):
        return True
    if re.match(r"^\d+\.", stripped):
        return True
    return len(stripped) >= 12 and any(punct in stripped for punct in ("。", "；", ";", "：", ":"))


def _append_citation_to_line(line: str, citation_id: str) -> str:
    stripped = line.rstrip()
    if not stripped or not citation_id or OUTWARD_CITATION_PATTERN.search(stripped):
        return line
    if stripped.startswith("|") and stripped.endswith("|"):
        return f"{stripped[:-1]} [{citation_id}] |"
    suffix = ""
    if stripped[-1] in TRAILING_PUNCTUATION:
        suffix = stripped[-1]
        stripped = stripped[:-1].rstrip()
    return f"{stripped}[{citation_id}]{suffix}"


def _autocite_report_text(text: str, trace_items: list[dict[str, object]]) -> tuple[str, set[str]]:
    claim_index = _build_claim_match_index(trace_items)
    if not text.strip() or not claim_index:
        return text, set()

    used_citation_ids: set[str] = set()
    lines = text.splitlines()
    inside_fence = False
    rendered_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            inside_fence = not inside_fence
            rendered_lines.append(line)
            continue
        if inside_fence or not _line_needs_autocite(line):
            rendered_lines.append(line)
            continue

        best_score = 0
        best_citation_id = ""
        for claim_entry in claim_index:
            score = _score_line_for_citation(line, claim_entry)
            if score > best_score:
                best_score = score
                best_citation_id = str(claim_entry.get("citation_id", "") or "")
        if best_citation_id and best_score >= 4:
            used_citation_ids.add(best_citation_id)
            rendered_lines.append(_append_citation_to_line(line, best_citation_id))
            continue
        rendered_lines.append(line)
    return "\n".join(rendered_lines), used_citation_ids


def _build_citation_coverage(
    trace_items: list[dict[str, object]],
    used_claim_ids: set[int],
) -> dict[str, object]:
    total_claims = 0
    cited_claims = 0
    missing_items: list[dict[str, object]] = []
    for item in trace_items:
        claim_id = int(item.get("claim_id", 0) or 0)
        citation_id = str(item.get("citation_id", "") or "")
        claim_text = str(item.get("claim_text", "") or "").strip()
        if claim_id <= 0 or not citation_id or not claim_text:
            continue
        total_claims += 1
        if claim_id in used_claim_ids:
            cited_claims += 1
            continue
        missing_items.append(
            {
                "citation_id": citation_id,
                "claim_id": claim_id,
                "claim_type": str(item.get("claim_type", "") or ""),
                "claim_text": claim_text,
            }
        )
    uncited_claims = max(total_claims - cited_claims, 0)
    coverage_ratio = (cited_claims / total_claims) if total_claims > 0 else 0.0
    return {
        "total_claims": total_claims,
        "cited_claims": cited_claims,
        "uncited_claims": uncited_claims,
        "coverage_ratio": round(coverage_ratio, 4),
        "missing_items": missing_items,
    }


def _aggregate_risk_alerts(state: AuditGraphState, cm: dict) -> list[dict]:
    """从报告数值引擎(归零/盲估/不可拆分/口径校验)+ 时效看板红/过期项，聚合风险提示。"""
    dq = (cm.get("data_quality", {}) or {})
    alerts: list[dict] = []
    zeroed = dq.get("zeroed") or []
    if zeroed:
        names = "、".join(str(z.get("name", "") or "") for z in zeroed if isinstance(z, dict))[:120]
        alerts.append({"type": "估值归零", "level": "high", "source": "报告自动",
                       "message": f"{len(zeroed)} 项资产因极端风险被归零（{names}）"})
    if dq.get("is_estimated_count"):
        alerts.append({"type": "盲估", "level": "mid", "source": "报告自动",
                       "message": f"{dq['is_estimated_count']} 项资产为系统盲估，无实测依据"})
    if dq.get("unsplittable_claim_count"):
        alerts.append({"type": "债权口径", "level": "mid", "source": "报告自动",
                       "message": f"{dq['unsplittable_claim_count']} 笔债权无法拆分本息"})
    cc = dq.get("cross_check")
    if isinstance(cc, dict) and cc:
        alerts.append({"type": "口径差异", "level": "high", "source": "报告自动",
                       "message": "资产净值在汇总口径与逐项核算间存在差异，需复核"})
    # 时效看板红/过期项：用确定性时效引擎重算（与 /cases/{id}/deadline-board 口径统一）
    try:
        from ..context_loader import resolve_full_context_data
        from ..deadline_board import compute_deadline_board
        deadline = (resolve_full_context_data(state).get("engine_results", {}) or {}).get("deadline_scan", {}) or {}
        counts = compute_deadline_board(deadline).get("counts", {})
        n_expired = counts.get("expired", 0)
        n_red = counts.get("red", 0)
        if n_expired:
            alerts.append({"type": "时效已过期", "level": "high", "source": "报告自动",
                           "message": f"{n_expired} 项司法时效已过期，需立即处理"})
        if n_red:
            alerts.append({"type": "时效红色预警", "level": "high", "source": "报告自动",
                           "message": f"{n_red} 项司法时效红色预警"})
    except Exception:  # noqa: BLE001
        pass
    return alerts


_THOUSANDS_SEP = re.compile(r"(\d),(?=\d{3}(?:\D|$))")


def _strip_thousands_separators(text: str) -> str:
    """去掉数字千分位逗号（金额口径要求无千分位）。ASCII 逗号夹在数字组间必是千分位，
    中文正文用「，」「、」，故安全。循环处理多组（1,234,567 → 1234567）。"""
    if not text or "," not in text:
        return text
    prev = None
    out = text
    while prev != out:
        prev = out
        out = _THOUSANDS_SEP.sub(r"\1", out)
    return out


def _seed_recovery_forecast(state: AuditGraphState, case_id: int, final_report_ref: str) -> None:
    """报告出完后种子化：预期回款(NPV 三档) + 风险提示聚合写入进度。best-effort，吞异常。"""
    if case_id <= 0:
        return
    try:
        import datetime

        from ...services.progress_service import get_progress_service

        cm = resolve_computed_metrics(state) or {}
        svc = get_progress_service()
        # 预期回款：NPV 三档
        npv = cm.get("npv", {}) or {}
        forecast = npv.get("tranche_forecast", {}) or {}
        if forecast:
            years = (cm.get("params", {}) or {}).get("tranche_years", {}) or {}
            today = datetime.date.today()
            tranches = []
            for tranche, amount in forecast.items():
                yr = float(years.get(tranche, 0) or 0)
                exp_date = today + datetime.timedelta(days=int(round(yr * 365))) if yr else None
                tranches.append({"tranche": tranche, "expected_amount": amount,
                                 "expected_date": exp_date, "basis": "报告NPV"})
            svc.seed_forecast(case_id, report_ref=final_report_ref, tranches=tranches)
        # 风险提示：报告自动聚合（覆盖上一轮"报告自动"项；人工项的保留策略见 Phase 2）
        risk_alerts = _aggregate_risk_alerts(state, cm)
        if risk_alerts:
            svc.upsert_progress(case_id, risk_alerts=risk_alerts)
        LOGGER.info("progress_seeded case_id=%s forecast=%s risks=%s", case_id, len(forecast), len(risk_alerts))
    except Exception as exc:  # noqa: BLE001 — 种子化失败绝不影响报告
        LOGGER.warning("progress_seed_failed case_id=%s error=%s", case_id, str(exc)[:160])


def reconcile_report_and_extract_tasks(state: AuditGraphState) -> AuditGraphState:
    case_id = int(state.get("current_case_id", 0) or 0)
    # 八段式优先：收集 1..8 段；无则回退旧 part_a/part_b（保持向后兼容）。
    section_texts = {sid: resolve_report_section(state, sid).strip() for sid in SECTION_IDS}
    use_sections = any(section_texts.values())
    if use_sections:
        body_units = [(sid, section_texts[sid]) for sid in SECTION_IDS if section_texts[sid]]
        task_source = section_texts.get("7", "")
    else:
        body_units = [
            ("a", resolve_report_part_a(state).strip()),
            ("b", resolve_report_part_b(state).strip()),
        ]
        task_source = body_units[1][1] if len(body_units) > 1 else ""
    raw_trace_items = resolve_trace_items(state)
    citation_rows: list[dict[str, object]] = []
    citation_id_by_claim_id: dict[int, str] = {}
    trace_items: list[dict[str, object]] = []
    for index, item in enumerate(raw_trace_items, start=1):
        claim_id = int(item.get("claim_id", 0) or 0)
        citation_id = build_report_citation_id(index)
        trace_item = dict(item)
        trace_item["citation_id"] = citation_id
        trace_items.append(trace_item)
        if claim_id <= 0 or not citation_id:
            continue
        citation_id_by_claim_id[claim_id] = citation_id
        citation_rows.append(
            {
                "citation_id": citation_id,
                "claim_id": claim_id,
                "report_section": "report_body",
                "ordinal": index,
                "paragraph_index": 0,
            }
        )
    # 逐段挂角标（inline placeholder + autocite），收集已用 claim/citation。
    cited_units: list[tuple[str, str]] = []
    used_claim_ids: set[int] = set()
    used_citation_ids: set[str] = set()
    for sid, text in body_units:
        text, used = _apply_inline_citations(text, citation_id_by_claim_id=citation_id_by_claim_id)
        text, auto = _autocite_report_text(text, trace_items)
        text = _strip_thousands_separators(text)  # 金额口径：去千分位（LLM 常自动加逗号）
        cited_units.append((sid, text))
        used_claim_ids |= set(used)
        used_citation_ids |= set(auto)
    section_text_by_id = {sid: text for sid, text in cited_units}
    citation_coverage = _build_citation_coverage(
        trace_items,
        used_claim_ids=used_claim_ids,
    )
    if used_citation_ids:
        for item in trace_items:
            citation_id = str(item.get("citation_id", "") or "")
            claim_id = int(item.get("claim_id", 0) or 0)
            if citation_id and citation_id in used_citation_ids and claim_id > 0:
                used_claim_ids.add(claim_id)
        citation_coverage = _build_citation_coverage(
            trace_items,
            used_claim_ids=used_claim_ids,
        )
    trace_summary = resolve_kg_trace_summary(
        state,
        citation_id_by_claim_id=citation_id_by_claim_id,
    ).strip()
    body_chunks = [text for _, text in cited_units if text]
    final_report = "\n\n".join(chunk for chunk in (*body_chunks, trace_summary) if chunk)
    final_report_ref = put_heavy_payload(
        "final_report",
        {
            "text": final_report,
            "trace_items": trace_items,
            "citation_coverage": citation_coverage,
        },
    )
    if case_id > 0 and citation_rows:
        try:
            get_kg_service().replace_report_citations(
                case_id=case_id,
                report_ref=final_report_ref,
                rows=citation_rows,
            )
        except Exception as exc:
            LOGGER.warning("replace_report_citations_failed case_id=%s error=%s", case_id, exc)
    # 任务从第 7 段（或回退 part_b）抽取；第 7 段不含 JSON 代码块，故 final_report 不再泄漏 tasks JSON。
    task_text = section_text_by_id.get("7", task_source) if use_sections else task_source
    extracted_tasks = _extract_tasks(task_text)
    result: AuditGraphState = {
        "final_report_ref": final_report_ref,
        "final_report_summary": final_report[:240],
        "final_report": "",
        "trace_items": trace_items,
        "citation_coverage": citation_coverage,
        "extracted_tasks": [task.model_dump() for task in extracted_tasks],
    }
    # 向后兼容：回填 report_part_a/b_ref（下钻 agent / normalize 等仍读 part_b 作前序上下文）。
    if use_sections:
        part_a_text = "\n\n".join(section_text_by_id[s] for s in ("1", "2", "3", "4") if section_text_by_id.get(s))
        part_b_text = "\n\n".join(section_text_by_id[s] for s in ("5", "6", "7", "8") if section_text_by_id.get(s))
        result["report_part_a_ref"] = put_heavy_payload("report_part_a", {"text": part_a_text})
        result["report_part_b_ref"] = put_heavy_payload("report_part_b", {"text": part_b_text})
    # 回款闭环：报告出完后把数值引擎 NPV 三档种子化为预期回款（best-effort，绝不拖垮报告）。
    _seed_recovery_forecast(state, case_id, final_report_ref)
    return result

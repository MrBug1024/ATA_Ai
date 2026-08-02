"""Hierarchical intent routing with high-confidence rules and structured model fallback."""

from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from .capabilities import get_capability_spec, render_route_catalog
from .llm import build_router_llm, has_api_key
from .prompting import load_prompt
from .schemas import RouteDecisionModel
from .state import AuditGraphState, Intent
from .write_contracts import (
    command_dict,
    explicit_write_capability,
    resolve_case_create_command,
    resolve_task_write_command,
    write_clarification,
)


LOGGER = logging.getLogger(__name__)
ROUTE_VERSION = "v2"
VALID_INTENTS: tuple[Intent, ...] = ("re_audit", "full_audit", "drilldown", "review")

FULL_AUDIT_KEYWORDS = (
    "完整报告",
    "完整审计",
    "全面审计",
    "重新审计",
    "八段式",
    "全流程审计",
    "全流程",
    "出具报告",
)
RE_AUDIT_KEYWORDS = ("重审", "重出", "修正", "改成", "不对", "有误", "错误")
RE_AUDIT_OBJECTS = ("报告", "估值", "房产", "矿权", "解封", "回收率", "净值", "数据", "结论")
NEGATED_RE_AUDIT_PHRASES = ("不要重审", "不用重审", "无需重审", "不需要重审")
NEGATED_FULL_AUDIT_PHRASES = (
    "不要完整报告",
    "不用完整报告",
    "无需完整报告",
    "不出完整报告",
    "不要重新审计",
    "不用重新审计",
    "无需重新审计",
)
REVIEW_KEYWORDS = ("复盘", "对账", "回款复盘", "回款对账", "预期vs实际", "预期与实际", "达成率")
TASK_KEYWORDS = ("任务", "督办", "待办")
TASK_WRITE_ACTIONS = {
    "创建": ("创建任务", "新增任务", "建任务"),
    "完成": ("标记完成", "完成任务", "设为完成"),
    "指派": ("指派", "分配给", "转给"),
    "更新": ("更新任务", "修改任务", "变更状态"),
}
CASE_CREATE_KEYWORDS = ("创建案件", "新建案件", "新增案件", "立案")
MATERIAL_UPLOAD_KEYWORDS = ("上传材料", "上传卷宗", "补充材料", "补件")
MATERIAL_STATUS_KEYWORDS = ("材料状态", "上传进度", "批次状态", "解析进度", "OCR状态")
MATERIAL_VALIDATE_KEYWORDS = ("材料分类", "卷宗分类", "类别校验", "缺什么材料", "缺少材料")
DEADLINE_KEYWORDS = ("司法时效", "诉讼时效", "到期", "期限", "红黄绿")
EVIDENCE_KEYWORDS = ("证据原文", "引用原文", "角标", "卷宗原文", "证据追溯", "本案证据")
CASELAW_KEYWORDS = (
    "相似案件",
    "类似案件",
    "相似案例",
    "类似案例",
    "类案",
    "判例",
    "法院怎么判",
    "通常怎么判",
    "裁判观点",
)
GRAPH_KEYWORDS = ("知识图谱", "关系图", "资金流", "企业穿透", "关联关系", "白手套")
AUDIT_DRILLDOWN_KEYWORDS = ("估值", "债权", "保证人", "担保", "偿债", "审计结论", "详细分析")
GREETING_KEYWORDS = ("你好", "您好", "谢谢", "在吗", "你是谁", "帮助")


def extract_case_id(text: str) -> int | None:
    patterns = (
        r"案件[编号\s]*(\d+)",
        r"案件\s*(\d+)",
        r"case[_\s]*id\s*[=:：]\s*(\d+)",
        r"分析\s*(\d+)",
        r"审计\s*(\d+)",
        r"^\s*(\d+)\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _task_target_id(query: str) -> str:
    match = re.search(r"(?:任务|task)[编号#\s:]*(\d+)", query, re.IGNORECASE)
    return match.group(1) if match else ""


def _decision(
    business_line: str,
    capability: str,
    *,
    confidence: float,
    source: str,
    case_id: int | None = None,
    action: str = "",
    target_id: str = "",
    needs_clarification: bool = False,
    clarification_question: str = "",
) -> RouteDecisionModel:
    return RouteDecisionModel(
        route_version=ROUTE_VERSION,
        business_line=business_line,
        capability=capability,
        confidence=confidence,
        source=source,
        case_id=case_id,
        action=action,
        target_id=target_id,
        needs_clarification=needs_clarification,
        clarification_question=clarification_question,
    )


def _report_exists(state: AuditGraphState) -> bool:
    return bool(
        state.get("final_report_ref")
        or state.get("report_part_b_ref")
        or state.get("report_part_a_ref")
        or (state.get("report_section_refs") or {})
    )


def is_explicit_case_create_request(state: AuditGraphState | dict) -> bool:
    """Return whether pre-route tenancy may open an unbound creation thread."""
    if explicit_write_capability(state) == "case.create":
        return True
    query = str(state.get("query") or "")
    return any(keyword in query for keyword in CASE_CREATE_KEYWORDS)


def _case_create_decision(state: AuditGraphState, *, source: str) -> RouteDecisionModel:
    _, missing = resolve_case_create_command(state)
    try:
        bound_case_id = int(state.get("current_case_id") or 0)
    except (TypeError, ValueError):
        bound_case_id = 0
    if bound_case_id > 0:
        return _decision(
            "operator",
            "case.create",
            confidence=0.99,
            source=source,
            case_id=bound_case_id,
            action="create",
            needs_clarification=True,
            clarification_question="当前会话已绑定案件，请使用新的未绑定会话创建案件。",
        )
    return _decision(
        "operator",
        "case.create",
        confidence=0.98 if not missing else 0.80,
        source=source,
        action="create",
        needs_clarification=bool(missing),
        clarification_question=write_clarification("case.create", missing) if missing else "",
    )


def _task_write_decision(
    state: AuditGraphState,
    *,
    action: str,
    source: str,
) -> RouteDecisionModel:
    command = command_dict(state)
    raw_target = command.get("task_id") or _task_target_id(str(state.get("query") or ""))
    provisional = {"action": action, "target_id": str(raw_target or "")}
    _, missing = resolve_task_write_command(state, provisional)
    return _decision(
        "supervision",
        "task.write",
        confidence=0.98 if not missing else 0.80,
        source=source,
        case_id=extract_case_id(str(state.get("query") or "")) or state.get("current_case_id") or None,
        action=action,
        target_id=str(raw_target or ""),
        needs_clarification=bool(missing),
        clarification_question=write_clarification("task.write", missing) if missing else "",
    )


def _rule_route(state: AuditGraphState) -> RouteDecisionModel | None:
    query = (state.get("query") or "").strip()
    case_id = extract_case_id(query) or state.get("current_case_id") or None
    explicit_write = explicit_write_capability(state)

    if state.get("uploaded_files"):
        return _decision("operator", "material.upload", confidence=1.0, source="context", case_id=case_id, action="upload")

    if explicit_write == "case.create":
        return _case_create_decision(state, source="context")

    if explicit_write == "material.upload":
        return _decision(
            "operator",
            "material.upload",
            confidence=0.80,
            source="context",
            case_id=case_id,
            action="upload",
            needs_clarification=True,
            clarification_question="请上传要处理的卷宗文件。",
        )

    if explicit_write == "task.write":
        raw_action = str(command_dict(state).get("task_action") or "")
        return _task_write_decision(state, action=raw_action, source="context")

    if any(keyword in query for keyword in REVIEW_KEYWORDS):
        return _decision("supervision", "recovery.review", confidence=0.99, source="rule", case_id=case_id, action="review")

    # Specific correction intent must win over generic query words such as "查一下".
    if (
        not any(phrase in query for phrase in NEGATED_RE_AUDIT_PHRASES)
        and any(keyword in query for keyword in RE_AUDIT_KEYWORDS)
        and any(marker in query for marker in RE_AUDIT_OBJECTS)
    ):
        return _decision("audit_analysis", "audit.reaudit", confidence=0.99, source="rule", case_id=case_id, action="reaudit")

    if not any(phrase in query for phrase in NEGATED_FULL_AUDIT_PHRASES) and any(
        keyword in query for keyword in FULL_AUDIT_KEYWORDS
    ):
        return _decision("audit_analysis", "audit.full", confidence=0.99, source="rule", case_id=case_id, action="generate")

    for action, phrases in TASK_WRITE_ACTIONS.items():
        if any(phrase in query for phrase in phrases):
            return _task_write_decision(state, action=action, source="rule")

    if any(keyword in query for keyword in TASK_KEYWORDS):
        return _decision("supervision", "task.query", confidence=0.95, source="rule", case_id=case_id, action="query")

    if any(keyword in query for keyword in CASE_CREATE_KEYWORDS):
        return _case_create_decision(state, source="rule")

    if any(keyword in query for keyword in MATERIAL_UPLOAD_KEYWORDS):
        return _decision(
            "operator",
            "material.upload",
            confidence=0.90,
            source="rule",
            case_id=case_id,
            action="upload",
            needs_clarification=not bool(state.get("uploaded_files")),
            clarification_question="请上传要处理的卷宗文件。" if not state.get("uploaded_files") else "",
        )

    if any(keyword in query for keyword in MATERIAL_STATUS_KEYWORDS):
        return _decision("operator", "material.status", confidence=0.96, source="rule", case_id=case_id, action="query")

    if any(keyword in query for keyword in MATERIAL_VALIDATE_KEYWORDS):
        return _decision("operator", "material.validate", confidence=0.96, source="rule", case_id=case_id, action="validate")

    if any(keyword in query for keyword in DEADLINE_KEYWORDS):
        return _decision("supervision", "deadline.query", confidence=0.94, source="rule", case_id=case_id, action="query")

    if any(keyword in query for keyword in CASELAW_KEYWORDS):
        return _decision("audit_analysis", "caselaw.search", confidence=0.96, source="rule", case_id=case_id, action="query")

    if any(keyword in query for keyword in EVIDENCE_KEYWORDS):
        return _decision("audit_analysis", "evidence.resolve", confidence=0.96, source="rule", case_id=case_id, action="query")

    if any(keyword in query for keyword in GRAPH_KEYWORDS):
        return _decision("audit_analysis", "graph.query", confidence=0.96, source="rule", case_id=case_id, action="query")

    if any(keyword in query for keyword in AUDIT_DRILLDOWN_KEYWORDS):
        return _decision("audit_analysis", "audit.drilldown", confidence=0.90, source="rule", case_id=case_id, action="query")

    # A case number supplies context but does not by itself authorize an expensive full audit.
    if extract_case_id(query) is not None:
        return _decision("operator", "case.profile", confidence=0.90, source="rule", case_id=case_id, action="query")

    if query in GREETING_KEYWORDS or any(query.startswith(keyword) for keyword in GREETING_KEYWORDS):
        return _decision("common", "common.general", confidence=0.99, source="rule", case_id=case_id, action="respond")

    if _report_exists(state):
        return _decision("audit_analysis", "audit.drilldown", confidence=0.86, source="context", case_id=case_id, action="query")

    return None


def _normalize_model_decision(decision: RouteDecisionModel, state: AuditGraphState) -> RouteDecisionModel:
    decision.route_version = ROUTE_VERSION
    decision.source = "model"
    decision.case_id = decision.case_id or extract_case_id(state.get("query", "")) or state.get("current_case_id") or None

    context_free_capabilities = {"case.create", "caselaw.search", "common.general", "clarify"}
    if decision.confidence < 0.85 and not decision.case_id and decision.capability not in context_free_capabilities:
        decision.needs_clarification = True
        if not decision.clarification_question:
            decision.clarification_question = "请先说明要处理的案件编号和具体业务。"

    if decision.capability == "task.write" and decision.action in {"完成", "指派", "更新", "complete", "assign", "update"}:
        if not decision.target_id:
            decision.needs_clarification = True
            decision.clarification_question = decision.clarification_question or "请提供要操作的任务编号。"
    spec = get_capability_spec(decision.capability)
    if spec is not None and spec.access_mode == "write":
        if explicit_write_capability(state) != decision.capability:
            decision.needs_clarification = True
            decision.clarification_question = "写操作需要明确命令参数，请确认操作对象和必填字段。"
    return RouteDecisionModel.model_validate(decision.model_dump())


def _positive_case_id(value: object) -> int | None:
    try:
        case_id = int(value or 0)
    except (TypeError, ValueError):
        return None
    return case_id if case_id > 0 else None


def _apply_registered_requirements(
    decision: RouteDecisionModel,
    state: AuditGraphState,
) -> RouteDecisionModel:
    """Enforce capability context requirements after query/thread context is merged."""
    decision.case_id = (
        _positive_case_id(decision.case_id)
        or _positive_case_id(extract_case_id(state.get("query", "")))
        or _positive_case_id(state.get("current_case_id"))
    )
    spec = get_capability_spec(decision.capability)
    if spec is not None and spec.requires_case and decision.case_id is None:
        decision.needs_clarification = True
        decision.clarification_question = "请先提供要处理的案件编号。"
    return RouteDecisionModel.model_validate(decision.model_dump())


def resolve_route_decision(state: AuditGraphState) -> RouteDecisionModel:
    rule_decision = _rule_route(state)
    if rule_decision is not None:
        return _apply_registered_requirements(rule_decision, state)

    query = (state.get("query") or "").strip()
    try:
        llm = build_router_llm()
        if has_api_key(llm):
            structured_llm = llm.with_structured_output(RouteDecisionModel)
            context = {
                "query": query,
                "current_case_id": state.get("current_case_id") or None,
                "report_exists": _report_exists(state),
                "memory_context": str(state.get("memory_context") or "")[-1200:],
            }
            response = structured_llm.invoke(
                [
                    SystemMessage(content=f"{load_prompt('router.txt')}\n\n{render_route_catalog()}"),
                    HumanMessage(content=json.dumps(context, ensure_ascii=False)),
                ]
            )
            decision = response if isinstance(response, RouteDecisionModel) else RouteDecisionModel.model_validate(response)
            return _apply_registered_requirements(_normalize_model_decision(decision, state), state)
        LOGGER.warning("router_llm_no_api_key; route=clarify")
    except Exception as exc:
        LOGGER.exception("router_llm_failed error=%s; route=clarify", exc)

    return _apply_registered_requirements(
        _decision(
            "common",
            "clarify",
            confidence=0.0,
            source="fallback",
            case_id=extract_case_id(query) or state.get("current_case_id") or None,
            needs_clarification=True,
            clarification_question="请说明您要处理的是案件材料、审计分析还是任务督办。",
        ),
        state,
    )


def route_intent(state: AuditGraphState) -> Intent:
    """Compatibility wrapper for callers that still consume the four-way intent."""
    return resolve_route_decision(state).intent


def _coerce_intent(content: str) -> Intent | None:
    """Legacy raw-output parser retained for external callers during migration."""
    text = content.strip()
    if not text:
        return None
    fenced = re.sub(r"^```(?:json)?|```$", "", text, flags=re.IGNORECASE).strip()
    try:
        parsed = json.loads(fenced)
        if isinstance(parsed, dict):
            candidate = str(parsed.get("intent", "")).strip().lower()
            if candidate in VALID_INTENTS:
                return candidate  # type: ignore[return-value]
    except (json.JSONDecodeError, ValueError):
        pass
    lowered = fenced.lower()
    for intent in VALID_INTENTS:
        if intent in lowered:
            return intent
    return None

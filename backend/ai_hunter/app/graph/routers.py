"""Annual-audit intent routing with deterministic rules and model fallback."""

from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from .capabilities import CAPABILITY_IDS, get_capability_spec, render_route_catalog
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
ROUTE_VERSION = "annual-v1"
VALID_INTENTS: tuple[Intent, ...] = ("re_audit", "full_audit", "drilldown")

PROJECT_CREATE_KEYWORDS = (
    "创建年审项目",
    "新建年审项目",
    "创建审计项目",
    "年审立项",
)
FULL_AUDIT_KEYWORDS = (
    "执行完整年审",
    "执行完整年度审计",
    "执行年度审计",
    "完整年度审计",
    "执行年审",
    "完整年审",
    "全面年审",
    "全面年度审计",
    "全面检查",
    "生成年审报告",
    "生成年度审计报告",
    "生成全面年审报告",
    "年审报告初稿",
    "年度审计报告初稿",
    "生成审计报告草稿",
    "出具审计报告",
    "生成完整工作底稿",
    "生成工作底稿",
    "生成底稿",
)
REAUDIT_KEYWORDS = ("重新执行年审", "重新生成报告", "重跑年审", "更正后重跑", "重新审计")
REAUDIT_OBJECTS = ("报告", "底稿", "结论", "数据", "调整", "错报", "年审")
AUDIT_REVIEW_ISSUE_KEYWORDS = (
    "有问题",
    "存在问题",
    "不对",
    "不准确",
    "不正确",
    "错误",
    "错了",
    "不一致",
    "遗漏",
    "缺失",
    "需要调整",
    "需要补充",
    "补充资料",
    "继续审计",
    "继续分析",
)
AUDIT_REVIEW_OK_KEYWORDS = (
    "没有问题",
    "没问题",
    "无问题",
    "确认无误",
    "结果正确",
    "没有发现问题",
)
ATTACHMENT_CONFIRM_KEYWORDS = (
    "生成附件",
    "生成成果",
    "生成报告、报表",
    "生成报告和报表",
    "生成报表和附注",
    "生成年度审计报告",
    "生成审计报告",
    "生成财务报表",
    "生成附注",
    "生成工作底稿",
    "生成管理建议书",
    "生成函证",
    "重新生成附件",
    "重新生成",
    "可以生成",
    "确认生成",
    "开始生成",
    "好的",
    "好，生成",
    "是的",
    "是，生成",
)
MATERIAL_UPLOAD_KEYWORDS = ("上传审计资料", "上传财务资料", "补充审计资料", "补资料")
MATERIAL_STATUS_KEYWORDS = ("资料状态", "上传进度", "解析进度", "资料处理进度")
MATERIAL_VALIDATE_KEYWORDS = ("资料完整性", "还缺什么资料", "缺少什么资料", "资料清单")
EVIDENCE_KEYWORDS = ("证据原文", "引用出处", "证据追溯", "底稿依据", "查看原文")
GRAPH_KEYWORDS = (
    "关系图谱",
    "主体关系",
    "交易链路",
    "关联方关系",
    "账户关系",
    "资金流向",
    "对手方关系",
)
DRILLDOWN_KEYWORDS = (
    "收入",
    "应收",
    "账龄",
    "函证",
    "货币资金",
    "银行",
    "现金",
    "流水",
    "截止性",
    "科目余额",
    "总账",
    "明细账",
    "凭证",
    "重要性",
    "审计风险",
    "复核",
    "底稿",
)
TASK_KEYWORDS = ("任务", "审计程序", "待办", "督办")
WORKFLOW_KEYWORDS = (
    "全部业务流程",
    "完整业务流程",
    "完整流程",
    "全流程",
    "端到端",
    "业务闭环",
    "最终产出",
    "最终成果",
    "最终交付",
    "交付物",
    "应该有哪些产出",
    "应该得到什么",
    "年审最终要",
    "年审最终应该",
)
TASK_WRITE_ACTIONS = {
    "create": ("创建任务", "新增任务", "新建任务"),
    "complete": ("标记完成", "完成任务", "设为完成"),
    "assign": ("指派", "分配给", "转给"),
    "update": ("更新任务", "修改任务", "变更状态"),
}
GREETING_KEYWORDS = ("你好", "您好", "谢谢", "在吗", "帮助")


def extract_case_id(text: str) -> int | None:
    """Extract the compatibility project id carried in existing case_id fields."""

    patterns = (
        r"年审项目[编号\s#:]*(\d+)",
        r"审计项目[编号\s#:]*(\d+)",
        r"engagement[_\s]*id\s*[=:：]?\s*(\d+)",
        r"项目[编号\s#:]*(\d+)",
        r"case[_\s]*id\s*[=:：]?\s*(\d+)",
        r"^\s*(\d+)\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, str(text or ""), re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _positive_case_id(value: object) -> int | None:
    try:
        case_id = int(value or 0)
    except (TypeError, ValueError):
        return None
    return case_id if case_id > 0 else None


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
        or state.get("final_report")
        or state.get("final_report_summary")
    )


def _review_confirmation_route(state: AuditGraphState) -> RouteDecisionModel | None:
    """Resolve the two human confirmations following a full audit."""

    stage = str(state.get("audit_review_stage") or "")
    query = str(state.get("query") or "").strip()
    case_id = _positive_case_id(state.get("current_case_id"))
    if not query or not case_id:
        return None

    # A restart can clear the in-memory graph checkpoint while the browser is
    # still showing an already generated attachment package.  The visible
    # “重新生成附件” action must remain usable in that situation; otherwise a
    # user clicks a supplied button and receives a generic clarification.
    if any(keyword in query for keyword in ("重新生成附件", "重新生成交付附件")):
        return _decision(
            "audit_analysis",
            "audit.full",
            confidence=1.0,
            source="context",
            case_id=case_id,
            action="prepare_attachments",
        )

    if not stage:
        return None

    if stage == "awaiting_result_review":
        # Check explicit approval first so "没有问题" is never mistaken for
        # the substring "有问题".
        if any(keyword in query for keyword in AUDIT_REVIEW_OK_KEYWORDS):
            return _decision(
                "common",
                "common.general",
                confidence=1.0,
                source="context",
                case_id=case_id,
                action="confirm_audit_result",
                needs_clarification=True,
                clarification_question=(
                    "已记录：当前审计结果没有问题。\n\n"
                    "是否基于当前已激活的模板版本生成年度审计交付附件？\n"
                    "可生成的核心交付附件包括年度审计报告、年度审计财务报表和财务报表附注；\n"
                    "管理建议书属于按需生成的可选附件；\n"
                    "每个附件严格沿用对应已激活模板的文件格式和版式（模板是 .docx/.xlsx/.xls/.md/.pdf 等，\n"
                    "交付就保持该格式），并只写入模板定义的字段、段落或表格位置，不追加通用结果附页。\n\n"
                    "审计工作底稿、函证属于过程资料，不会随标准年审交付包自动生成。\n\n"
                    "请回复“确认生成”或“暂不生成”。"
                ),
            )
        if any(keyword in query for keyword in AUDIT_REVIEW_ISSUE_KEYWORDS):
            return _decision(
                "audit_analysis",
                "audit.reaudit",
                confidence=1.0,
                source="context",
                case_id=case_id,
                action="reaudit",
            )

    if stage == "awaiting_attachment_generation_confirmation":
        if any(keyword in query for keyword in ATTACHMENT_CONFIRM_KEYWORDS):
            return _decision(
                "audit_analysis",
                "audit.full",
                confidence=1.0,
                source="context",
                case_id=case_id,
                action="generate_attachments",
            )
        if any(keyword in query for keyword in ("暂不生成", "不生成", "先不", "取消")):
            return _decision(
                "common",
                "common.general",
                confidence=1.0,
                source="context",
                case_id=case_id,
                action="skip_attachments",
                needs_clarification=True,
                clarification_question="好的，暂不生成附件。后续如需生成，请回复“确认生成附件”。",
            )

    if stage in {"awaiting_artifact_confirmation", "attachments_skipped", "attachments_generated"}:
        if any(keyword in query for keyword in ATTACHMENT_CONFIRM_KEYWORDS):
            return _decision(
                "audit_analysis",
                "audit.full",
                confidence=1.0,
                source="context",
                case_id=case_id,
                action="prepare_attachments",
            )
        if any(keyword in query for keyword in ("暂不生成", "不生成", "先不", "取消")):
            return _decision(
                "common",
                "common.general",
                confidence=1.0,
                source="context",
                case_id=case_id,
                action="skip_attachments",
                needs_clarification=True,
                clarification_question="好的，暂不生成附件。后续如需生成，请回复“确认生成附件”。",
            )
    return None


def is_explicit_case_create_request(state: AuditGraphState | dict) -> bool:
    if explicit_write_capability(state) == "case.create":
        return True
    query = str(state.get("query") or "")
    return any(keyword in query for keyword in PROJECT_CREATE_KEYWORDS)


def _case_create_decision(state: AuditGraphState, *, source: str) -> RouteDecisionModel:
    _, missing = resolve_case_create_command(state)
    bound_case_id = _positive_case_id(state.get("current_case_id"))
    if bound_case_id:
        return _decision(
            "operator",
            "case.create",
            confidence=0.99,
            source=source,
            case_id=bound_case_id,
            action="create",
            needs_clarification=True,
            clarification_question="当前会话已绑定年审项目，请使用新的未绑定会话创建项目。",
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


def _task_target_id(query: str) -> str:
    match = re.search(r"(?:任务|task)[编号#\s:]*(\d+)", query, re.IGNORECASE)
    return match.group(1) if match else ""


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
        case_id=extract_case_id(str(state.get("query") or ""))
        or _positive_case_id(state.get("current_case_id")),
        action=action,
        target_id=str(raw_target or ""),
        needs_clarification=bool(missing),
        clarification_question=write_clarification("task.write", missing) if missing else "",
    )


def _rule_route(state: AuditGraphState) -> RouteDecisionModel | None:
    query = str(state.get("query") or "").strip()
    case_id = extract_case_id(query) or _positive_case_id(state.get("current_case_id"))
    explicit_write = explicit_write_capability(state)

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
            clarification_question="请上传需要处理的年审资料。",
        )
    if explicit_write == "task.write":
        return _task_write_decision(
            state,
            action=str(command_dict(state).get("task_action") or ""),
            source="context",
        )
    workflow_route = _review_confirmation_route(state)
    if workflow_route is not None:
        return workflow_route
    if any(keyword in query for keyword in REAUDIT_KEYWORDS) and any(marker in query for marker in REAUDIT_OBJECTS):
        return _decision("audit_analysis", "audit.reaudit", confidence=0.99, source="rule", case_id=case_id, action="reaudit")
    if any(keyword in query for keyword in FULL_AUDIT_KEYWORDS):
        return _decision("audit_analysis", "audit.full", confidence=0.99, source="rule", case_id=case_id, action="generate")
    if any(keyword in query for keyword in WORKFLOW_KEYWORDS):
        return _decision("audit_analysis", "audit.workflow", confidence=0.99, source="rule", case_id=case_id, action="guide")
    if state.get("uploaded_files"):
        return _decision("operator", "material.upload", confidence=1.0, source="context", case_id=case_id, action="upload")
    for action, phrases in TASK_WRITE_ACTIONS.items():
        if any(phrase in query for phrase in phrases):
            return _task_write_decision(state, action=action, source="rule")
    if any(keyword in query for keyword in TASK_KEYWORDS):
        return _decision("supervision", "task.query", confidence=0.95, source="rule", case_id=case_id, action="query")
    if any(keyword in query for keyword in PROJECT_CREATE_KEYWORDS):
        return _case_create_decision(state, source="rule")
    if any(keyword in query for keyword in MATERIAL_UPLOAD_KEYWORDS):
        return _decision(
            "operator",
            "material.upload",
            confidence=0.96,
            source="rule",
            case_id=case_id,
            action="upload",
            needs_clarification=not bool(state.get("uploaded_files")),
            clarification_question="请上传需要处理的年审资料。" if not state.get("uploaded_files") else "",
        )
    if any(keyword in query for keyword in MATERIAL_STATUS_KEYWORDS):
        return _decision("operator", "material.status", confidence=0.96, source="rule", case_id=case_id, action="query")
    if any(keyword in query for keyword in MATERIAL_VALIDATE_KEYWORDS):
        return _decision("operator", "material.validate", confidence=0.96, source="rule", case_id=case_id, action="validate")
    if any(keyword in query for keyword in EVIDENCE_KEYWORDS):
        return _decision("audit_analysis", "evidence.resolve", confidence=0.98, source="rule", case_id=case_id, action="query")
    if any(keyword in query for keyword in GRAPH_KEYWORDS):
        return _decision("audit_analysis", "graph.query", confidence=0.98, source="rule", case_id=case_id, action="query")
    if any(keyword in query for keyword in DRILLDOWN_KEYWORDS):
        return _decision("audit_analysis", "audit.drilldown", confidence=0.94, source="rule", case_id=case_id, action="query")
    if extract_case_id(query) is not None:
        return _decision("operator", "case.profile", confidence=0.94, source="rule", case_id=case_id, action="query")
    if query in GREETING_KEYWORDS or any(query.startswith(keyword) for keyword in GREETING_KEYWORDS):
        return _decision("common", "common.general", confidence=0.99, source="rule", case_id=case_id, action="respond")
    if _report_exists(state):
        return _decision("audit_analysis", "audit.drilldown", confidence=0.86, source="context", case_id=case_id, action="query")
    return None


def _apply_requirements(decision: RouteDecisionModel, state: AuditGraphState) -> RouteDecisionModel:
    decision.route_version = ROUTE_VERSION
    decision.case_id = (
        _positive_case_id(decision.case_id)
        or _positive_case_id(extract_case_id(str(state.get("query") or "")))
        or _positive_case_id(state.get("current_case_id"))
    )
    spec = get_capability_spec(decision.capability)
    if spec is not None and spec.requires_case and decision.case_id is None:
        decision.needs_clarification = True
        decision.clarification_question = "请先提供要处理的年审项目编号。"
    if spec is not None and spec.access_mode == "write":
        explicit = explicit_write_capability(state)
        if decision.source == "model" and explicit != decision.capability:
            decision.needs_clarification = True
            decision.clarification_question = "写操作需要明确命令参数，请确认项目和必填字段。"
    return RouteDecisionModel.model_validate(decision.model_dump())


def _enforce_annual_capability(
    decision: RouteDecisionModel,
    state: AuditGraphState,
) -> RouteDecisionModel:
    if decision.capability in CAPABILITY_IDS:
        return decision
    return _decision(
        "common",
        "clarify",
        confidence=1.0,
        source="fallback",
        case_id=_positive_case_id(state.get("current_case_id")),
        needs_clarification=True,
        clarification_question="请说明要处理的年审资料、审计循环、证据、图谱、底稿、报告或任务。",
    )


def resolve_route_decision(state: AuditGraphState) -> RouteDecisionModel:
    rule_decision = _rule_route(state)
    if rule_decision is not None:
        return _apply_requirements(rule_decision, state)

    query = str(state.get("query") or "").strip()
    try:
        llm = build_router_llm()
        if has_api_key(llm):
            structured_llm = llm.with_structured_output(RouteDecisionModel)
            context = {
                "query": query,
                "current_project_id": state.get("current_case_id") or None,
                "report_exists": _report_exists(state),
                "memory_context": str(state.get("memory_context") or "")[-1200:],
            }
            response = structured_llm.invoke(
                [
                    SystemMessage(
                        content=f"{load_prompt('annual_audit_router.txt')}\n\n{render_route_catalog()}"
                    ),
                    HumanMessage(content=json.dumps(context, ensure_ascii=False)),
                ]
            )
            decision = response if isinstance(response, RouteDecisionModel) else RouteDecisionModel.model_validate(response)
            decision.source = "model"
            return _apply_requirements(decision, state)
        LOGGER.warning("annual_router_llm_no_api_key; route=clarify")
    except Exception as exc:
        LOGGER.exception("annual_router_llm_failed error=%s; route=clarify", exc)

    return _apply_requirements(
        _decision(
            "common",
            "clarify",
            confidence=0.0,
            source="fallback",
            case_id=extract_case_id(query) or _positive_case_id(state.get("current_case_id")),
            needs_clarification=True,
            clarification_question="请说明要处理的年审项目、资料、审计循环、证据、底稿、报告或任务。",
        ),
        state,
    )


def route_intent(state: AuditGraphState) -> Intent:
    return resolve_route_decision(state).intent


def _coerce_intent(content: str) -> Intent | None:
    text = str(content or "").strip().lower()
    for intent in VALID_INTENTS:
        if intent in text:
            return intent
    return None

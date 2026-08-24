"""Chat routes for normal JSON invocation and optional SSE streaming progress."""

from __future__ import annotations

import datetime
import hashlib
import itertools
import json
import logging
import asyncio
import re
from typing import Any, AsyncIterator

import anyio
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import iterate_in_threadpool

from ..graph.context_loader import (
    resolve_aggregated_text,
    resolve_citation_coverage,
    resolve_final_report,
    resolve_reconciliation_items,
    resolve_trace_items,
    resolve_unresolved_graph_items,
)
from ..graph.capabilities import capability_permission_modules
from ..graph.json_utils import json_dumps_safe
from ..graph.main import build_audit_orchestrator_graph
from ..auth.identity import Identity
from ..auth.permissions import has_module, report_section_code_for_id, require_any_module, require_module, visible_report_sections
from ..auth.report_filter import filter_report_text_by_sections
from ..auth.tenancy import get_tenancy_service, require_case_access, require_thread_access, require_thread_manage
from ...annual_audit.storage import mysql_connection


def _any_section_id_from_node(node_name: str) -> str | None:
    """Annual reports are generated as one artifact rather than legacy section nodes."""
    return None


def _any_section_meta(section_id: str) -> dict:
    return {}


_REASONING_TAG_PATTERN = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)
_REASONING_OPEN_TAG = "<think>"
_REASONING_CLOSE_TAG = "</think>"


def _split_tagged_reasoning(text: str) -> list[tuple[str, str]]:
    """Split provider-emitted complete <think> blocks from visible content."""
    if not isinstance(text, str) or not text:
        return []
    parts: list[tuple[str, str]] = []
    cursor = 0
    for match in _REASONING_TAG_PATTERN.finditer(text):
        before = text[cursor:match.start()]
        if before:
            parts.append(("content", before))
        reasoning = match.group(1)
        if reasoning:
            parts.append(("reasoning", reasoning))
        cursor = match.end()
    tail = text[cursor:]
    if tail:
        parts.append(("content", tail))
    return parts


def _tag_prefix_suffix_len(text: str, tag: str) -> int:
    lower = text.lower()
    max_len = min(len(lower), len(tag) - 1)
    for size in range(max_len, 0, -1):
        if tag.startswith(lower[-size:]):
            return size
    return 0


def _split_tagged_reasoning_stream(text: str, state: dict[str, str]) -> list[tuple[str, str]]:
    """Split <think> blocks even when provider chunks split the tags."""
    if not isinstance(text, str) or not text:
        return []
    mode = state.get("mode", "content")
    data = state.get("buffer", "") + text
    state["buffer"] = ""
    parts: list[tuple[str, str]] = []

    while data:
        lower = data.lower()
        if mode == "content":
            idx = lower.find(_REASONING_OPEN_TAG)
            if idx >= 0:
                before = data[:idx]
                if before:
                    parts.append(("content", before))
                data = data[idx + len(_REASONING_OPEN_TAG):]
                mode = "reasoning"
                continue
            hold = _tag_prefix_suffix_len(data, _REASONING_OPEN_TAG)
            visible = data[:-hold] if hold else data
            if visible:
                parts.append(("content", visible))
            state["buffer"] = data[-hold:] if hold else ""
            break

        idx = lower.find(_REASONING_CLOSE_TAG)
        if idx >= 0:
            reasoning = data[:idx]
            if reasoning:
                parts.append(("reasoning", reasoning))
            data = data[idx + len(_REASONING_CLOSE_TAG):]
            mode = "content"
            continue
        hold = _tag_prefix_suffix_len(data, _REASONING_CLOSE_TAG)
        reasoning = data[:-hold] if hold else data
        if reasoning:
            parts.append(("reasoning", reasoning))
        state["buffer"] = data[-hold:] if hold else ""
        break

    state["mode"] = mode
    return parts


def _flush_tagged_reasoning_stream(state: dict[str, str]) -> list[tuple[str, str]]:
    buffered = state.get("buffer", "")
    mode = state.get("mode", "content")
    state["buffer"] = ""
    state["mode"] = "content"
    if not buffered:
        return []
    lower = buffered.lower()
    if mode == "content" and _REASONING_OPEN_TAG.startswith(lower):
        return []
    if mode == "reasoning" and _REASONING_CLOSE_TAG.startswith(lower):
        return []
    return [(mode, buffered)]


from ..graph.schemas import (
    CitationCoverageModel,
    ReconciliationLedgerItemModel,
    RouteDecisionModel,
    TraceItemModel,
    UnresolvedClaimItemModel,
    UnresolvedRelationItemModel,
    WriteCommandModel,
)
from ..graph.routers import extract_case_id, is_explicit_case_create_request
from ..graph.state import FileItem
from ..logging_utils import build_request_logger, preview_text
from ..repositories import get_conversation_message_repo
from ..services.conversation_service import get_conversation_service
from ..settings import get_settings
from ..utils.pg_lock import thread_advisory_lock
from ._upload_helpers import (
    resolve_engagement_entity,
    resolve_upload_batch_id,
    to_file_item,
)


router = APIRouter(prefix="/chat", tags=["chat"])
graph = build_audit_orchestrator_graph()
LOGGER = logging.getLogger(__name__)

CHAT_INVOKE_MODULES = ("report", "drilldown", "materials", "tasks", "corrections", "graph")
INTENT_MODULES = {
    "full_audit": "report",
    "drilldown": "drilldown",
    "re_audit": "corrections",
}
CAPABILITY_MODULES = capability_permission_modules()

# Lazy-initialized async graph bound to AsyncPostgresSaver.
# astream_events() requires an async checkpointer; the sync PostgresSaver
# used by ``graph`` does not implement aget_tuple, so we keep a separate
# compiled graph for streaming paths.
_async_graph = None
_async_graph_lock = asyncio.Lock()


async def _ensure_async_graph():
    """Lazy-load the async graph with double-checked locking."""
    global _async_graph
    if _async_graph is not None:
        return _async_graph

    async with _async_graph_lock:
        if _async_graph is not None:
            return _async_graph
        from ..graph.checkpointer import get_async_checkpointer

        async_cp = await get_async_checkpointer()
        _async_graph = build_audit_orchestrator_graph(checkpointer=async_cp)
        LOGGER.info("async_graph_initialized")
    return _async_graph


def _resolve_cached_turn(thread_id: str, client_turn_id: str) -> dict[str, Any] | None:
    """Return the persisted response state for an already processed client turn."""
    if not client_turn_id:
        return None
    turn_id = hashlib.sha256(
        f"{thread_id}:{client_turn_id}".encode()
    ).hexdigest()[:16]
    repo = get_conversation_message_repo()
    for row in repo.get_messages(thread_id):
        if row["turn_id"] == f"{turn_id}_assistant":
            graph_context = row.get("graph_context")
            cached_state = dict(graph_context) if isinstance(graph_context, dict) else {}
            cached_state.update(
                {
                    "current_case_id": int(row.get("case_id") or 0),
                    "final_report_ref": str(row.get("final_report_ref") or ""),
                    "final_report": str(row.get("content") or ""),
                    "intent": str(row.get("intent") or ""),
                    "assistant_message_id": str(row.get("turn_id") or ""),
                }
            )
            return cached_state
    return None


def _normalize_cached_turn(payload: ChatRequest, cached_state: dict[str, Any]) -> dict[str, Any]:
    """Fill tenant-bound case context for historical cache rows that stored case_id=0."""
    normalized = dict(cached_state)
    if int(normalized.get("current_case_id") or 0) <= 0:
        normalized["current_case_id"] = _cached_case_id(payload)
    return normalized


async def _cached_sse_response(
    payload: ChatRequest,
    cached_state: dict[str, Any],
    visible_section_codes: set[str] | None = None,
) -> AsyncIterator[str]:
    """Yield a minimal SSE stream for a cached (idempotent) turn."""
    current_case_id = int(cached_state.get("current_case_id") or 0)
    yield _sse_event(
        "start",
        {
            "thread_id": payload.thread_id,
            "query": payload.query,
            "current_case_id": current_case_id,
            "uploaded_file_count": len(payload.uploaded_files),
            "cached": True,
        },
    )
    yield _sse_event(
        "final",
        _build_final_response(payload, cached_state, visible_section_codes).model_dump(),
    )
    yield _sse_event("done", {"thread_id": payload.thread_id})


class ChatRequest(BaseModel):
    thread_id: str = Field(description="会话线程 ID。多轮对话请保持同一个 thread_id。")
    query: str = Field(default="", description="用户输入内容。")
    current_case_id: int = Field(default=0, description="当前年审项目 ID；未知时可传 0。")
    current_entity_id: int = Field(default=0, description="被审计单位实体 ID；未知时可传 0。")
    current_entity_name: str = Field(default="", description="被审计单位名称；为空时由项目主数据解析。")
    doc_category: str = Field(default="", description="可选，本批上传审计资料类别编码。")
    batch_name: str = Field(default="", description="可选，本批上传批次名称。")
    upload_batch_id: str = Field(default="", description="可选，本批上传批次 ID。")
    operator_id: str = Field(default="", description="可选，操作员 ID。")
    operator_name: str = Field(default="", description="可选，操作员名称。")
    write_command: WriteCommandModel | None = Field(
        default=None,
        description=(
            "确定性写命令槽位。创建年审项目、任务写操作建议由前端传入；"
            "身份和租户字段不在此模型中，由服务端鉴权注入。"
        ),
    )
    uploaded_files: list[FileItem] = Field(
        default_factory=list,
        description=(
            "已归一化的文件列表。适合前端已经拿到文件 URL、文本内容或 base64 内容时直接挂到聊天请求里。"
            " 若前端要上传原始二进制文件，请改走 /files/upload-and-ingest。"
        ),
    )
    stream: bool = Field(
        default=True,
        description=(
            "是否走 SSE 流式返回。默认 true（流式）。"
            " 如需一次性 JSON 返回，显式传 false。"
            " 也可用请求头 Accept: text/event-stream 强制流式。"
        ),
    )
    client_turn_id: str = Field(
        default="",
        description=(
            "前端生成的轮次唯一 ID（建议用单调递增数字或 UUID）。"
            " 多轮对话中每轮必须不同；网络重试时必须保持相同。"
            " 后端用它做幂等去重，保证消息不重复、不乱序。"
        ),
    )
    regenerate: bool = Field(
        default=False,
        description=(
            "true 表示用户点击'重新生成'。后端只写入 assistant 消息，"
            "不重复写入 user 消息；旧的 assistant 记录保留供前端翻页。"
        ),
    )
    selected_assistant_turn_id: str = Field(
        default="",
        description=(
            "预留字段：用户选中了某条历史 assistant 后，继续对话时传入"
            "该 assistant 的 turn_id。后续迭代将支持上下文替换。"
        ),
    )

    @field_validator("thread_id")
    @classmethod
    def _thread_id_must_not_be_blank(cls, value: str) -> str:
        """Reject blank thread_id so a frontend bug surfaces instead of silently
        writing every turn into one shared thread_id="" bucket."""
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError(
                "thread_id 不能为空：前端需为每个会话生成并复用一个固定的非空 thread_id"
                "（如 crypto.randomUUID()），读取历史时用列表返回的 thread_id 字段，"
                "不要用 checkpoint_id。"
            )
        return normalized


class ChatInvokeResponse(BaseModel):
    thread_id: str = Field(description="会话线程 ID。")
    current_case_id: int = Field(default=0, description="当前年审项目 ID。")
    current_entity_id: int = Field(default=0, description="被审计单位实体 ID。")
    current_entity_name: str = Field(default="", description="被审计单位名称。")
    final_report_ref: str = Field(default="", description="最终报告引用 ID。")
    final_report: str = Field(default="", description="最终报告正文。")
    assistant_message_id: str = Field(
        default="",
        description="本轮持久化 assistant 消息 ID；SSE 客户端应将 final_report_ref 绑定到此消息。",
    )
    trace_items: list[TraceItemModel] = Field(default_factory=list, description="报告断言对应的证据链。")
    reconciliation_items: list[ReconciliationLedgerItemModel] = Field(
        default_factory=list,
        description="增量对账台账列表。",
    )
    unresolved_relations: list[UnresolvedRelationItemModel] = Field(
        default_factory=list,
        description="当前年审项目仍待后续批次补齐的未决关系列表。",
    )
    unresolved_claims: list[UnresolvedClaimItemModel] = Field(
        default_factory=list,
        description="当前年审项目仍待后续批次补齐的未决断言列表。",
    )
    citation_coverage: CitationCoverageModel = Field(
        default_factory=CitationCoverageModel,
        description="报告角标覆盖率统计。",
    )
    response_analysis_runs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="本轮回复实际成功执行的年审分析运行范围；仅用于本回复的证据追溯。",
    )
    parse_summary: str = Field(default="", description="材料摄入摘要。")
    doc_category: str = Field(default="", description="审计资料类别编码。")
    batch_name: str = Field(default="", description="上传批次名称。")
    upload_batch_id: str = Field(default="", description="上传批次 ID。")
    operator_id: str = Field(default="", description="操作员 ID。")
    operator_name: str = Field(default="", description="操作员名称。")
    upload_batch_summary: dict = Field(default_factory=dict, description="上传批次摘要。")
    recognized_categories: list[str] = Field(default_factory=list, description="识别出的审计资料类别。")
    missing_categories: list[str] = Field(default_factory=list, description="项目仍缺失的审计资料类别。")
    duplicate_files: list[str] = Field(default_factory=list, description="疑似重复文件列表。")
    suspected_mismatch_files: list[str] = Field(default_factory=list, description="疑似类别不匹配文件列表。")
    new_files: list[str] = Field(default_factory=list, description="本次识别为新增的文件列表。")
    doc_category_validation: dict = Field(default_factory=dict, description="审计资料类别预校验结果。")
    intent: str = Field(default="", description="本次路由的图流程意图。")
    route_decision: RouteDecisionModel | None = Field(
        default=None,
        description="分层路由决策；业务线、capability、执行意图、权限模块和工具范围由统一注册表约束。",
    )
    memory_context: str = Field(default="", description="轻量会话记忆摘要。")
    audit_review_stage: str = Field(
        default="",
        description=(
            "完整年审后的人工确认阶段：awaiting_result_review、"
            "awaiting_artifact_confirmation 或附件已处理状态。"
        ),
    )
    active_template_versions: dict[str, str] = Field(
        default_factory=dict,
        description="本轮审计/附件生成所使用的已激活模板版本标签。",
    )
    attachment_package: dict[str, Any] = Field(
        default_factory=dict,
        description="用户确认后生成的附件包及其模板版本快照。",
    )


@router.post(
    "/invoke",
    summary="主对话入口",
    description=(
        "同一接口支持普通 JSON 返回和 SSE 流式返回。"
        " 后端会根据 query、年审项目上下文和 uploaded_files 路由到资料、审计分析、报告、任务或图谱能力。"
        " case.profile / material.status / material.validate / evidence.resolve / task.query"
        " 进入确定性年度审计节点；audit.full / audit.reaudit 进入报告图，"
        " audit.drilldown / graph.query 进入各自年度审计 Agent。"
        " evidence.resolve 只查询当前年审项目的资料与证据。"
        " case.create / material.upload / task.write 进入确定性写命令节点；"
        " 创建项目和任务操作可使用 write_command 提供结构化槽位，"
        " 缺少必填字段、身份、项目权限或任务归属校验失败时不执行写入。"
        " material.upload 只验收本轮前置 ingest 结果，不二次摄入。"
        " 低置信度、缺少项目上下文或缺少写操作目标时返回澄清问题，不调用业务工具。"
        "\n\nSSE 切换方式："
        "\n- 请求体传 `stream=true`；或"
        "\n- 请求头传 `Accept: text/event-stream`。"
        "\n满足任意一个条件即切换到 SSE 流式模式。"
        "\n\nSSE 事件类型：`start`、`node`、`final`、`done`、`error`。"
    ),
    response_model=ChatInvokeResponse,
    responses={
        200: {
            "description": "普通请求返回 JSON；当 `stream=true` 或请求头 `Accept: text/event-stream` 时返回 SSE 事件流。",
        }
    },
)
async def invoke_chat(payload: ChatRequest, request: Request,
                      identity: Identity = Depends(require_any_module(CHAT_INVOKE_MODULES))):
    request_id = getattr(request.state, "request_id", "-")
    logger = build_request_logger(
        __name__,
        request_id=request_id,
        thread_id=payload.thread_id,
        case_id=payload.current_case_id or "-",
    )
    wants_stream = payload.stream or "text/event-stream" in request.headers.get("accept", "")
    logger.info(
        "chat_invoke_received stream=%s uploaded_file_count=%s query_preview=%s client_turn_id=%s",
        wants_stream,
        len(payload.uploaded_files),
        preview_text(payload.query),
        payload.client_turn_id,
    )

    settings = get_settings()
    section_codes = visible_report_sections(identity)  # 报告段落分权：可见 section_code 集
    _require_pre_graph_write_module(identity, payload)
    requested_case_id = extract_case_id(payload.query) or payload.current_case_id
    allow_unbound = is_explicit_case_create_request(payload.model_dump())
    await anyio.to_thread.run_sync(
        lambda: _require_existing_annual_engagement(requested_case_id, allow_unbound=allow_unbound)
    )
    if settings.auth_enabled:
        await anyio.to_thread.run_sync(
            lambda: _ensure_chat_thread(identity, payload.thread_id, requested_case_id, allow_unbound)
        )

    if wants_stream:
        return StreamingResponse(
            _stream_chat_events(payload, logger, settings.postgres_checkpointer_dsn, section_codes, identity),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Serialize per-thread execution via PostgreSQL advisory lock.
    # This guarantees order consistency even with multiple uvicorn workers.
    async with thread_advisory_lock(settings.postgres_checkpointer_dsn, payload.thread_id):
        cached = _resolve_cached_turn(payload.thread_id, payload.client_turn_id)
        if cached is not None and not payload.regenerate:
            logger.info("chat_invoke_cached client_turn_id=%s", payload.client_turn_id)
            return _build_final_response(
                payload,
                _normalize_cached_turn(payload, cached),
                section_codes,
            )

        graph_input = _build_graph_input(payload, identity)
        result = await anyio.to_thread.run_sync(
            lambda: _run_graph_with_logging(
                graph_input,
                payload.thread_id,
                logger,
                identity,
            )
        )

    logger.info(
        "chat_invoke_completed intent=%s capability=%s route_source=%s entity=%s final_report_chars=%s",
        result.get("intent", ""),
        (result.get("route_decision") or {}).get("capability", ""),
        (result.get("route_decision") or {}).get("source", ""),
        result.get("current_entity_name", ""),
        len(resolve_final_report(result) or result.get("final_report", "") or ""),
    )
    if settings.auth_enabled:
        await anyio.to_thread.run_sync(
            lambda: _bind_created_case_if_needed(payload.thread_id, result, identity)
        )
        await anyio.to_thread.run_sync(
            lambda: get_tenancy_service().update_thread_metadata(
                payload.thread_id,
                last_intent=str(result.get("intent", "") or ""),
                title=payload.query.strip()[:50],
            )
        )
    return _build_final_response(payload, result, section_codes)


def _identity_context(identity: Identity | None) -> dict[str, Any]:
    if identity is None:
        return {}
    return {
        "user_id": identity.user_id,
        "username": identity.username,
        "roles": list(identity.roles),
        "company_id": identity.company_id,
        "apps": list(identity.apps),
        "is_company_admin": identity.is_company_admin,
        "is_super_admin": identity.is_super_admin,
        "authenticated": identity.authenticated,
    }


def _ensure_chat_thread(
    identity: Identity,
    thread_id: str,
    case_id: int,
    allow_unbound: bool,
) -> None:
    service = get_tenancy_service()
    if allow_unbound:
        service.ensure_thread_for_invoke(identity, thread_id, case_id, allow_unbound=True)
    else:
        service.ensure_thread_for_invoke(identity, thread_id, case_id)


def _require_existing_annual_engagement(case_id: int, *, allow_unbound: bool) -> None:
    """Reject a non-existent annual engagement before any chat route executes.

    Local development commonly runs with authentication disabled, so tenancy
    checks alone cannot be the guardrail for a case-bound chat. Let an
    explicit case-creation request remain unbound, but never let an arbitrary
    positive ``caseId`` reach an LLM or deterministic tool as if it were an
    audit engagement.
    """
    if allow_unbound or int(case_id or 0) <= 0:
        return
    from ai_hunter.annual_audit.engagement_repository import EngagementNotFoundError, get_engagement

    try:
        get_engagement(int(case_id))
    except EngagementNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"年审项目 {int(case_id)} 不存在，不能执行审计分析或生成审计结论。"
                "请先创建或选择一个真实项目，并导入相应审计资料。"
            ),
        ) from exc


def _build_graph_input(payload: ChatRequest, identity: Identity | None = None) -> dict[str, Any]:
    """Prepare the input dict for the graph.

    Drops ``current_case_id`` when it is the Pydantic default (0) so the
    checkpointer's historical value is not overwritten on multi-turn threads.
    """
    data = payload.model_dump(exclude={"stream"})
    data["identity_context"] = _identity_context(identity)
    if data.get("current_case_id") == 0:
        data.pop("current_case_id", None)
    return data


def _cached_case_id(payload: ChatRequest) -> int:
    if payload.current_case_id > 0:
        return payload.current_case_id
    if not get_settings().auth_enabled:
        return 0
    try:
        thread = get_tenancy_service().get_thread_access_record(payload.thread_id)
    except Exception:
        return 0
    return int(thread.case_id or 0) if thread else 0


def _bind_created_case_if_needed(thread_id: str, state: dict[str, Any], identity: Identity) -> None:
    decision = state.get("route_decision") or {}
    result = state.get("business_line_result") or {}
    if not isinstance(decision, dict) or not isinstance(result, dict):
        return
    if decision.get("capability") != "case.create" or not result.get("ok"):
        return
    case_id = int(state.get("current_case_id") or decision.get("case_id") or 0)
    if case_id > 0:
        get_tenancy_service().bind_thread_case(identity, thread_id, case_id)


def _require_intent_module(identity: Identity, intent: str) -> None:
    module = INTENT_MODULES.get(str(intent or ""))
    if module and not has_module(identity, module):
        raise HTTPException(status_code=403, detail=f"无权限执行意图：{intent}，需要模块：{module}")


def _require_route_module(identity: Identity, payload: dict[str, Any]) -> None:
    decision = payload.get("route_decision") or {}
    capability = str(decision.get("capability", "")) if isinstance(decision, dict) else ""
    module = CAPABILITY_MODULES.get(capability)
    if module:
        if not has_module(identity, module):
            raise HTTPException(status_code=403, detail=f"无权限执行业务能力：{capability}，需要模块：{module}")
        return
    _require_intent_module(identity, str(payload.get("intent", "")))


def _require_pre_graph_write_module(identity: Identity, payload: ChatRequest) -> None:
    """Reject deterministic write inputs before pre-route ingestion can run."""
    capability = "material.upload" if payload.uploaded_files else ""
    if not capability and payload.write_command is not None:
        capability = str(payload.write_command.capability or "")
    module = CAPABILITY_MODULES.get(capability)
    if module and not has_module(identity, module):
        raise HTTPException(status_code=403, detail=f"无权限执行业务能力：{capability}，需要模块：{module}")


_RESPONSE_FINAL_STATE_FIELDS = (
    "current_case_id",
    "current_entity_id",
    "current_entity_name",
    "final_report_ref",
    "final_report_summary",
    "final_report",
    "assistant_message_id",
    "response_evidence_index",
    "response_analysis_runs",
    "trace_items",
    "citation_coverage",
    "reconciliation_items",
    "unresolved_relations",
    "unresolved_claims",
    "intent",
    "route_decision",
    "audit_review_stage",
    "active_template_versions",
    "attachment_package",
)


def _merge_response_final_state(
    state: dict[str, Any],
    update: dict[str, Any],
) -> dict[str, Any]:
    """Merge terminal node output without falling back to a prior turn.

    Async checkpointer visibility can lag the astream_events completion event
    by one scheduling turn. The terminal node output is sufficient to build
    this response's final payload, so retain it until aget_state is read.
    """
    merged = dict(state)
    for field in _RESPONSE_FINAL_STATE_FIELDS:
        if field in update:
            merged[field] = update[field]
    return merged


async def _stream_chat_events(
    payload: ChatRequest,
    logger: logging.LoggerAdapter,
    dsn: str,
    visible_section_codes: set[str] | None = None,
    identity: Identity | None = None,
) -> AsyncIterator[str]:
    """Stream graph progress as SSE events while keeping one public API surface.

    visible_section_codes：报告段落分权——不可见 section_code 的段落事件不下发，final 报告同样过滤。
    None 表示不过滤（向后兼容）。
    """
    def _section_visible(sid: str | None) -> bool:
        if visible_section_codes is None or sid is None:
            return True
        section_code = report_section_code_for_id(sid)
        return section_code is None or section_code in visible_section_codes
    # Serialize per-thread execution via PostgreSQL advisory lock.
    async with thread_advisory_lock(dsn, payload.thread_id):
        cached = _resolve_cached_turn(payload.thread_id, payload.client_turn_id)
        if cached is not None and not payload.regenerate:
            logger.info("chat_stream_cached client_turn_id=%s", payload.client_turn_id)
            async for frame in _cached_sse_response(
                payload,
                _normalize_cached_turn(payload, cached),
                visible_section_codes,
            ):
                yield frame
            return

        config = {"configurable": {"thread_id": payload.thread_id}}
        graph_input = _build_graph_input(payload, identity)

        yield _sse_event(
            "start",
            {
                "thread_id": payload.thread_id,
                "query": payload.query,
                "current_case_id": payload.current_case_id,
                "uploaded_file_count": len(payload.uploaded_files),
            },
        )
        logger.info("chat_stream_started uploaded_file_count=%s", len(payload.uploaded_files))

        try:
            streaming_graph = await _ensure_async_graph()
            started_sections: set[str] = set()
            reasoning_stream_states: dict[str, dict[str, str]] = {}
            terminal_response_state: dict[str, Any] = {}
            async for event in streaming_graph.astream_events(
                graph_input,
                config=config,
                version="v2",
            ):
                kind = event.get("event", "")
                name = event.get("name", "")
                data = event.get("data", {}) or {}
                node = (event.get("metadata", {}) or {}).get("langgraph_node", "")
                section_id = _any_section_id_from_node(node)

                if kind == "on_chain_end" and name not in {"__end__", "LangGraph"}:
                    # Emit section completion only when a report generator exposes section nodes.
                    done_sid = _any_section_id_from_node(name)
                    if done_sid and _section_visible(done_sid):
                        for part_kind, part_text in _flush_tagged_reasoning_stream(reasoning_stream_states.get(done_sid, {})):
                            if part_kind == "reasoning":
                                yield _sse_event("section_reasoning_chunk", {"section_id": done_sid, "text": part_text})
                            else:
                                yield _sse_event("section_chunk", {"section_id": done_sid, "text": part_text})
                        yield _sse_event("section_done", {"section_id": done_sid})
                    node_payload = data.get("output", {})
                    if not isinstance(node_payload, dict):
                        node_payload = {}
                    if name in {"finalize_answer", "persist_conversation_memory"}:
                        terminal_response_state = _merge_response_final_state(
                            terminal_response_state,
                            node_payload,
                        )
                    if name == "classify_intent" and identity is not None:
                        try:
                            _require_route_module(identity, node_payload)
                        except HTTPException as exc:
                            yield _sse_event(
                                "error",
                                {
                                    "thread_id": payload.thread_id,
                                    "status_code": exc.status_code,
                                    "message": exc.detail,
                                },
                            )
                            return
                    logger.info(
                        "chat_stream_node node=%s summary=%s",
                        name,
                        _summarize_node_update(name, node_payload),
                    )
                    yield _sse_event(
                        "node",
                        {
                            "node": name,
                            "summary": _summarize_node_update(name, node_payload),
                            "payload": _dehydrate_node_payload(name, node_payload),
                        },
                    )
                    continue

                if kind == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    if chunk is None:
                        continue
                    content = getattr(chunk, "content", "")
                    reasoning = getattr(chunk, "reasoning_content", "") or getattr(
                        chunk, "additional_kwargs", {}
                    ).get("reasoning_content", "")
                    if section_id:
                        # 报告段落分权：不可见 section_code 的段 token 不下发
                        if not _section_visible(section_id):
                            continue
                        # Section-capable report generators tag tokens for frontend assembly.
                        if section_id not in started_sections:
                            started_sections.add(section_id)
                            section = _any_section_meta(section_id)
                            yield _sse_event(
                                "section_start",
                                {
                                    "section_id": section_id,
                                    "title": section.get("title", ""),
                                    "audience": section.get("audience", ""),
                                },
                            )
                        state = reasoning_stream_states.setdefault(section_id, {"mode": "content", "buffer": ""})
                        for part_kind, part_text in _split_tagged_reasoning_stream(content, state):
                            if part_kind == "reasoning":
                                yield _sse_event("section_reasoning_chunk", {"section_id": section_id, "text": part_text})
                            else:
                                yield _sse_event("section_chunk", {"section_id": section_id, "text": part_text})
                        if isinstance(reasoning, str) and reasoning:
                            yield _sse_event("section_reasoning_chunk", {"section_id": section_id, "text": reasoning})
                        continue
                    # 非段节点（兜底）：沿用旧单流事件
                    state = reasoning_stream_states.setdefault("__default__", {"mode": "content", "buffer": ""})
                    for part_kind, part_text in _split_tagged_reasoning_stream(content, state):
                        if part_kind == "reasoning":
                            yield _sse_event("reasoning_chunk", {"text": part_text})
                        else:
                            yield _sse_event("text_chunk", {"text": part_text})
                    if isinstance(reasoning, str) and reasoning:
                        # 思考过程走独立事件，前端可与正文 text_chunk 分区/折叠渲染。
                        yield _sse_event("reasoning_chunk", {"text": reasoning})
                    continue

            # Fetch the complete final state from the checkpointer so that
            # fields only present in the checkpoint (trace_items, citation_coverage,
            # etc.) are not lost.
            snapshot = await streaming_graph.aget_state(config)
            final_state = dict(snapshot.values) if snapshot else dict(graph_input)
            final_state = _merge_response_final_state(
                final_state,
                terminal_response_state,
            )

            logger.info(
                "chat_stream_completed intent=%s capability=%s route_source=%s entity=%s final_report_chars=%s",
                final_state.get("intent", ""),
                (final_state.get("route_decision") or {}).get("capability", ""),
                (final_state.get("route_decision") or {}).get("source", ""),
                final_state.get("current_entity_name", ""),
                len(resolve_final_report(final_state) or final_state.get("final_report", "") or ""),
            )
            if get_settings().auth_enabled:
                await anyio.to_thread.run_sync(
                    lambda: _bind_created_case_if_needed(payload.thread_id, final_state, identity)
                )
                await anyio.to_thread.run_sync(
                    lambda: get_tenancy_service().update_thread_metadata(
                        payload.thread_id,
                        last_intent=str(final_state.get("intent", "") or ""),
                        title=payload.query.strip()[:50],
                    )
                )
            yield _sse_event("final", _build_final_response(payload, final_state, visible_section_codes).model_dump())
            yield _sse_event("done", {"thread_id": payload.thread_id})
        except Exception as exc:
            logger.exception("chat_stream_failed error=%s", exc)
            yield _sse_event(
                "error",
                {
                    "thread_id": payload.thread_id,
                    "message": str(exc),
                },
            )


def _run_graph_with_logging(
    payload: dict[str, Any],
    thread_id: str,
    logger: logging.LoggerAdapter,
    identity: Identity,
) -> dict[str, Any]:
    """Execute the graph while logging node-level progress for non-stream requests."""
    latest_state: dict[str, Any] = payload
    if not hasattr(graph, "stream"):
        return graph.invoke(payload, config={"configurable": {"thread_id": thread_id}})

    for mode, chunk in graph.stream(
        payload,
        config={"configurable": {"thread_id": thread_id}},
        stream_mode=["updates", "values"],
    ):
        if mode == "values" and isinstance(chunk, dict):
            latest_state = chunk
            continue
        if mode != "updates" or not isinstance(chunk, dict):
            continue
        node_name, node_payload = next(iter(chunk.items()))
        if node_name == "classify_intent" and isinstance(node_payload, dict):
            _require_route_module(identity, node_payload)
        logger.info(
            "chat_graph_node node=%s summary=%s",
            node_name,
            _summarize_node_update(node_name, node_payload),
        )
    return latest_state


def _response_analysis_runs(value: Any) -> list[dict[str, Any]]:
    """Validate the exact persisted analysis scopes exposed to a reply.

    The values originate from ToolMessages, but the conversation table is
    long-lived JSON.  Revalidate here so an old or malformed record cannot
    claim that an arbitrary analysis run supported a visible reply.
    """
    if not isinstance(value, list):
        return []
    scopes: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or "").strip()
        analysis_type = str(item.get("analysis_type") or "").strip()
        run_id = item.get("analysis_run_id")
        if isinstance(run_id, bool):
            continue
        try:
            analysis_run_id = int(run_id)
        except (TypeError, ValueError):
            continue
        if not tool_name or not analysis_type or analysis_run_id <= 0:
            continue
        key = (tool_name, analysis_type, analysis_run_id)
        if key in seen:
            continue
        seen.add(key)
        scopes.append(
            {
                "tool_name": tool_name,
                "analysis_type": analysis_type,
                "analysis_run_id": analysis_run_id,
            }
        )
    return scopes


def _build_final_response(payload: ChatRequest, result: dict[str, Any],
                          visible_section_codes: set[str] | None = None) -> ChatInvokeResponse:
    """Normalize final API output for both blocking and streaming modes.

    visible_section_codes=None → 不过滤（向后兼容）；否则按可见 section_code 过滤报告段落。
    """
    unresolved_items = resolve_unresolved_graph_items(result)
    final_report = resolve_final_report(result) or result.get("final_report", "")
    if visible_section_codes is not None:
        final_report = filter_report_text_by_sections(final_report, visible_section_codes)
    return ChatInvokeResponse(
        thread_id=payload.thread_id,
        current_case_id=result.get("current_case_id", 0),
        current_entity_id=result.get("current_entity_id", 0),
        current_entity_name=result.get("current_entity_name", ""),
        final_report_ref=result.get("final_report_ref", ""),
        final_report=final_report,
        assistant_message_id=result.get("assistant_message_id", ""),
        trace_items=[TraceItemModel.model_validate(item) for item in resolve_trace_items(result)],
        reconciliation_items=[
            ReconciliationLedgerItemModel.model_validate(item) for item in resolve_reconciliation_items(result)
        ],
        unresolved_relations=[
            UnresolvedRelationItemModel.model_validate(item)
            for item in unresolved_items.get("unresolved_relations", [])
        ],
        unresolved_claims=[
            UnresolvedClaimItemModel.model_validate(item)
            for item in unresolved_items.get("unresolved_claims", [])
        ],
        citation_coverage=CitationCoverageModel.model_validate(resolve_citation_coverage(result)),
        response_analysis_runs=_response_analysis_runs(result.get("response_analysis_runs")),
        parse_summary=result.get("parse_summary", ""),
        doc_category=result.get("doc_category", payload.doc_category),
        batch_name=result.get("batch_name", payload.batch_name),
        upload_batch_id=result.get("upload_batch_id", payload.upload_batch_id),
        operator_id=result.get("operator_id", payload.operator_id),
        operator_name=result.get("operator_name", payload.operator_name),
        upload_batch_summary=result.get("upload_batch_summary", {}),
        recognized_categories=result.get("recognized_categories", result.get("categories_found", [])),
        missing_categories=result.get("missing_categories", []),
        duplicate_files=result.get("duplicate_files", []),
        suspected_mismatch_files=result.get("suspected_mismatch_files", []),
        new_files=result.get("new_files", []),
        doc_category_validation=result.get("doc_category_validation", {}),
        intent=result.get("intent", ""),
        route_decision=result.get("route_decision") or None,
        memory_context=result.get("memory_context", ""),
        audit_review_stage=str(result.get("audit_review_stage") or ""),
        active_template_versions=dict(result.get("active_template_versions") or {}),
        attachment_package=dict(result.get("attachment_package") or {}),
    )


class ChatUploadResponse(BaseModel):
    """Sync MinIO upload result for one /chat/upload-files call."""

    upload_batch_id: str = Field(description="本批次的批次 ID。")
    case_id: int = Field(description="关联的年审项目 ID。")
    entity_id: int = Field(default=0, description="被审计单位实体 ID。")
    entity_name: str = Field(default="", description="经项目主数据校验后的被审计单位名称。")
    effective_entity_name: str = Field(
        default="",
        description="实际用于 MinIO key 命名的权威被审计单位名称。",
    )
    file_count: int = Field(description="本批次上传文件数(含重复)。")
    duplicate_files: list[str] = Field(
        default_factory=list, description="本批次内重复的文件名列表(按 SHA256 去重)。"
    )
    files: list[FileItem] = Field(
        default_factory=list,
        description="上传后的 FileItem 列表;每项含 storage_ref / url / file_hash / storage_*。",
    )


@router.post(
    "/upload-files",
    summary="对话入口的同步文件上传",
    description=(
        "在对话流中先一步把审计资料落到 MinIO,前端拿到含 storage_ref / file_hash 的 FileItem 列表后,"
        "再把这份列表挂到 /chat/invoke 的 uploaded_files 字段走同步问图流程。"
        "\n\n- 强约束:current_case_id 必须 > 0。"
        "\n- AUTH_ENABLED=true 时校验当前用户对年审项目的 owner/member/company 权限。"
        "\n- entity_id/名称必须与年审项目主数据一致。"
        "\n- 不写 source_file / material_event 表,file_id 留空,下游继续用 file_hash 追溯。"
        "\n- 重复文件按 SHA256 在本批次内去重,duplicate_files 字段返回被去重的名字。"
    ),
    response_model=ChatUploadResponse,
    status_code=status.HTTP_200_OK,
)
async def chat_upload_files(
    request: Request,
    files: list[UploadFile] = File(
        ...,
        description=(
            "待上传文件列表。txt/csv/md 直接落 MinIO;"
            "pdf/doc/docx/xls/xlsx/xlsm/et/ett 与图片走 OCR 路径在后续 /chat/invoke 中执行。"
        ),
    ),
    current_case_id: int = Form(
        0,
        description="年审项目 ID;> 0 必填,对话入口上传必须先关联到具体项目。",
    ),
    current_entity_id: int = Form(0, description="被审计单位实体 ID;未知时传 0。"),
    current_entity_name: str = Form(
        "",
        description="被审计单位名称;为空时由年审项目主数据解析。",
    ),
    doc_category: str = Form("", description="可选,本批审计资料类别编码;非必填。"),
    batch_name: str = Form("", description="可选,本批次名称。"),
    upload_batch_id: str = Form("", description="可选,本批次 ID;空时由后端生成。"),
    operator_id: str = Form("", description="可选,操作员 ID。"),
    operator_name: str = Form("", description="可选,操作员名称。"),
    identity: Identity = Depends(require_any_module(("report", "corrections"))),
) -> dict:
    """Accept multipart uploads, push bytes to MinIO, return one FileItem per file."""
    settings = get_settings()
    if not files:
        raise HTTPException(status_code=400, detail="至少上传一个文件。")
    if len(files) > settings.max_upload_files:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多上传 {settings.max_upload_files} 个文件。",
        )
    if not current_case_id or current_case_id <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "current_case_id 必填且 > 0:对话入口的上传资料必须先关联到具体年审项目。"
                "如尚未选定项目,请先在 /chat/invoke 中发起带 current_case_id 的对话,"
                "再调用本接口上传补充材料。"
            ),
        )
    require_case_access(current_case_id, identity)

    operator_id = operator_id or identity.user_id
    operator_name = operator_name or identity.username
    resolved_batch_id = resolve_upload_batch_id(upload_batch_id)
    request_id = getattr(request.state, "request_id", "-")
    logger = build_request_logger(
        __name__,
        request_id=request_id,
        case_id=current_case_id,
    )

    entity_resolution = resolve_engagement_entity(
        case_id=current_case_id,
        entity_id=current_entity_id,
        entity_name=current_entity_name,
        identity=identity,
    )
    current_entity_id = entity_resolution.entity_id
    current_entity_name = entity_resolution.entity_name
    effective_entity_name = entity_resolution.entity_name
    logger.info(
        "chat_upload_received files=%s entity_id=%s effective_entity_name=%s resolution_source=%s upload_batch_id=%s",
        len(files),
        current_entity_id,
        effective_entity_name,
        entity_resolution.source,
        resolved_batch_id,
    )

    uploaded_files: list[FileItem] = []
    seen_hashes: dict[str, str] = {}
    duplicate_files: list[str] = []
    for upload in files:
        item = await to_file_item(
            upload,
            settings,
            logger,
            current_case_id=current_case_id,
            current_entity_id=current_entity_id,
            entity_name=effective_entity_name,
            doc_category=doc_category,
            upload_batch_id=resolved_batch_id,
        )
        file_hash = item.get("file_hash", "")
        if file_hash and file_hash in seen_hashes:
            item["duplicate_of"] = seen_hashes[file_hash]
            duplicate_files.append(item.get("name", "uploaded-file"))
        elif file_hash:
            seen_hashes[file_hash] = item.get("name", "uploaded-file")
        uploaded_files.append(item)

    return {
        "upload_batch_id": resolved_batch_id,
        "case_id": current_case_id,
        "entity_id": current_entity_id,
        "entity_name": current_entity_name,
        "effective_entity_name": effective_entity_name,
        "file_count": len(uploaded_files),
        "duplicate_files": duplicate_files,
        "files": uploaded_files,
    }


def _summarize_node_update(node_name: str, payload: Any) -> str:
    """Turn one graph node update into a short user-visible progress message."""
    if not isinstance(payload, dict):
        return f"{node_name} completed"
    if node_name == "normalize_input":
        return "已归一化请求参数"
    if node_name == "hydrate_memory_context":
        return "已装载轻量对话记忆"
    if node_name == "resolve_case_context":
        case_id = payload.get("current_case_id", 0)
        entity_name = payload.get("current_entity_name", "")
        if entity_name:
            return f"已解析年审项目上下文，项目ID={case_id}，被审计单位={entity_name}"
        return f"已解析年审项目上下文，项目ID={case_id}"
    if node_name == "ingest_graph":
        parse_summary = payload.get("parse_summary", "")
        entity_name = payload.get("current_entity_name", "")
        if parse_summary and entity_name:
            return f"补充资料已摄入，被审计单位={entity_name}，{parse_summary}"
        if parse_summary:
            return f"补充材料已摄入，{parse_summary}"
        return "补充材料摄入完成"
    if node_name == "summarize_ingest_result":
        return "已生成材料摄入摘要"
    if node_name == "classify_intent":
        decision = payload.get("route_decision") or {}
        capability = decision.get("capability", "") if isinstance(decision, dict) else ""
        confidence = decision.get("confidence", 0) if isinstance(decision, dict) else 0
        return f"已完成意图路由：{capability or payload.get('intent', '') or 'unknown'} ({confidence:.2f})"
    if node_name == "clarify_route":
        return "路由信息不足，已请求补充必要信息"
    if node_name == "extract_correction":
        records = payload.get("correction_records", [])
        return f"已提取修正台账，共 {len(records)} 条"
    if node_name == "full_audit_graph":
        tasks = payload.get("extracted_tasks", [])
        report_summary = payload.get("final_report_summary", "")
        if tasks:
            return f"完整审计已生成，并提取 {len(tasks)} 条督办任务"
        if report_summary:
            return "完整审计报告已生成"
        return "完整审计流程完成"
    if node_name == "create_tasks":
        created = payload.get("task_create_result", {})
        return f"督办任务已处理：{str(created)[:120]}"
    if node_name == "drilldown_agent_graph":
        agent_output = (payload.get("agent_output") or "").strip()
        return f"下钻追问已完成：{agent_output[:80]}" if agent_output else "下钻追问已完成"
    if node_name in {"operator_subgraph", "audit_analysis_subgraph", "supervision_subgraph", "common_subgraph"}:
        decision = payload.get("route_decision") or {}
        capability = str(decision.get("capability") or "") if isinstance(decision, dict) else ""
        if capability == "audit.full":
            return "业务线完整审计已完成"
        if capability == "audit.reaudit":
            return "业务线修正重审已完成"
        agent_output = (payload.get("agent_output") or "").strip()
        return f"业务线能力执行已完成：{agent_output[:80]}" if agent_output else "业务线能力执行已完成"
    if node_name == "finalize_answer":
        return "已整理最终答复"
    if node_name == "persist_conversation_memory":
        return "已持久化当前会话记忆"
    return f"{node_name} completed"


def _dehydrate_node_payload(node_name: str, payload: Any) -> dict[str, Any]:
    """Return a compact node payload that is safe to expose in streamed progress."""
    if not isinstance(payload, dict):
        return {"value": str(payload)}

    compact: dict[str, Any] = {}
    for key in (
        "intent",
        "route_decision",
        "current_case_id",
        "current_entity_id",
        "current_entity_name",
        "parse_summary",
        "doc_category",
        "batch_name",
        "upload_batch_id",
        "operator_id",
        "operator_name",
        "upload_batch_summary",
        "ingest_payload_summary",
        "full_context_summary",
        "report_part_a_summary",
        "report_part_b_summary",
        "final_report_summary",
        "memory_context",
        "task_create_result",
        "agent_output",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value:
            compact[key] = value[:400]
        elif value not in (None, "", [], {}):
            compact[key] = value

    if "categories_found" in payload:
        compact["categories_found"] = payload.get("categories_found", [])[:10]
    if "recognized_categories" in payload:
        compact["recognized_categories"] = payload.get("recognized_categories", [])[:10]
    if "missing_categories" in payload:
        compact["missing_categories"] = payload.get("missing_categories", [])[:10]
    if "duplicate_files" in payload:
        compact["duplicate_files"] = payload.get("duplicate_files", [])[:10]
    if "suspected_mismatch_files" in payload:
        compact["suspected_mismatch_files"] = payload.get("suspected_mismatch_files", [])[:10]
    if "new_files" in payload:
        compact["new_files"] = payload.get("new_files", [])[:10]
    if "extracted_tasks" in payload:
        compact["extracted_task_count"] = len(payload.get("extracted_tasks", []))
    if "trace_items" in payload:
        compact["trace_item_count"] = len(payload.get("trace_items", []))
    if "correction_records" in payload:
        compact["correction_record_count"] = len(payload.get("correction_records", []))
    if "records_inserted" in payload:
        compact["records_inserted"] = payload.get("records_inserted", 0)
    if node_name == "persist_conversation_memory" and "messages" in payload:
        compact["message_count"] = len(payload.get("messages", []))
    return compact


def _sse_event(event: str, data: dict[str, Any]) -> str:
    """Format one SSE event frame."""
    return f"event: {event}\ndata: {json_dumps_safe(data)}\n\n"


# ============================================================================
# Conversation History Management Routes
# ============================================================================


class ThreadListItem(BaseModel):
    """Single thread item in the list."""
    thread_id: str = Field(description="会话线程 ID")
    title: str = Field(description="会话标题")
    checkpoint_id: str = Field(description="最新检查点 ID")
    case_id: int = Field(description="年审项目 ID")
    entity_id: int = Field(description="被审计单位实体 ID")
    entity_name: str = Field(description="被审计单位名称")
    last_query: str = Field(description="最后一次用户输入")
    last_intent: str = Field(description="最后一次意图")
    updated_at: str | None = Field(description="最后更新时间")


class ThreadListResponse(BaseModel):
    """Thread list response with pagination."""
    threads: list[ThreadListItem] = Field(description="会话线程列表")
    total: int = Field(description="总数")
    limit: int = Field(description="每页数量")
    offset: int = Field(description="偏移量")


class ThreadDetailResponse(BaseModel):
    """Detailed thread information."""
    thread_id: str = Field(description="会话线程 ID")
    title: str = Field(description="会话标题")
    checkpoint_id: str = Field(description="最新检查点 ID")
    case_id: int = Field(description="年审项目 ID")
    entity_id: int = Field(description="被审计单位实体 ID")
    entity_name: str = Field(description="被审计单位名称")
    last_query: str = Field(description="最后一次用户输入")
    last_intent: str = Field(description="最后一次意图")
    final_report_ref: str = Field(description="最终报告引用 ID")
    memory_context: str = Field(description="轻量会话记忆摘要")
    step: int = Field(description="当前步骤数")
    upload_batch_id: str = Field(default="", description="上传批次 ID")
    doc_category: str = Field(default="", description="审计资料类别")
    batch_name: str = Field(default="", description="批次名称")
    created_at: str | None = Field(description="会话创建时间")
    updated_at: str | None = Field(description="最后更新时间")


class DeleteThreadResponse(BaseModel):
    """Thread deletion response."""
    success: bool = Field(description="是否删除成功")
    thread_id: str = Field(description="被删除的线程 ID")


@router.get(
    "/threads",
    summary="获取会话历史列表",
    description=(
        "返回会话线程列表，支持按案件 ID 过滤和分页。"
        "\n\n启用鉴权后，仅返回当前用户按公司、案件 owner/member 规则可读的会话。"
        "每个线程包含最后一次对话的摘要信息，便于前端展示历史会话列表。"
    ),
    response_model=ThreadListResponse,
)
async def list_threads(
    case_id: int | None = Query(None, description="可选，按案件 ID 过滤"),
    limit: int = Query(50, ge=1, le=200, description="每页数量，默认 50"),
    offset: int = Query(0, ge=0, description="偏移量，默认 0"),
    identity: Identity = Depends(require_module("report")),
):
    """List conversation threads with optional case_id filter."""
    try:
        service = get_conversation_service()
        allowed_thread_ids = None
        if get_settings().auth_enabled:
            allowed_thread_ids = await anyio.to_thread.run_sync(
                lambda: get_tenancy_service().list_accessible_thread_ids(identity, case_id=case_id)
            )
        result = service.list_threads(
            case_id=case_id,
            limit=limit,
            offset=offset,
            allowed_thread_ids=allowed_thread_ids,
        )
        
        threads = [ThreadListItem(**thread) for thread in result["threads"]]
        
        return ThreadListResponse(
            threads=threads,
            total=result["total"],
            limit=result["limit"],
            offset=result["offset"],
        )
    except Exception as exc:
        LOGGER.exception("list_threads_failed case_id=%s error=%s", case_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to list threads: {str(exc)}")


@router.get(
    "/threads/{thread_id}",
    summary="获取会话详情",
    description="返回当前用户有权读取的会话详情，包括完整的记忆上下文和报告引用。",
    response_model=ThreadDetailResponse,
)
async def get_thread_detail(thread_id: str, identity: Identity = Depends(require_module("report"))):
    """Get detailed information about a specific thread."""
    try:
        if get_settings().auth_enabled:
            require_thread_access(thread_id, identity)
        service = get_conversation_service()
        thread = service.get_thread_detail(thread_id)
        
        if not thread:
            # Do not include thread_id or explain whether another tenant owns
            # it.  A legacy conversation outside the annual-audit store must
            # never be presented as a source that can support an audit.
            raise HTTPException(
                status_code=404,
                detail=(
                    "该历史会话在当前年审存储中不可用。请在对应年审项目内重新发起会话；"
                    "未在当前存储中可追溯的历史内容不能作为审计依据。"
                ),
            )
        
        return ThreadDetailResponse(**thread)
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.exception("get_thread_detail_failed thread_id=%s error=%s", thread_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to get thread detail: {str(exc)}")


@router.delete(
    "/threads/{thread_id}",
    summary="删除会话",
    description=(
        "软删除指定会话线程，数据保留在数据库中用于审计。"
        "启用鉴权后，仅 thread 创建人、案件 owner、公司管理员或全局超级管理员可删除。"
    ),
    response_model=DeleteThreadResponse,
)
async def delete_thread(thread_id: str, identity: Identity = Depends(require_module("report"))):
    """Soft delete a conversation thread by setting deleted_at timestamp."""
    try:
        if get_settings().auth_enabled:
            require_thread_manage(thread_id, identity)
        service = get_conversation_service()
        deleted = service.delete_thread(thread_id)
        
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        
        return DeleteThreadResponse(success=True, thread_id=thread_id)
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.exception("delete_thread_failed thread_id=%s error=%s", thread_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to delete thread: {str(exc)}")


class MessageItem(BaseModel):
    """Single message in a conversation."""
    role: str = Field(description="消息角色：user, assistant, system")
    content: str = Field(description="消息内容；assistant 为完整答复正文")
    type: str = Field(description="LangChain 消息类型：human, ai, system")
    id: str = Field(default="", description="消息 ID")
    name: str = Field(default="", description="消息发送者名称")
    final_report_ref: str = Field(default="", description="该轮最终报告引用，可用于拉取证据链/角标")
    intent: str = Field(default="", description="该轮图流程意图：full_audit / drilldown / re_audit / ingest 等")
    route_decision: RouteDecisionModel | None = Field(
        default=None,
        description="该轮分层业务路由决策；历史旧消息可能为空。",
    )
    uploaded_files: list[FileItem] = Field(
        default_factory=list,
        description="user 消息携带的附件 FileItem 列表；assistant 消息恒为空",
    )
    trace_items: list[TraceItemModel] = Field(
        default_factory=list,
        description="该轮 assistant 报告各角标对应的 claim+证据预览；刷新历史会话时供角标 hover tooltip 直接使用，免去逐条 /evidence/resolve。user 消息恒为空",
    )
    citation_coverage: CitationCoverageModel = Field(
        default_factory=CitationCoverageModel,
        description="该轮报告的角标覆盖率快照，供报告顶部覆盖率警告条在历史会话中复现",
    )
    unresolved_relations: list[UnresolvedRelationItemModel] = Field(
        default_factory=list,
        description="该轮未决关系，供『待补件 N』badge 在历史会话中复现",
    )
    unresolved_claims: list[UnresolvedClaimItemModel] = Field(
        default_factory=list,
        description="该轮未决断言，供『待补件 N』badge 在历史会话中复现",
    )
    audit_review_stage: str = Field(default="", description="年审人工确认阶段")
    active_template_versions: dict[str, str] = Field(
        default_factory=dict, description="该轮使用的已激活模板版本"
    )
    attachment_package: dict[str, Any] = Field(
        default_factory=dict, description="该轮生成的年审附件包及预览/下载地址"
    )


class ThreadMessagesResponse(BaseModel):
    """Thread messages response."""
    thread_id: str = Field(description="会话线程 ID")
    messages: list[MessageItem] = Field(description="消息列表")
    message_count: int = Field(description="消息总数")


@router.get(
    "/threads/{thread_id}/messages",
    summary="获取会话消息历史",
    description=(
        "返回指定会话线程的完整消息历史记录。"
        "\n\n包含所有用户输入和 AI 回复，按时间顺序排列。"
    ),
    response_model=ThreadMessagesResponse,
)
async def get_thread_messages(thread_id: str,
                              identity: Identity = Depends(require_module("report"))):
    """Get all messages from a conversation thread."""
    try:
        if get_settings().auth_enabled:
            require_thread_access(thread_id, identity)
        service = get_conversation_service()
        messages = service.get_thread_messages(thread_id)

        # 报告段落分权：历史里 assistant 报告正文按可见 section_code 过滤
        visible_sections = visible_report_sections(identity)
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("content"):
                msg["content"] = filter_report_text_by_sections(msg["content"], visible_sections)

        message_items = [MessageItem(**msg) for msg in messages]

        return ThreadMessagesResponse(
            thread_id=thread_id,
            messages=message_items,
            message_count=len(message_items),
        )
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.exception("get_thread_messages_failed thread_id=%s error=%s", thread_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to get thread messages: {str(exc)}")


# ── Aggregate turns (user + assistants per turn_id) ──────────────────────

class AssistantTurnItem(BaseModel):
    """One assistant record within a turn group."""
    turn_id: str = Field(description="轮次 ID")
    role: str = Field(default="assistant", description="角色")
    content: str = Field(description="回复正文")
    final_report_ref: str = Field(default="", description="最终报告引用")
    intent: str = Field(default="", description="本轮意图")
    case_id: int = Field(default=0, description="关联案件 ID")
    route_decision: RouteDecisionModel | None = Field(
        default=None,
        description="该 assistant 版本自己的路由快照；不会回退为线程最新路由。",
    )
    trace_items: list[TraceItemModel] = Field(
        default_factory=list,
        description="该 assistant 版本自己的引用 claim + 证据快照。",
    )
    citation_coverage: CitationCoverageModel = Field(
        default_factory=CitationCoverageModel,
        description="该 assistant 版本自己的角标覆盖率快照。",
    )
    response_analysis_runs: list[dict[str, Any]] | None = Field(
        default=None,
        description="该 assistant 版本实际执行的年审分析运行范围。",
    )
    unresolved_relations: list[UnresolvedRelationItemModel] = Field(
        default_factory=list,
        description="该 assistant 版本自己的未决关系快照。",
    )
    unresolved_claims: list[UnresolvedClaimItemModel] = Field(
        default_factory=list,
        description="该 assistant 版本自己的未决断言快照。",
    )
    audit_review_stage: str = Field(default="", description="年审人工确认阶段")
    active_template_versions: dict[str, str] = Field(
        default_factory=dict, description="该 assistant 版本使用的已激活模板版本"
    )
    attachment_package: dict[str, Any] = Field(
        default_factory=dict, description="该 assistant 版本生成的年审附件包"
    )
    version: int = Field(default=1, description="生成版本号，1=首次，2+=重新生成")
    created_at: str = Field(default="", description="创建时间 ISO 格式")


class UserTurnItem(BaseModel):
    """User record within a turn group."""
    turn_id: str = Field(description="轮次 ID")
    role: str = Field(default="user", description="角色")
    content: str = Field(description="用户输入")
    created_at: str = Field(default="", description="创建时间 ISO 格式")
    uploaded_files: list[FileItem] = Field(
        default_factory=list,
        description="本轮 user 消息携带的附件 FileItem 列表",
    )


class TurnGroup(BaseModel):
    """A single turn: one user message + 0..N assistant records."""
    turn_id: str = Field(description="轮次 ID")
    user: UserTurnItem = Field(description="用户消息")
    assistants: list[AssistantTurnItem] = Field(description="该轮所有 AI 回复（支持重新生成多版本）")


class ThreadTurnsResponse(BaseModel):
    """Thread turns aggregate response."""
    thread_id: str = Field(description="会话线程 ID")
    turns: list[TurnGroup] = Field(description="轮次列表")
    turn_count: int = Field(description="轮次总数")


def _turn_graph_context(raw_context: Any) -> dict[str, Any]:
    """Validate one persisted assistant graph snapshot for the ``/turns`` API.

    The history table is long lived and may contain records written before the
    graph context contract existed.  A malformed legacy item must not make a
    whole thread unreadable; it is skipped and the remaining response-scoped
    snapshot is still returned.
    """
    context = raw_context if isinstance(raw_context, dict) else {}

    def _models(value: Any, model_type: type[BaseModel]) -> list[BaseModel]:
        if not isinstance(value, list):
            return []
        results: list[BaseModel] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            try:
                results.append(model_type.model_validate(item))
            except ValueError:
                continue
        return results

    raw_route = context.get("route_decision")
    route_decision: RouteDecisionModel | None = None
    if isinstance(raw_route, dict) and raw_route.get("capability"):
        try:
            route_decision = RouteDecisionModel.model_validate(raw_route)
        except ValueError:
            route_decision = None

    raw_coverage = context.get("citation_coverage")
    try:
        citation_coverage = CitationCoverageModel.model_validate(
            raw_coverage if isinstance(raw_coverage, dict) else {}
        )
    except ValueError:
        citation_coverage = CitationCoverageModel()

    return {
        "route_decision": route_decision,
        "trace_items": _models(context.get("trace_items"), TraceItemModel),
        "citation_coverage": citation_coverage,
        # ``None`` means this is a legacy reply written before the response
        # scope contract existed.  An explicit empty list means a new reply
        # deliberately had no completed analysis run.
        "response_analysis_runs": (
            _response_analysis_runs(context.get("response_analysis_runs"))
            if "response_analysis_runs" in context
            else None
        ),
        "unresolved_relations": _models(
            context.get("unresolved_relations"), UnresolvedRelationItemModel
        ),
        "unresolved_claims": _models(
            context.get("unresolved_claims"), UnresolvedClaimItemModel
        ),
        "audit_review_stage": str(context.get("audit_review_stage") or ""),
        "active_template_versions": (
            context.get("active_template_versions")
            if isinstance(context.get("active_template_versions"), dict)
            else {}
        ),
        "attachment_package": (
            context.get("attachment_package")
            if isinstance(context.get("attachment_package"), dict)
            else {}
        ),
    }


def _recover_legacy_attachment_package(case_id: int, content: str) -> dict[str, Any]:
    """Recover package actions for replies written before metadata persistence.

    Older assistant rows already contain the human-readable ``附件包 vN``
    response, but their graph snapshot did not store the artifact URLs.  This
    small compatibility lookup keeps those existing replies actionable after a
    refresh; new replies use the response-scoped snapshot directly.
    """

    match = re.search(r"附件包\s*v(\d+)", content or "")
    if case_id <= 0 or not match:
        return {}
    try:
        package_version = int(match.group(1))
        with mysql_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, package_version, status, artifact_refs_json
                    FROM annual_audit_attachment_package
                    WHERE engagement_id = %s AND package_version = %s
                    LIMIT 1
                    """,
                    (case_id, package_version),
                )
                row = dict(cursor.fetchone() or {})
        if not row:
            return {}
        raw_refs = row.get("artifact_refs_json")
        refs = json.loads(raw_refs) if isinstance(raw_refs, str) else raw_refs
        artifacts = []
        for index, item in enumerate(refs if isinstance(refs, list) else []):
            if not isinstance(item, dict):
                continue
            artifacts.append(
                {
                    key: item.get(key)
                    for key in (
                        "artifact_type",
                        "file_name",
                        "template_version",
                        "template_fill_status",
                    )
                    if item.get(key) is not None
                }
                | {
                    "download_url": f"/api/annual-audit/{case_id}/attachment-packages/{row['id']}/files/{index}",
                    "preview_url": f"/api/annual-audit/{case_id}/attachment-packages/{row['id']}/files/{index}/preview",
                }
            )
        return {
            "package_id": row.get("id"),
            "package_version": row.get("package_version"),
            "status": row.get("status") or "",
            "artifacts": artifacts,
        }
    except Exception:
        LOGGER.warning("legacy_attachment_package_recovery_failed case_id=%s", case_id, exc_info=True)
        return {}


@router.get(
    "/threads/{thread_id}/turns",
    summary="获取会话轮次聚合列表",
    description=(
        "返回按 turn_id 聚合的轮次列表，每个轮次包含一条 user 消息"
        "和该轮所有 assistant 回复（支持 regenerate 多版本）。"
        "\n\n前端可按 1/3, 2/3 分页渲染。"
    ),
    response_model=ThreadTurnsResponse,
)
async def get_thread_turns(thread_id: str, identity: Identity = Depends(require_module("report"))):
    """Get conversation turns grouped by turn_id."""
    try:
        if get_settings().auth_enabled:
            require_thread_access(thread_id, identity)
        repo = get_conversation_message_repo()
        raw_turns = repo.get_turns(thread_id)

        visible_sections = visible_report_sections(identity)
        turns: list[TurnGroup] = []
        for t in raw_turns:
            user_data = t.get("user")
            user_msg = None
            if user_data:
                created_at = ""
                if user_data.get("created_at"):
                    if isinstance(user_data["created_at"], datetime.datetime):
                        created_at = user_data["created_at"].isoformat()
                    else:
                        created_at = str(user_data["created_at"])
                user_msg = UserTurnItem(
                    turn_id=t["turn_id"],
                    content=user_data["content"],
                    created_at=created_at,
                    uploaded_files=user_data.get("uploaded_files") or [],
                )

            assistants: list[AssistantTurnItem] = []
            for a in t.get("assistants") or []:
                created_at = ""
                if a.get("created_at"):
                    if isinstance(a["created_at"], datetime.datetime):
                        created_at = a["created_at"].isoformat()
                    else:
                        created_at = str(a["created_at"])
                graph_context = _turn_graph_context(a.get("graph_context"))
                if not graph_context["attachment_package"]:
                    recovered_package = _recover_legacy_attachment_package(
                        int(a.get("case_id") or 0), str(a.get("content") or "")
                    )
                    if recovered_package:
                        graph_context["attachment_package"] = recovered_package
                        graph_context["audit_review_stage"] = "attachments_generated"
                assistants.append(
                    AssistantTurnItem(
                        turn_id=t["turn_id"],
                        content=filter_report_text_by_sections(a["content"], visible_sections),
                        final_report_ref=a.get("final_report_ref") or "",
                        intent=a.get("intent") or "",
                        case_id=a.get("case_id") or 0,
                        route_decision=graph_context["route_decision"],
                        trace_items=graph_context["trace_items"],
                        citation_coverage=graph_context["citation_coverage"],
                        response_analysis_runs=graph_context["response_analysis_runs"],
                        unresolved_relations=graph_context["unresolved_relations"],
                        unresolved_claims=graph_context["unresolved_claims"],
                        audit_review_stage=graph_context["audit_review_stage"],
                        active_template_versions=graph_context["active_template_versions"],
                        attachment_package=graph_context["attachment_package"],
                        version=a.get("version", 1),
                        created_at=created_at,
                    )
                )

            if user_msg is not None:
                turns.append(
                    TurnGroup(
                        turn_id=t["turn_id"],
                        user=user_msg,
                        assistants=assistants,
                    )
                )

        return ThreadTurnsResponse(
            thread_id=thread_id,
            turns=turns,
            turn_count=len(turns),
        )
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.exception("get_thread_turns_failed thread_id=%s error=%s", thread_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to get thread turns: {str(exc)}")

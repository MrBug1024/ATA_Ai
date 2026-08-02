# ============================================================================
# AI 猎手 FastAPI — 12 个 Endpoint 完整实现
#
# 启动方式：
#   pip install fastapi uvicorn psycopg2-binary openai httpx
#   export LLM_PROVIDER=gemini          # 或 minimax
#   export GEMINI_API_KEY=your-key      # 或 MINIMAX_API_KEY=your-key
#   export PG_DSN="host=localhost dbname=ai_hunter user=hunter password=xxx"
#   uvicorn ai_hunter.app.main:app --host 0.0.0.0 --port 8081 --reload
#
# Endpoint 清单：
#   写入类（3个）：createCase / fetchEnterprise / ingestStructuredFields
#   引擎类（4个）：auditDeltaCheck / auditValuationSqueeze / auditDeadlineScan / auditBehavioralScan
#   查询类（3个）：getCaseProfile / getWhitegloveAnalysis / getFundFlow
#   任务类（2个）：createTaskBatch / manageTasks
# ============================================================================

from fastapi import FastAPI, HTTPException, Request, Query, Path
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional, Any
from datetime import date, datetime
import concurrent.futures
import hashlib
import httpx
import json
import logging
import os
import re
import time
import traceback
import uuid

from . import db, llm_client
from .config import AUDIT_API_TOKEN, LLM_PROVIDER, QICHACHA_API_KEY, QICHACHA_SECRET_KEY, QICHACHA_BASE_URL, \
    CPWS_EMBED_DIM

logger = logging.getLogger("ai_hunter.domain_engine")

# ---------------------------------------------------------------------------
# 脱敏工具
# ---------------------------------------------------------------------------
_SENSITIVE_KEYS = re.compile(r"(api_key|password|secret|token|authorization)", re.I)

def _sanitize(text: str, max_len: int = 20000) -> str:
    """截断 + 脱敏"""
    if not text:
        return ""
    for m in _SENSITIVE_KEYS.finditer(text):
        pass  # 脱敏在 JSON 层面处理
    return text[:max_len] + ("...[truncated]" if len(text) > max_len else "")


def _extract_case_id(body: str) -> Optional[int]:
    """从 request body 中提取 case_id"""
    try:
        data = json.loads(body)
        cid = data.get("case_id")
        return int(cid) if cid is not None else None
    except Exception:
        return None


def _path_to_endpoint_name(path: str) -> str:
    """将 URL 路径转为易读端点名"""
    mapping = {
        "/api/ingest/case": "createCase",
        "/api/ingest/enterprise": "fetchEnterprise",
        "/api/ingest/doc-categories": "getDocCategories",
        "/api/ingest/structured-fields": "ingestStructuredFields",
        "/api/ingest/validate-doc-category": "validateDocCategory",
        "/api/audit/delta-check": "auditDeltaCheck",
        "/api/audit/valuation-squeeze": "auditValuationSqueeze",
        "/api/audit/deadline-scan": "auditDeadlineScan",
        "/api/audit/behavioral-scan": "auditBehavioralScan",
        "/api/tasks/create-batch": "createTaskBatch",
        "/api/tasks/manage": "manageTasks",
    }
    # 处理带路径参数的端点
    if "/api/case/" in path:
        if path.endswith("/profile"):
            return "getCaseProfile"
        elif path.endswith("/doc-categories"):
            return "getCaseDocCategories"
        elif path.endswith("/whiteglove"):
            return "getWhitegloveAnalysis"
        elif path.endswith("/fund-flow"):
            return "getFundFlow"
    return mapping.get(path, path)


app = FastAPI(title="AI猎手领域引擎", version="7.2")

# 注册子模块路由
from .documents import router as doc_parser_router
app.include_router(doc_parser_router, tags=["文档解析"])

# ---------------------------------------------------------------------------
# HTTP Middleware — 请求/响应日志 + DB 持久化
# ---------------------------------------------------------------------------
_SKIP_LOG_PATHS = {"/health", "/api/v1/check","/api/v1/rpc", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}


@app.middleware("http")
async def log_requests(request: Request, call_next):
    path = request.url.path
    if path in _SKIP_LOG_PATHS:
        return await call_next(request)

    request_id = str(uuid.uuid4())[:12]
    method = request.method
    client_ip = request.client.host if request.client else "-"
    query_params = str(request.query_params) if request.query_params else ""

    # 读取 request body
    body_bytes = await request.body()
    body_text = body_bytes.decode("utf-8", errors="replace") if body_bytes else ""

    start_time = time.time()
    error_message = None
    response_status = 500
    response_text = ""

    try:
        response = await call_next(request)
        response_status = response.status_code

        # 读取 response body
        resp_body_parts = []
        async for chunk in response.body_iterator:
            if isinstance(chunk, bytes):
                resp_body_parts.append(chunk)
            else:
                resp_body_parts.append(chunk.encode("utf-8"))
        resp_bytes = b"".join(resp_body_parts)
        response_text = resp_bytes.decode("utf-8", errors="replace")

        # 重建 response（原始 body_iterator 已消耗）
        response = Response(
            content=resp_bytes,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
    except Exception as exc:
        error_message = traceback.format_exc()
        logger.error("[%s] %s %s → 异常: %s", request_id, method, path, str(exc))
        raise
    finally:
        duration_ms = int((time.time() - start_time) * 1000)
        case_id = _extract_case_id(body_text)
        # 对路径参数中的 case_id 也提取
        if case_id is None and "/api/case/" in path:
            try:
                parts = path.split("/")
                idx = parts.index("case") + 1
                if idx < len(parts):
                    case_id = int(parts[idx])
            except (ValueError, IndexError):
                pass

        endpoint_name = _path_to_endpoint_name(path)

        logger.info(
            "[%s] %s %s → %d (%dms) | case_id=%s | ip=%s | ep=%s",
            request_id, method, path, response_status, duration_ms,
            case_id, client_ip, endpoint_name,
        )

        # 持久化到 api_call_logs
        try:
            db.execute("""
                INSERT INTO api_call_logs
                    (request_id, method, path, query_params, request_body,
                     response_status, response_body, duration_ms, client_ip,
                     case_id, endpoint_name, error_message)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                request_id, method, path,
                _sanitize(query_params, 500),
                _sanitize(body_text),
                response_status,
                _sanitize(response_text),
                duration_ms, client_ip,
                case_id, endpoint_name,
                _sanitize(error_message or "", 2000) or None,
            ))
        except Exception as log_err:
            logger.warning("日志写入DB失败: %s", log_err)

    return response


# ============================================================================
# 请求模型
# ============================================================================

class CreateCaseReq(BaseModel):
    case_name: str = Field(description="案件名称。")
    case_type: Literal["单户", "资产包", "破产重整", "执转破"] = "破产重整"
    debtor_name: str = Field(description="债务人名称；建案强主数据，不从资产购买方或卷宗标题推断。")
    debtor_uscc: Optional[str] = Field(default=None, description="债务人统一社会信用代码。")
    asset_purchaser_name: Optional[str] = Field(
        default=None,
        description="可选资产购买方名称；写入 case_party 的 asset_purchaser 角色，不写入 debtors。",
    )
    company_id: Optional[str] = None
    owner_id: Optional[str] = None
    created_by: Optional[str] = None


CasePartyRole = Literal[
    "debtor",
    "asset_purchaser",
    "creditor",
    "guarantor",
    "administrator",
    "other",
]
ManageableCasePartyRole = Literal[
    "asset_purchaser",
    "creditor",
    "guarantor",
    "administrator",
    "other",
]


class CasePartyUpsertReq(BaseModel):
    party_name: str = Field(min_length=1, max_length=200, description="参与方名称。")
    party_role: ManageableCasePartyRole = Field(
        description="非债务人角色；债务人必须通过建案或债务人专项流程维护。",
    )
    uscc: Optional[str] = Field(default=None, max_length=32, description="统一社会信用代码。")
    is_primary: bool = Field(default=False, description="是否为同角色下的主要参与方。")
    status: Literal["active", "disabled"] = Field(
        default="active",
        description="参与方状态；disabled 为软禁用，保留审计记录。",
    )
    extra_fields: dict[str, Any] = Field(
        default_factory=dict,
        description="非核心扩展信息；名称和角色不得只写在此字段。",
    )


class CasePartyItem(BaseModel):
    party_id: int = Field(description="参与方记录ID。")
    case_id: int = Field(description="案件ID。")
    debtor_id: Optional[int] = Field(default=None, description="债务人专项记录ID；仅 debtor 角色存在。")
    party_name: str = Field(description="参与方名称。")
    party_role: CasePartyRole = Field(description="参与方角色编码。")
    uscc: Optional[str] = Field(default=None, description="统一社会信用代码。")
    is_primary: bool = Field(description="是否为同角色下的主要参与方。")
    status: Literal["active", "disabled"] = Field(description="参与方状态。")
    source_type: str = Field(description="角色来源。")
    extra_fields: dict[str, Any] = Field(default_factory=dict, description="扩展信息。")
    created_by: str = Field(default="", description="登记人用户ID。")
    created_at: Optional[str] = Field(default=None, description="创建时间。")
    updated_at: Optional[str] = Field(default=None, description="最近更新时间。")


class CasePartyListResp(BaseModel):
    case_id: int = Field(description="案件ID。")
    parties: list[CasePartyItem] = Field(description="案件参与方列表。")


class CaseMemberUpsertReq(BaseModel):
    member_role: str = Field(default="", description="案件内角色，如 operator/auditor/reviewer/viewer。")
    status: Literal["active", "disabled"] = Field(
        default="active",
        description="成员状态；disabled 表示软移除，保留成员关系审计记录。",
    )


class CaseMemberItem(BaseModel):
    case_id: int = Field(description="案件ID。")
    company_id: str = Field(description="案件所属公司ID。")
    user_id: str = Field(description="成员用户ID。")
    username: str = Field(default="", description="成员用户名。")
    member_role: str = Field(default="", description="案件内角色。")
    status: Literal["active", "disabled"] = Field(description="成员状态。")
    added_by: str = Field(default="", description="最近添加或更新该成员的操作人ID。")
    created_at: Optional[str] = Field(default=None, description="成员关系创建时间。")
    updated_at: Optional[str] = Field(default=None, description="成员关系更新时间。")


class CaseMemberListResp(BaseModel):
    case_id: int = Field(description="案件ID。")
    company_id: str = Field(description="案件所属公司ID。")
    members: list[CaseMemberItem] = Field(description="案件成员列表。")

class FetchEnterpriseReq(BaseModel):
    case_id: int
    company_name: str
    depth: int = 2

class IngestFieldsReq(BaseModel):
    case_id: int
    debtor_id: int
    doc_category: str
    fields: dict

class ValidateDocCategoryReq(BaseModel):
    case_id: int = Field(..., description="案件ID，对应 cases.case_id")
    doc_category: str = Field(
        ...,
        description="用户选择的标准卷宗类别 code 或中文名，例如 judgment / 判决书",
        examples=["judgment"],
    )
    file_names: list[str] = Field(
        default_factory=list,
        description="待上传文件名列表，用于同名重复检测和类别关键词初筛",
        examples=[["判决书.pdf", "资产负债表.xlsx"]],
    )
    text_preview: Optional[str] = Field(
        default=None,
        description="可选的 OCR/文本预览片段，用于上传前判断类别是否选错；不传则只用文件名判断",
    )

class DocCategoryItem(BaseModel):
    code: str = Field(..., description="标准类别 code，供前端和 Dify 稳定传参使用")
    name: str = Field(..., description="中文类别名")
    description: Optional[str] = Field(None, description="类别说明")
    sort_order: int = Field(..., description="前端展示顺序")
    enabled: bool = Field(..., description="是否启用")
    fields: list[str] = Field(default_factory=list, description="该类别可抽取/入库的字段名")

class DocCategoriesResp(BaseModel):
    categories: list[DocCategoryItem] = Field(..., description="标准卷宗类别字典，当前为13类")

class CaseDocCategoryCoverageItem(BaseModel):
    code: str = Field(..., description="标准类别 code")
    name: str = Field(..., description="中文类别名")
    uploaded: bool = Field(..., description="该案件是否已覆盖该类资料；file_count 或 record_count 大于0即为 true")
    file_count: int = Field(..., description="source_file_doc_category 关联到该类别的文件数")
    record_count: int = Field(..., description="该类别对应业务表中的结构化记录数")
    last_uploaded_at: Optional[str] = Field(None, description="最近一次上传/更新文件时间，ISO 字符串")

class CaseDocCategoriesResp(BaseModel):
    case_id: int = Field(..., description="案件ID")
    categories: list[CaseDocCategoryCoverageItem] = Field(..., description="13类资料覆盖明细")
    missing_categories: list[str] = Field(..., description="尚未覆盖的类别 code 列表")

class ValidateDocCategoryResp(BaseModel):
    ok: bool = Field(..., description="类别初检是否通过；类别疑似不匹配时为 false")
    suspected_mismatch: bool = Field(..., description="是否疑似选错类别")
    suspected_duplicate: bool = Field(..., description="是否疑似重复上传")
    content_check_performed: bool = Field(..., description="是否完成了基于文本/文件名特征的类别匹配校验")
    message: str = Field(..., description="给前端/工作流展示的校验说明")

class AuditReq(BaseModel):
    case_id: int
    mining_transfer_prices: Optional[dict] = None  # {mine_name: price} 矿权协议转让底价，用于价值倒挂探测
    recompute: bool = False  # True 则强制重算 get_full_context（跳过缓存），默认走缓存

class TaskBatchReq(BaseModel):
    case_id: int
    tasks: list

class ManageTaskReq(BaseModel):
    case_id: int
    action: str  # list / update / assign / summary
    filter_status: Optional[str] = None
    task_id: Optional[int] = None
    new_status: Optional[str] = None
    completion_note: Optional[str] = None
    assigned_to: Optional[str] = None


# ---------------------------------------------------------------------------
# 辅助函数：建案去重
# ---------------------------------------------------------------------------
def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _has_service_token(request: Request) -> bool:
    """Return whether request carries the shared ai_hunter -> NpaDemo token."""
    expected = (AUDIT_API_TOKEN or "").strip()
    if not expected:
        return False
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return False
    return auth[7:].strip() == expected


def _trusted_admin_flags(
    request: Request,
    *,
    is_company_admin: bool,
    is_super_admin: bool,
) -> tuple[bool, bool]:
    """Only trust admin query flags from authenticated service callers."""
    if not _has_service_token(request):
        if _is_truthy(is_company_admin) or _is_truthy(is_super_admin):
            logger.warning("[Tenancy] 忽略未认证调用方传入的管理员标记")
        return False, False
    return _is_truthy(is_company_admin), _is_truthy(is_super_admin)


def _case_visibility_clause(
    *,
    company_id: Optional[str],
    user_id: Optional[str],
    is_company_admin: bool = False,
    is_super_admin: bool = False,
    table_alias: str = "c",
) -> tuple[list[str], list[Any]]:
    """Build tenant visibility SQL for cases.

    不传 company_id 时保留历史内部调用行为；ai_hunter v2-B 会始终传入租户上下文。
    """
    company_id = (company_id or "").strip()
    user_id = (user_id or "").strip()
    if is_super_admin or not company_id:
        return [], []

    clauses = [f"{table_alias}.company_id = %s"]
    params: list[Any] = [company_id]
    if not is_company_admin:
        if not user_id:
            clauses.append("FALSE")
            return clauses, params
        clauses.append(f"""
            (
                {table_alias}.owner_id = %s
                OR EXISTS (
                    SELECT 1
                    FROM case_member cm
                    WHERE cm.case_id = {table_alias}.case_id
                      AND cm.company_id = {table_alias}.company_id
                      AND cm.user_id = %s
                      AND cm.status = 'active'
                )
            )
        """)
        params.extend([user_id, user_id])
    return clauses, params


def _require_service_token(request: Request) -> None:
    """Reject tenant administration calls that are not from the trusted service."""
    if not _has_service_token(request):
        raise HTTPException(401, "缺少有效的服务间 Authorization Bearer token")


def _get_visible_case(
    request: Request,
    *,
    case_id: int,
    company_id: Optional[str],
    user_id: Optional[str],
    is_company_admin: bool,
    is_super_admin: bool,
) -> tuple[dict, bool, bool]:
    """Load a case under the same tenant visibility rules used by list/profile."""
    trusted_company_admin, trusted_super_admin = _trusted_admin_flags(
        request,
        is_company_admin=is_company_admin,
        is_super_admin=is_super_admin,
    )
    clauses = ["c.case_id = %s"]
    params: list[Any] = [case_id]
    visibility_clauses, visibility_params = _case_visibility_clause(
        company_id=company_id,
        user_id=user_id,
        is_company_admin=trusted_company_admin,
        is_super_admin=trusted_super_admin,
        table_alias="c",
    )
    clauses.extend(visibility_clauses)
    params.extend(visibility_params)
    case = db.query_one(
        f"SELECT c.case_id, c.company_id, c.owner_id FROM cases c WHERE {' AND '.join(clauses)}",
        tuple(params),
    )
    if not case:
        raise HTTPException(404, "案件不存在或无权访问")
    return dict(case), trusted_company_admin, trusted_super_admin


def _normalize_entity_name(name: Optional[str]) -> str:
    """企业名称规范化：去首尾空白并移除中间空白字符"""
    if not name:
        return ""
    return re.sub(r"\s+", "", str(name)).strip()


def _find_existing_case(
    debtor_name: str,
    debtor_uscc: Optional[str] = None,
    *,
    company_id: Optional[str] = None,
) -> Optional[dict]:
    """
    查找可复用案件：
    1. 优先按 USCC 精确匹配
    2. 其次按规范化后的债务人名称匹配
    返回 {case_id, debtor_id, case_name}
    """
    normalized_name = _normalize_entity_name(debtor_name)
    normalized_uscc = (debtor_uscc or "").strip().upper()
    tenant_where = ""
    tenant_params: list[Any] = []
    if (company_id or "").strip():
        tenant_where = " AND c.company_id = %s"
        tenant_params.append(company_id.strip())

    if normalized_uscc:
        row = db.query_one("""
            SELECT d.case_id, d.debtor_id, c.case_name
            FROM debtors d
            JOIN cases c ON c.case_id = d.case_id
            WHERE upper(coalesce(d.uscc, '')) = %s
              {tenant_where}
            ORDER BY c.created_at DESC, d.debtor_id DESC
            LIMIT 1
        """.format(tenant_where=tenant_where), tuple([normalized_uscc] + tenant_params))
        if row:
            return dict(row)

    if normalized_name:
        row = db.query_one(r"""
            SELECT d.case_id, d.debtor_id, c.case_name
            FROM debtors d
            JOIN cases c ON c.case_id = d.case_id
            WHERE regexp_replace(coalesce(d.entity_name, ''), '\s+', '', 'g') = %s
              {tenant_where}
            ORDER BY c.created_at DESC, d.debtor_id DESC
            LIMIT 1
        """.format(tenant_where=tenant_where), tuple([normalized_name] + tenant_params))
        if row:
            return dict(row)

    return None


# ---------------------------------------------------------------------------
# 辅助函数：UPSERT 综合风险评分
# ---------------------------------------------------------------------------
_RISK_WEIGHTS = {"delta": 0.30, "behavioral": 0.30, "valuation": 0.25, "deadline": 0.15}


def _upsert_risk_score(case_id: int, **scores):
    """
    UPSERT audit_risk_scores 并自动重算 composite_score。
    调用示例: _upsert_risk_score(1, delta_score=75.5)
    """
    existing = db.query_one("SELECT * FROM audit_risk_scores WHERE case_id=%s", (case_id,))

    ds = scores.get("delta_score", float(existing["delta_score"]) if existing and existing.get("delta_score") is not None else None)
    vs = scores.get("valuation_score", float(existing["valuation_score"]) if existing and existing.get("valuation_score") is not None else None)
    dls = scores.get("deadline_score", float(existing["deadline_score"]) if existing and existing.get("deadline_score") is not None else None)
    bs = scores.get("behavioral_score", float(existing["behavioral_score"]) if existing and existing.get("behavioral_score") is not None else None)

    # 加权平均（仅对已有值的引擎）。这里 Python 侧只为 INSERT 首插提供一个值；
    # UPDATE 分支的 composite_score 改由 SQL 用 COALESCE 后的最终行重算，
    # 以消除“四引擎并发各自 read-modify-write 同一行”导致的 composite 丢更新/算错。
    parts, weight_sum = 0.0, 0.0
    for val, key in [(ds, "delta"), (vs, "valuation"), (dls, "deadline"), (bs, "behavioral")]:
        if val is not None:
            parts += val * _RISK_WEIGHTS[key]
            weight_sum += _RISK_WEIGHTS[key]
    composite = round(parts / weight_sum, 2) if weight_sum > 0 else None

    cross_hits = scores.get("cross_hits")
    details = scores.get("details")

    # 并发安全的 composite：在单条 UPSERT 内基于 COALESCE 合并后的最终四项分数计算，
    # 而非依赖调用方读到的 stale 快照。权重取自 _RISK_WEIGHTS（单一来源，避免漂移）。
    w = _RISK_WEIGHTS
    _m = {  # 合并后的各项分数表达式（EXCLUDED 优先，回退现有行）
        "delta": "COALESCE(EXCLUDED.delta_score, audit_risk_scores.delta_score)",
        "valuation": "COALESCE(EXCLUDED.valuation_score, audit_risk_scores.valuation_score)",
        "deadline": "COALESCE(EXCLUDED.deadline_score, audit_risk_scores.deadline_score)",
        "behavioral": "COALESCE(EXCLUDED.behavioral_score, audit_risk_scores.behavioral_score)",
    }
    composite_sql = (
        "round((" + " + ".join(f"COALESCE({_m[k]} * {w[k]}, 0)" for k in _m) + ") / NULLIF("
        + " + ".join(f"(CASE WHEN {_m[k]} IS NOT NULL THEN {w[k]} ELSE 0 END)" for k in _m)
        + ", 0), 2)"
    )

    db.execute(f"""
        INSERT INTO audit_risk_scores
            (case_id, delta_score, valuation_score, deadline_score, behavioral_score,
             composite_score, cross_hits, details, calculated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, now())
        ON CONFLICT (case_id) DO UPDATE SET
            delta_score     = COALESCE(EXCLUDED.delta_score, audit_risk_scores.delta_score),
            valuation_score = COALESCE(EXCLUDED.valuation_score, audit_risk_scores.valuation_score),
            deadline_score  = COALESCE(EXCLUDED.deadline_score, audit_risk_scores.deadline_score),
            behavioral_score= COALESCE(EXCLUDED.behavioral_score, audit_risk_scores.behavioral_score),
            composite_score = {composite_sql},
            cross_hits      = COALESCE(EXCLUDED.cross_hits, audit_risk_scores.cross_hits),
            details         = COALESCE(EXCLUDED.details, audit_risk_scores.details),
            calculated_at   = now()
    """, (
        case_id, ds, vs, dls, bs, composite,
        json.dumps(cross_hits, ensure_ascii=False) if cross_hits else None,
        json.dumps(details, ensure_ascii=False) if details else None,
    ))
    return composite


# ---------------------------------------------------------------------------
# 标准卷宗类别（13类）与 source_file 分类辅助
# ---------------------------------------------------------------------------
DOC_CATEGORY_TABLE = "doc_category_catalog"
SOURCE_FILE_CATEGORY_TABLE = "source_file_doc_category"

STANDARD_DOC_CATEGORIES = [
    {
        "code": "loan_contract",
        "name": "贷款合同",
        "description": "贷款主合同、借款合同、授信合同等",
        "sort_order": 1,
        "enabled": True,
        "fields": [
            "principal", "interest", "penalty", "delayed_interest", "total_claim",
            "guarantee_type", "collateral_desc", "lien_priority", "court_name",
            "exec_case_no", "litigation_status", "guarantor_names",
        ],
        "keywords": ["贷款合同", "借款合同", "授信合同", "金融借款", "贷款本金", "罚息"],
    },
    {
        "code": "judgment",
        "name": "判决书",
        "description": "判决书、裁定书、调解书、执行裁定等法律文书",
        "sort_order": 2,
        "enabled": True,
        "fields": [
            "case_number", "court_name", "case_cause", "doc_type", "judgment_date",
            "claim_amount", "judgment_amount", "execution_status", "plaintiff",
            "defendant", "enforcement_deadline", "court_level", "case_type",
        ],
        "keywords": ["判决书", "裁定书", "调解书", "执行裁定", "民事判决", "案号", "本院认为"],
    },
    {
        "code": "financial_statement",
        "name": "财务报表",
        "description": "资产负债表、利润表、审计报告中的财务快照",
        "sort_order": 3,
        "enabled": True,
        "fields": [
            "report_period", "report_type", "other_receivables", "prepayments",
            "total_assets", "total_liabilities", "revenue", "operating_cost",
            "net_profit", "tax_reported_revenue", "tax_reported_cost",
        ],
        "keywords": ["财务报表", "资产负债表", "利润表", "审计报告", "营业收入", "净利润"],
    },
    {
        "code": "real_estate_cert",
        "name": "不动产权证",
        "description": "不动产权证、房产证、土地证等权属资料",
        "sort_order": 4,
        "enabled": True,
        "fields": [
            "property_owner", "property_address", "real_estate_cert_no", "land_nature",
            "total_building_area", "land_use_area", "property_usage", "mortgage_status",
            "seal_status", "seal_expiry", "lease_status", "gross_value",
            "has_title_objection", "physical_occupation", "lien_priority",
            "sealing_court", "lease_annual_rent", "lease_start", "lease_end",
        ],
        "keywords": ["不动产权证", "房产证", "土地使用权证", "不动产", "建筑面积", "坐落"],
    },
    {
        "code": "mining_permit",
        "name": "采矿许可证",
        "description": "采矿许可证、采矿权登记信息",
        "sort_order": 5,
        "enabled": True,
        "fields": [
            "mine_name", "mine_location", "permit_expiry", "production_scale",
            "mineral_type", "mine_scale", "mining_status", "safety_permit_status",
            "env_approval_status", "mining_right_mortgage", "mining_right_sealed",
            "proved_reserves", "estimated_value", "transfer_base_price",
            "in_ecological_redline",
        ],
        "keywords": ["采矿许可证", "采矿权", "矿区范围", "生产规模", "有效期限", "矿山名称"],
    },
    {
        "code": "bank_statement",
        "name": "银行流水",
        "description": "银行流水、交易明细、回单签批链",
        "sort_order": 6,
        "enabled": True,
        "fields": ["transactions"],
        "keywords": ["银行流水", "交易明细", "交易流水", "对账单", "付款人", "收款人"],
    },
    {
        "code": "guarantee_contract",
        "name": "担保合同",
        "description": "保证合同、担保合同、连带保证资料",
        "sort_order": 7,
        "enabled": True,
        "fields": ["entity_name", "guarantor_type", "guarantee_type", "guarantee_scope", "spouse_name"],
        "keywords": ["担保合同", "保证合同", "连带保证", "一般保证", "保证范围", "保证期间"],
    },
    {
        "code": "restructuring_plan",
        "name": "煤矿重整方案",
        "description": "破产重整方案、变价方案、分配方案等",
        "sort_order": 8,
        "enabled": True,
        "fields": [
            "mine_name", "debtor_name", "administrator", "administrator_contact",
            "investor_name", "investor_contact", "total_debt", "secured_debt",
            "unsecured_debt", "employee_debt", "tax_debt", "proposed_recovery_rate",
            "transfer_base_price", "asset_list_summary", "restructuring_timeline",
            "court_name", "case_number", "key_conditions",
        ],
        "keywords": ["重整方案", "破产重整", "管理人", "债权人会议", "清偿率", "变价方案", "分配方案"],
    },
    {
        "code": "exploration_report",
        "name": "勘探报告",
        "description": "勘探报告、地质报告、储量报告",
        "sort_order": 9,
        "enabled": True,
        "fields": [
            "mine_name", "report_org", "report_date", "mineral_type", "proved_reserves",
            "controlled_reserves", "inferred_resources", "total_reserves",
            "calorific_value", "ash_content_pct", "sulfur_content_pct", "coal_type",
        ],
        "keywords": ["勘探报告", "勘查报告", "地质报告", "储量报告", "探明储量", "煤层"],
    },
    {
        "code": "environmental_approval",
        "name": "环评批复",
        "description": "环评批复、环境影响评价审批文件",
        "sort_order": 10,
        "enabled": True,
        "fields": ["mine_name", "env_approval_status", "production_scale", "in_ecological_redline"],
        "keywords": ["环评批复", "环境影响", "环境影响评价", "环保审批", "生态红线"],
    },
    {
        "code": "court_general_query",
        "name": "法院总对总",
        "description": "法院总对总网络查控结果",
        "sort_order": 11,
        "enabled": True,
        "fields": [
            "target_name", "inquiry_date", "bank_deposits", "real_estate_hits",
            "vehicle_hits", "securities_hits", "insurance_hits", "other_hits",
        ],
        "keywords": ["总对总", "网络查控", "银行存款查询", "不动产查询", "车辆查询", "冻结"],
    },
    {
        "code": "lawyer_investigation",
        "name": "律师调查报告",
        "description": "律师实地调查、现场调查、经营核查报告",
        "sort_order": 12,
        "enabled": True,
        "fields": [
            "investigator", "investigation_date", "physical_address_status",
            "employee_status", "asset_on_site", "lease_situation",
            "investigation_conclusion", "key_person_contacts",
            "related_party_findings", "asset_transfer_clues",
        ],
        "keywords": ["律师调查", "实地调查", "现场调查", "调查报告", "人去楼空", "停业"],
    },
    {
        "code": "mining_design_reclamation",
        "name": "开采设计与复垦",
        "description": "开采设计、复垦方案、矿山恢复治理资料",
        "sort_order": 13,
        "enabled": True,
        "fields": ["mine_name", "annual_capacity", "mining_status"],
        "keywords": ["开采设计", "复垦", "恢复治理", "年度产能", "设计生产能力"],
    },
]

STANDARD_DOC_CATEGORY_BY_CODE = {item["code"]: item for item in STANDARD_DOC_CATEGORIES}
STANDARD_DOC_CATEGORY_BY_NAME = {item["name"]: item for item in STANDARD_DOC_CATEGORIES}
STANDARD_DOC_CATEGORY_ALIASES = {
    "执行裁定": "judgment",
    "审批单据": "bank_statement",
    "权证文件": "real_estate_cert",
}
DOC_CATEGORY_TABLE_FIELD_MAP = {
    "loan_contract": "claims",
    "judgment": "legal_documents",
    "financial_statement": "financial_snapshots",
    "real_estate_cert": "real_estate_evaluations",
    "mining_permit": "mining_evaluations",
    "guarantee_contract": "guarantors",
    "exploration_report": "mining_evaluations",
    "environmental_approval": "mining_evaluations",
    "mining_design_reclamation": "mining_evaluations",
}
DOC_CATEGORY_MULTI_UPLOAD = {
    "judgment", "financial_statement", "bank_statement", "guarantee_contract", "real_estate_cert",
}


def _table_exists(table_name: str) -> bool:
    row = db.query_one(
        """
        SELECT 1 AS ok
        FROM information_schema.tables
        WHERE table_schema='public' AND table_name=%s
        LIMIT 1
        """,
        (table_name,),
    )
    return bool(row)


def _safe_json_loads(text: Any) -> dict:
    if not text:
        return {}
    if isinstance(text, dict):
        return text
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _normalize_doc_category_value(value: str) -> Optional[dict]:
    raw = (value or "").strip()
    if not raw:
        return None
    alias = STANDARD_DOC_CATEGORY_ALIASES.get(raw, raw)
    if alias in STANDARD_DOC_CATEGORY_BY_CODE:
        return STANDARD_DOC_CATEGORY_BY_CODE[alias]
    if alias in STANDARD_DOC_CATEGORY_BY_NAME:
        return STANDARD_DOC_CATEGORY_BY_NAME[alias]
    return None


def _runtime_fields_for_category(meta: dict) -> list[str]:
    table = DOC_CATEGORY_TABLE_FIELD_MAP.get(meta["code"])
    if not table:
        return meta["fields"]
    live_cols = set(_get_table_columns(table))
    result = []
    for field in meta["fields"]:
        if field in live_cols or field in ("guarantor_names", "transactions"):
            result.append(field)
    return result


def _load_doc_categories() -> list[dict]:
    if _table_exists(DOC_CATEGORY_TABLE):
        rows = db.query(f"""
            SELECT code, name, description, sort_order, enabled, fields
            FROM {DOC_CATEGORY_TABLE}
            ORDER BY sort_order, code
        """)
        if rows:
            loaded = []
            for row in rows:
                data = dict(row)
                fields = data.get("fields")
                if isinstance(fields, str):
                    try:
                        fields = json.loads(fields)
                    except Exception:
                        fields = []
                if not isinstance(fields, list) or not fields:
                    fallback = STANDARD_DOC_CATEGORY_BY_CODE.get(data["code"])
                    fields = _runtime_fields_for_category(fallback) if fallback else []
                data["fields"] = fields
                loaded.append(data)
            return loaded

    return [
        {
            "code": item["code"],
            "name": item["name"],
            "description": item["description"],
            "sort_order": item["sort_order"],
            "enabled": item["enabled"],
            "fields": _runtime_fields_for_category(item),
        }
        for item in STANDARD_DOC_CATEGORIES
    ]


def _get_case_category_record_counts(case_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    counts["loan_contract"] = int(db.query_one("""
        SELECT count(*) AS c
        FROM claims
        WHERE case_id=%s
          AND coalesce(litigation_status, '') <> '重整中'
          AND coalesce(guarantee_type, '') NOT IN ('职工债权', '税款债权')
          AND coalesce(guarantee_type, '') NOT LIKE '重整方案%%'
    """, (case_id,))["c"])
    counts["judgment"] = int(db.query_one("SELECT count(*) AS c FROM legal_documents WHERE case_id=%s", (case_id,))["c"])
    counts["financial_statement"] = int(db.query_one("SELECT count(*) AS c FROM financial_snapshots WHERE case_id=%s", (case_id,))["c"])
    counts["real_estate_cert"] = int(db.query_one("SELECT count(*) AS c FROM real_estate_evaluations WHERE case_id=%s", (case_id,))["c"])
    counts["mining_permit"] = int(db.query_one("""
        SELECT count(*) AS c
        FROM mining_evaluations
        WHERE case_id=%s
          AND (
            permit_expiry IS NOT NULL OR mine_location IS NOT NULL OR mine_scale IS NOT NULL
            OR mining_right_mortgage IS NOT NULL OR mining_right_sealed IS NOT NULL
          )
    """, (case_id,))["c"])
    counts["bank_statement"] = int(db.query_one("SELECT count(*) AS c FROM transaction_signatures WHERE case_id=%s", (case_id,))["c"])
    counts["guarantee_contract"] = int(db.query_one("""
        SELECT count(*) AS c
        FROM guarantors
        WHERE case_id=%s
          AND (
            guarantee_type IS NOT NULL OR guarantee_scope IS NOT NULL OR spouse_name IS NOT NULL
          )
    """, (case_id,))["c"])
    counts["restructuring_plan"] = int(db.query_one("""
        SELECT
            (SELECT count(*) FROM contacts WHERE case_id=%s AND role IN ('破产管理人', '重整投资人'))
          + (SELECT count(*) FROM claims WHERE case_id=%s AND litigation_status='重整中')
          AS c
    """, (case_id, case_id))["c"])
    counts["exploration_report"] = int(db.query_one("""
        SELECT count(*) AS c
        FROM mining_evaluations
        WHERE case_id=%s
          AND (
            report_org IS NOT NULL OR report_date IS NOT NULL OR controlled_reserves IS NOT NULL
            OR inferred_resources IS NOT NULL OR total_reserves IS NOT NULL
            OR calorific_value IS NOT NULL OR ash_content_pct IS NOT NULL
            OR sulfur_content_pct IS NOT NULL OR coal_type IS NOT NULL
          )
    """, (case_id,))["c"])
    counts["environmental_approval"] = int(db.query_one("""
        SELECT count(*) AS c
        FROM mining_evaluations
        WHERE case_id=%s
          AND (
            env_approval_status IS NOT NULL
            OR (extra_fields ? 'approval_org')
            OR (extra_fields ? 'approval_number')
          )
    """, (case_id,))["c"])
    counts["court_general_query"] = int(db.query_one("""
        SELECT
            (SELECT count(*) FROM bank_accounts WHERE case_id=%s)
          + (SELECT count(*) FROM hidden_assets WHERE case_id=%s AND discovery_method='法院总对总')
          AS c
    """, (case_id, case_id))["c"])
    counts["lawyer_investigation"] = int(db.query_one("""
        SELECT
            (SELECT count(*) FROM risk_profiles WHERE case_id=%s AND data_source='律师调查')
          + (SELECT count(*) FROM related_persons WHERE case_id=%s)
          + (SELECT count(*) FROM hidden_assets WHERE case_id=%s AND discovery_method='律师调查')
          AS c
    """, (case_id, case_id, case_id))["c"])
    counts["mining_design_reclamation"] = int(db.query_one("""
        SELECT count(*) AS c
        FROM mining_evaluations
        WHERE case_id=%s AND annual_capacity IS NOT NULL
    """, (case_id,))["c"])
    return counts


def _get_case_category_file_stats(case_id: int) -> dict[str, dict]:
    stats = {
        item["code"]: {"file_count": 0, "last_uploaded_at": None}
        for item in STANDARD_DOC_CATEGORIES
    }

    if _table_exists(SOURCE_FILE_CATEGORY_TABLE):
        rows = db.query(f"""
            SELECT sfdc.category_code,
                   count(DISTINCT sf.id) AS file_count,
                   max(coalesce(sf.updated_at, sf.created_at)) AS last_uploaded_at
            FROM {SOURCE_FILE_CATEGORY_TABLE} sfdc
            JOIN source_file sf ON sf.id = sfdc.file_id
            WHERE sfdc.case_id=%s
            GROUP BY sfdc.category_code
        """, (case_id,))
        for row in rows:
            code = row["category_code"]
            if code in stats:
                stats[code] = {
                    "file_count": int(row["file_count"]),
                    "last_uploaded_at": row["last_uploaded_at"],
                }
        if rows:
            return stats

    file_rows = db.query("""
        SELECT id, file_name, created_at, updated_at
        FROM source_file
        WHERE case_id=%s
        ORDER BY created_at DESC
    """, (case_id,))
    if file_rows:
        chunk_rows = db.query("""
            SELECT file_id, chunk_text
            FROM source_chunk
            WHERE case_id=%s
            ORDER BY file_id, id
        """, (case_id,))
        chunk_map: dict[int, list[str]] = {}
        for row in chunk_rows:
            chunk_map.setdefault(int(row["file_id"]), []).append(row.get("chunk_text") or "")

        for file_row in file_rows:
            file_id = int(file_row["id"])
            full_text = ((file_row.get("file_name") or "") + "\n" + "\n".join(chunk_map.get(file_id, [])))[:40000]
            for meta in STANDARD_DOC_CATEGORIES:
                if any(keyword in full_text for keyword in meta["keywords"]):
                    current = stats[meta["code"]]
                    current["file_count"] += 1
                    ts = file_row.get("updated_at") or file_row.get("created_at")
                    if ts and (current["last_uploaded_at"] is None or ts > current["last_uploaded_at"]):
                        current["last_uploaded_at"] = ts
        return stats

    log_rows = db.query("""
        SELECT path, request_body, response_body, created_at
        FROM api_call_logs
        WHERE case_id=%s
          AND path IN ('/api/ingest/structured-fields', '/api/ingest/parse-document')
        ORDER BY created_at DESC
    """, (case_id,))
    for row in log_rows:
        path = row["path"]
        created_at = row["created_at"]
        req = _safe_json_loads(row.get("request_body"))
        resp = _safe_json_loads(row.get("response_body"))
        codes = set()
        if path == "/api/ingest/structured-fields":
            meta = _normalize_doc_category_value(req.get("doc_category", ""))
            if meta:
                codes.add(meta["code"])
        else:
            for name in resp.get("categories_found", []) or []:
                meta = _normalize_doc_category_value(name)
                if meta:
                    codes.add(meta["code"])
            for detail in resp.get("details", []) or []:
                meta = _normalize_doc_category_value((detail or {}).get("category", ""))
                if meta:
                    codes.add(meta["code"])
        for code in codes:
            stats[code]["file_count"] += 1
            if stats[code]["last_uploaded_at"] is None or created_at > stats[code]["last_uploaded_at"]:
                stats[code]["last_uploaded_at"] = created_at
    return stats


def _category_keyword_scores(text: str) -> dict[str, int]:
    haystack = (text or "").lower()
    scores = {}
    for meta in STANDARD_DOC_CATEGORIES:
        score = 0
        for keyword in meta["keywords"]:
            if keyword.lower() in haystack:
                score += 1
        scores[meta["code"]] = score
    return scores


# ============================================================================
# EP 1 / 12：创建案件
# POST /api/ingest/case
# ============================================================================

@app.post("/api/ingest/case")
def create_case(req: CreateCaseReq):
    company_id = (req.company_id or "co_f1824b82e2116701").strip()
    owner_id = (req.owner_id or req.created_by or "").strip()
    created_by = (req.created_by or owner_id).strip()
    debtor_name = (req.debtor_name or "").strip()
    asset_purchaser_name = (req.asset_purchaser_name or "").strip()
    if not debtor_name:
        raise HTTPException(422, "debtor_name 不能为空")

    existing = _find_existing_case(debtor_name, req.debtor_uscc, company_id=company_id)
    if existing:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO case_party (
                        case_id, debtor_id, party_name, party_role, uscc,
                        is_primary, status, source_type, created_by
                    ) VALUES (%s, %s, %s, 'debtor', %s, TRUE, 'active', 'case_creation', %s)
                    ON CONFLICT (debtor_id) WHERE debtor_id IS NOT NULL
                    DO UPDATE SET
                        party_name = EXCLUDED.party_name,
                        uscc = COALESCE(EXCLUDED.uscc, case_party.uscc),
                        status = 'active',
                        updated_at = now()
                    """,
                    (
                        existing["case_id"],
                        existing["debtor_id"],
                        debtor_name,
                        req.debtor_uscc,
                        created_by,
                    ),
                )
                if asset_purchaser_name:
                    cur.execute(
                        """
                        INSERT INTO case_party (
                            case_id, party_name, party_role, is_primary,
                            status, source_type, created_by
                        ) VALUES (%s, %s, 'asset_purchaser', TRUE, 'active', 'case_creation', %s)
                        ON CONFLICT (case_id, party_name, party_role)
                        DO UPDATE SET
                            is_primary = TRUE,
                            status = 'active',
                            created_by = CASE
                                WHEN EXCLUDED.created_by <> '' THEN EXCLUDED.created_by
                                ELSE case_party.created_by
                            END,
                            updated_at = now()
                        """,
                        (existing["case_id"], asset_purchaser_name, created_by),
                    )
        logger.info("[CreateCase] 复用已有案件 | debtor=%s | uscc=%s | case_id=%s | debtor_id=%s",
                    debtor_name, req.debtor_uscc, existing["case_id"], existing["debtor_id"])
        return {
            "case_id": existing["case_id"],
            "debtor_id": existing["debtor_id"],
            "message": f"复用已有案件：{existing.get('case_name') or req.case_name}",
            "deduplicated": True,
        }

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cases (case_name, case_type, company_id, owner_id, created_by)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING case_id
                """,
                (req.case_name.strip(), req.case_type, company_id, owner_id, created_by),
            )
            case_id = int(cur.fetchone()[0])

            cur.execute(
                """
                INSERT INTO debtors (case_id, entity_name, uscc)
                VALUES (%s, %s, %s)
                RETURNING debtor_id
                """,
                (case_id, debtor_name, req.debtor_uscc),
            )
            debtor_id = int(cur.fetchone()[0])

            cur.execute(
                """
                INSERT INTO case_party (
                    case_id, debtor_id, party_name, party_role, uscc,
                    is_primary, status, source_type, created_by
                ) VALUES (%s, %s, %s, 'debtor', %s, TRUE, 'active', 'case_creation', %s)
                """,
                (case_id, debtor_id, debtor_name, req.debtor_uscc, created_by),
            )
            if asset_purchaser_name:
                cur.execute(
                    """
                    INSERT INTO case_party (
                        case_id, party_name, party_role, is_primary,
                        status, source_type, created_by
                    ) VALUES (%s, %s, 'asset_purchaser', TRUE, 'active', 'case_creation', %s)
                    """,
                    (case_id, asset_purchaser_name, created_by),
                )
            cur.execute(
                "SELECT init_data_source_checklist(%s, %s, %s)",
                (case_id, debtor_name, "债务人"),
            )

    return {"case_id": case_id, "debtor_id": debtor_id, "message": f"案件已创建，已初始化19个数据源检查项"}


# ============================================================================
# EP 2 / 12：企查查穿透
# POST /api/ingest/enterprise
# ============================================================================

def _qcc_auth_headers() -> dict:
    """生成企查查 API 请求头（Token + Timespan）"""
    timespan = str(int(time.time()))
    raw = QICHACHA_API_KEY + timespan + QICHACHA_SECRET_KEY
    token = hashlib.md5(raw.encode("utf-8")).hexdigest().upper()
    return {"Token": token, "Timespan": timespan}


def _map_qcc_detail(raw: dict) -> dict:
    """将企查查 735 返回的 Result 映射为内部格式"""
    r = raw.get("Result") or {}
    shareholders = []
    for p in r.get("Partners") or []:
        st = p.get("StockType", "")
        sh_type = "企业" if "法人" in st or "企业" in st else "自然人"
        ratio_str = (p.get("StockPercent") or "").replace("%", "").strip()
        try:
            ratio = float(ratio_str) / 100 if ratio_str else None
        except ValueError:
            ratio = None
        tags = p.get("TagsList") or []
        shareholders.append({
            "name": p.get("StockName", ""),
            "type": sh_type,
            "uscc": p.get("CreditCode") if sh_type == "企业" else None,
            "ratio": ratio,
            "is_actual_ctrl": "实际控制人" in tags,
        })
    executives = []
    for e in r.get("Employees") or []:
        executives.append({"name": e.get("Name", ""), "position": e.get("Job", "")})

    return {
        "entity_name": r.get("Name", ""),
        "uscc": r.get("CreditCode", ""),
        "legal_rep": r.get("OperName", ""),
        "registered_addr": r.get("Address", ""),
        "phone": (r.get("ContactInfo") or {}).get("PhoneNumber", ""),
        "established": (r.get("StartDate") or "")[:10] or None,
        "status": r.get("Status", ""),
        "reg_capital": r.get("RegistCapi", ""),
        "paid_capital": r.get("RecCap", ""),
        "industry_name": (r.get("Industry") or {}).get("SubIndustry", ""),
        "shareholders": shareholders,
        "executives": executives,
        "_raw": raw,
    }


def _load_enterprise_from_cache(enterprise_id: int) -> dict | None:
    """从缓存表读取完整企业信息，组装成API格式"""
    ent = db.query_one("SELECT * FROM enterprises WHERE enterprise_id=%s", (enterprise_id,))
    if not ent:
        return None
    
    shareholders_rows = db.query("SELECT * FROM shareholders WHERE enterprise_id=%s", (enterprise_id,))
    executives_rows = db.query("SELECT * FROM executives WHERE enterprise_id=%s", (enterprise_id,))
    
    shareholders = []
    for row in shareholders_rows:
        shareholders.append({
            "name": row["shareholder_name"],
            "type": row["shareholder_type"] or "其他",
            "uscc": row["shareholder_uscc"],
            "ratio": float(row["share_ratio"]) if row["share_ratio"] else None,
            "is_actual_ctrl": row.get("is_actual_ctrl", False),
        })
    
    executives = []
    for row in executives_rows:
        executives.append({
            "name": row["person_name"],
            "position": row["position"],
        })
    
    return {
        "entity_name": ent["entity_name"],
        "uscc": ent["uscc"],
        "legal_rep": ent["legal_rep"],
        "registered_addr": ent["registered_addr"],
        "phone": ent["phone"],
        "established": str(ent["established"]) if ent["established"] else None,
        "status": ent["status"],
        "reg_capital": str(ent["reg_capital"]) if ent["reg_capital"] else None,
        "paid_capital": str(ent["paid_capital"]) if ent["paid_capital"] else None,
        "industry_name": ent["industry_name"],
        "shareholders": shareholders,
        "executives": executives,
        "_raw": ent.get("raw_response", {}),
        "_cache_hit": True,
        "_cache_time": ent.get("api_fetched_at") or ent.get("updated_at"),
    }


async def _get_qcc_cached(company_name: str, cache_ttl_days: int = 30, 
                          force_refresh: bool = False) -> dict:
    """缓存包装：先查DB，无效或无缓存则调用API
    Args:
        company_name: 企业名称或USCC
        cache_ttl_days: 缓存有效期（天数）
        force_refresh: 是否强制刷新（跳过缓存）
    Returns:
        企业信息字典（含_cache_hit标记）
    """
    # 1. 如果不强制刷新，先查缓存
    if not force_refresh:
        cached = db.query_one(f"""
            SELECT enterprise_id, entity_name, updated_at 
            FROM enterprises 
            WHERE (entity_name = %s OR uscc = %s) 
              AND updated_at > now() - INTERVAL '{cache_ttl_days} days'
            LIMIT 1
        """, (company_name, company_name))
        
        if cached:
            logger.info("[QCC] 缓存命中: %s (enterprise_id=%s, 更新时间=%s)",
                       cached["entity_name"], cached["enterprise_id"], cached["updated_at"])
            result = _load_enterprise_from_cache(cached["enterprise_id"])
            if result:
                return result
    
    # 2. 缓存无效或强制刷新，调用API
    logger.info("[QCC] 缓存%s，调用API获取: %s", 
               "已过期" if not force_refresh else "强制刷新",
               company_name)
    api_result = await _call_qichacha(company_name)
    
    # 3. API成功则写入缓存，标记缓存未命中
    if isinstance(api_result, dict) and "entity_name" in api_result:
        # 排除mock数据，只缓存真实API返回
        if not api_result.get("mock"):
            api_result["_cache_hit"] = False
            api_result["_cache_time"] = None
    
    return api_result


async def _call_qichacha(company_name: str) -> dict:
    """调用企查查 735 企业工商详情 API，返回统一内部格式"""
    if not QICHACHA_API_KEY or not QICHACHA_SECRET_KEY:
        return {"error": "未配置企查查API Key/SecretKey", "mock": True, "company_name": company_name}

    headers = _qcc_auth_headers()
    url = f"{QICHACHA_BASE_URL}/ECIInfoVerify/GetInfo"
    params = {"key": QICHACHA_API_KEY, "searchKey": company_name}

    logger.info("[QCC] 请求企业工商详情: %s", company_name)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params, headers=headers)
            raw = resp.json()
    except Exception as e:
        logger.error("[QCC] 请求失败: %s", e)
        return {"error": str(e), "mock": True, "company_name": company_name}

    status = raw.get("Status")
    if status != "200":
        logger.warning("[QCC] 非成功状态 Status=%s Message=%s", status, raw.get("Message"))
        return {"error": raw.get("Message", "企查查返回异常"), "mock": True,
                "company_name": company_name, "qcc_status": status}

    mapped = _map_qcc_detail(raw)
    logger.info("[QCC] 成功获取: %s (USCC=%s, 股东%d, 高管%d)",
                mapped["entity_name"], mapped["uscc"],
                len(mapped["shareholders"]), len(mapped["executives"]))
    return mapped


def _parse_capital(val) -> float | None:
    """将注册资本字符串解析为万元数值，如 '5000万元' -> 5000.0"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(",", "").strip()
    m = re.search(r'([\d.]+)', s)
    if not m:
        return None
    num = float(m.group(1))
    if "亿" in s:
        num *= 10000
    return num


def _save_enterprise(case_id: int, data: dict, source: str = "qichacha"):
    """将企查查返回数据写入 enterprises/shareholders/executives"""
    name = data.get("entity_name") or data.get("name", "")
    uscc = (data.get("uscc") or data.get("credit_code", ""))[:18]  # 统一社会信用代码最长18位
    addr = data.get("registered_addr") or data.get("address", "")
    phone = data.get("phone", "")
    legal_rep = data.get("legal_rep") or data.get("legal_person", "")

    addr_hash = hashlib.md5(addr.encode()).hexdigest() if addr else None
    phone_hash = hashlib.md5(phone.replace("-", "").replace(" ", "").encode()).hexdigest() if phone else None

    row = db.execute_returning("""
        INSERT INTO enterprises (uscc, entity_name, legal_rep, registered_addr, phone,
            established, status, reg_capital, paid_capital, industry_name,
            addr_hash, phone_hash, data_source, raw_response)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT (uscc) DO UPDATE SET updated_at = now()
        RETURNING enterprise_id
    """, (
        uscc, name, legal_rep, addr, phone,
        data.get("established"), data.get("status"),
        _parse_capital(data.get("reg_capital")),
        _parse_capital(data.get("paid_capital")),
        data.get("industry_name"),
        addr_hash, phone_hash, source,
        json.dumps({k: v for k, v in data.items() if k != "_raw"}, ensure_ascii=False, default=str),
    ))
    ent_id = row["enterprise_id"]

    VALID_SH_TYPES = {"自然人", "企业", "其他"}
    for sh in data.get("shareholders", []):
        raw_type = sh.get("type", "自然人")
        sh_type = "企业" if "法人" in raw_type or "企业" in raw_type else (
            raw_type if raw_type in VALID_SH_TYPES else "其他")
        ratio = sh.get("ratio")
        if isinstance(ratio, str):
            ratio_clean = ratio.replace("%", "").strip()
            try:
                ratio = float(ratio_clean) / 100 if ratio_clean else None
            except ValueError:
                ratio = None
        db.execute("""
            INSERT INTO shareholders (enterprise_id, shareholder_name, shareholder_type,
                shareholder_uscc, share_ratio, is_actual_ctrl, data_source, snapshot_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,CURRENT_DATE)
            ON CONFLICT DO NOTHING
        """, (
            ent_id, sh.get("name", ""), sh_type,
            sh.get("uscc"), ratio, sh.get("is_actual_ctrl", False), source,
        ))

    for ex in data.get("executives", []):
        db.execute("""
            INSERT INTO executives (enterprise_id, person_name, position, data_source, snapshot_date)
            VALUES (%s,%s,%s,%s,CURRENT_DATE)
            ON CONFLICT DO NOTHING
        """, (ent_id, ex.get("name", ""), ex.get("position", ""), source))

    return ent_id


@app.post("/api/ingest/enterprise")
async def fetch_enterprise(req: FetchEnterpriseReq):
    """企业信息写库后失效该案件 get_full_context 缓存。"""
    try:
        return await _fetch_enterprise_impl(req)
    finally:
        _invalidate_full_context_cache(req.case_id)


async def _fetch_enterprise_impl(req: FetchEnterpriseReq):
    results = {"enterprise_count": 0, "shareholder_count": 0, "executive_count": 0,
               "five_same_hits": [], "cross_positions": [], "cache_hit": False}

    # ── 缓存检查：enterprises 表已有该公司且30天内更新过，直接跳过外部API ──
    cached = db.query_one("""
        SELECT enterprise_id, entity_name, uscc, legal_rep, registered_addr, phone,
               established, status, reg_capital, paid_capital, industry_name, updated_at
        FROM enterprises
        WHERE entity_name = %s AND updated_at > now() - INTERVAL '30 days'
        LIMIT 1
    """, (req.company_name,))

    if cached:
        logger.info("[Enterprise] 缓存命中，跳过外部API | company=%s | updated_at=%s",
                    req.company_name, cached["updated_at"])
        ent_id = cached["enterprise_id"]
        shareholders = db.query("SELECT * FROM shareholders WHERE enterprise_id=%s", (ent_id,))
        executives = db.query("SELECT * FROM executives WHERE enterprise_id=%s", (ent_id,))
        results["enterprise_count"] = 1
        results["shareholder_count"] = len(shareholders)
        results["executive_count"] = len(executives)
        results["cache_hit"] = True
    else:
        api_data = await _get_qcc_cached(req.company_name)

        if api_data.get("mock"):
            # 无法从API获取真实数据，记录警告但继续流程（不中断工作流）
            logger.warning("[Enterprise] 跳过此企业（无真实工商数据）: %s | reason=%s", 
                          req.company_name, api_data.get("error", "未知原因"))
            # 不入库任何数据，但继续返回其他有效数据（五同、交叉等）
        elif isinstance(api_data, dict) and "entity_name" in api_data:
            _save_enterprise(req.case_id, api_data)
            results["enterprise_count"] += 1
            results["shareholder_count"] += len(api_data.get("shareholders", []))
            results["executive_count"] += len(api_data.get("executives", []))

            # 递归穿透股东中的企业
            if req.depth > 1:
                for sh in api_data.get("shareholders", []):
                    if sh.get("type") == "企业" and sh.get("uscc"):
                        # 股东企业也先查缓存
                        sh_cached = db.query_one("""
                            SELECT enterprise_id FROM enterprises
                            WHERE entity_name=%s AND updated_at > now() - INTERVAL '30 days'
                        """, (sh["name"],))
                        if sh_cached:
                            logger.info("[Enterprise] 股东缓存命中: %s", sh["name"])
                            results["enterprise_count"] += 1
                            continue
                        sub_data = await _get_qcc_cached(sh["name"])
                        if isinstance(sub_data, dict) and "entity_name" in sub_data and not sub_data.get("mock"):
                            _save_enterprise(req.case_id, sub_data)
                            results["enterprise_count"] += 1
                        elif sub_data.get("mock"):
                            logger.warning("[Enterprise] 股东企业无真实数据，跳过: %s", sh["name"])

    # 查询五同命中
    five_same = db.query("""
        SELECT ent_a_name, ent_b_name,
               same_addr + same_phone + same_legal_rep + same_executive + same_industry AS score,
               same_addr, same_phone, same_legal_rep, same_executive, same_industry
        FROM v_five_same_audit
        WHERE same_addr + same_phone + same_legal_rep + same_executive + same_industry >= 2
        ORDER BY score DESC LIMIT 20
    """)
    results["five_same_hits"] = [dict(r) for r in five_same]

    # 查询交叉任职
    cross = db.query("""
        SELECT ea.person_name, ea.position AS pos_a, a.entity_name AS company_a,
               eb.position AS pos_b, b.entity_name AS company_b
        FROM executives ea
        JOIN executives eb ON ea.person_name = eb.person_name AND ea.enterprise_id < eb.enterprise_id
        JOIN enterprises a ON ea.enterprise_id = a.enterprise_id
        JOIN enterprises b ON eb.enterprise_id = b.enterprise_id
        WHERE ea.departure_date IS NULL AND eb.departure_date IS NULL
    """)
    results["cross_positions"] = [dict(r) for r in cross]

    logger.info("[Enterprise] 完成获取企业数据 | 企业数=%d | 股东数=%d | 高管数=%d | 缓存=%s | 五同=%d | 交叉=%d",
               results["enterprise_count"], results["shareholder_count"], results["executive_count"],
               "命中" if results["cache_hit"] else "未命中",
               len(results["five_same_hits"]), len(results["cross_positions"]))

    return results


# ============================================================================
# 新增：标准卷宗类别
# GET /api/ingest/doc-categories
# ============================================================================

@app.get(
    "/api/ingest/doc-categories",
    response_model=DocCategoriesResp,
    summary="获取标准卷宗类别字典",
    description=(
        "返回系统支持的标准卷宗类别列表。当前为13类，包含稳定 code、中文名称、展示顺序、"
        "字段清单等。前端上传下拉框和 Dify 工作流应优先使用 code 传参；若数据库中的 "
        "doc_category_catalog 已建表，则优先读取数据库字典，否则回退到代码内置字典。"
    ),
    tags=["卷宗上传"],
)
def get_doc_categories():
    return {"categories": _load_doc_categories()}


# ============================================================================
# 新增：案件卷宗类别覆盖情况
# GET /api/case/{case_id}/doc-categories
# ============================================================================

@app.get(
    "/api/case/{case_id}/doc-categories",
    response_model=CaseDocCategoriesResp,
    summary="查询案件13类卷宗覆盖情况",
    description=(
        "按案件返回每个标准卷宗类别是否已覆盖。file_count 来自 source_file_doc_category 与 "
        "source_file 的关联；record_count 来自对应业务结构化表。若分类关联表为空，接口会回退到 "
        "source_file/source_chunk 关键词判断，避免新表上线初期所有类别误判为未上传。"
    ),
    tags=["卷宗上传"],
)
def get_case_doc_categories(
    case_id: int = Path(..., description="案件ID，对应 cases.case_id")
):
    case = db.query_one("SELECT case_id FROM cases WHERE case_id=%s", (case_id,))
    if not case:
        raise HTTPException(404, "案件不存在")

    categories = _load_doc_categories()
    record_counts = _get_case_category_record_counts(case_id)
    file_stats = _get_case_category_file_stats(case_id)

    result = []
    missing = []
    for meta in categories:
        code = meta["code"]
        file_stat = file_stats.get(code, {})
        file_count = int(file_stat.get("file_count") or 0)
        record_count = int(record_counts.get(code) or 0)
        uploaded = file_count > 0 or record_count > 0
        last_uploaded_at = file_stat.get("last_uploaded_at")
        result.append({
            "code": code,
            "name": meta["name"],
            "uploaded": uploaded,
            "file_count": file_count,
            "record_count": record_count,
            "last_uploaded_at": last_uploaded_at.isoformat() if isinstance(last_uploaded_at, datetime) else (str(last_uploaded_at) if last_uploaded_at else None),
        })
        if not uploaded:
            missing.append(code)

    return {
        "case_id": case_id,
        "categories": result,
        "missing_categories": missing,
    }


# ============================================================================
# 新增：上传前类别校验
# POST /api/ingest/validate-doc-category
# ============================================================================

@app.post(
    "/api/ingest/validate-doc-category",
    response_model=ValidateDocCategoryResp,
    summary="上传前校验卷宗类别",
    description=(
        "用于文件上传前的轻量校验：检查所选 doc_category 是否为支持类别，基于文件名和可选文本预览"
        "判断是否疑似选错类别，并检查当前案件下是否存在同名文件或单文件类资料的重复上传风险。"
        "该接口不写入数据库，只返回校验提示。"
    ),
    tags=["卷宗上传"],
)
def validate_doc_category(req: ValidateDocCategoryReq):
    case = db.query_one("SELECT case_id FROM cases WHERE case_id=%s", (req.case_id,))
    if not case:
        raise HTTPException(404, "案件不存在")

    meta = _normalize_doc_category_value(req.doc_category)
    if not meta:
        raise HTTPException(400, f"不支持的文档类型: {req.doc_category}")

    probe_text = " ".join(req.file_names or [])
    if req.text_preview:
        probe_text = f"{probe_text}\n{req.text_preview}"
    scores = _category_keyword_scores(probe_text)
    selected_score = scores.get(meta["code"], 0)
    best_code = max(scores, key=scores.get) if scores else meta["code"]
    best_score = scores.get(best_code, 0)
    has_match_signal = best_score > 0
    has_probe_input = bool((probe_text or "").strip())
    content_check_performed = bool((req.text_preview or "").strip()) or has_match_signal

    suspected_mismatch = False
    if best_code != meta["code"] and best_score > 0 and best_score >= selected_score + 1:
        suspected_mismatch = True
    elif selected_score == 0 and best_score > 0:
        suspected_mismatch = True

    exact_dupes = []
    if req.file_names:
        exact_dupes_rows = db.query("""
            SELECT file_name
            FROM source_file
            WHERE case_id=%s AND lower(file_name) = ANY(%s)
        """, (req.case_id, [name.lower() for name in req.file_names]))
        exact_dupes = [row["file_name"] for row in exact_dupes_rows]

    coverage = _get_case_category_file_stats(req.case_id)
    category_uploaded = int((coverage.get(meta["code"]) or {}).get("file_count") or 0) > 0
    suspected_duplicate = bool(exact_dupes)
    if not suspected_duplicate and category_uploaded and meta["code"] not in DOC_CATEGORY_MULTI_UPLOAD:
        suspected_duplicate = True

    if not has_probe_input:
        message = "未提供文件名或文本预览，本次仅跳过类别匹配校验"
        ok = True
    elif not content_check_performed:
        message = "未提供文本预览，且文件名未体现明确类别特征；本次仅完成重复检测，未校验内容匹配"
        ok = True
    if suspected_duplicate and exact_dupes:
        message = f"疑似重复上传：已存在同名文件 {', '.join(exact_dupes[:3])}"
        ok = True
    elif suspected_duplicate:
        message = "该案件该类别已存在上传记录，请确认是否为重复或补充上传"
        ok = True
    elif suspected_mismatch:
        best_name = STANDARD_DOC_CATEGORY_BY_CODE.get(best_code, {}).get("name", best_code)
        message = f"文件内容更像“{best_name}”，请复核所选类别"
        ok = False
    elif has_match_signal:
        message = "文件与所选类别基本匹配"
        ok = True

    return {
        "ok": ok,
        "suspected_mismatch": suspected_mismatch,
        "suspected_duplicate": suspected_duplicate,
        "content_check_performed": content_check_performed,
        "message": message,
    }


# ============================================================================
# EP 3 / 12：结构化字段入库
# POST /api/ingest/structured-fields
# ============================================================================

# Dify发送的字段名 → DB实际列名（不一致时映射）
FIELD_ALIASES = {
    "guarantor_name": "entity_name",
    "designed_capacity": "annual_capacity",
    "current_status": "mining_status",
    "project_scale": "production_scale",
    "eco_redline_status": "in_ecological_redline",
    "query_date": "inquiry_date",
}

INGEST_ROUTER = {
    "贷款合同": ("claims", ["principal", "interest", "penalty", "delayed_interest", "total_claim",
                            "guarantee_type", "collateral_desc", "lien_priority", "court_name",
                            "exec_case_no", "litigation_status"]),
    # S1: 判决书和执行裁定合并为同一路由（Dify统一发 doc_category="判决书"）
    "判决书": ("legal_documents", ["case_number", "court_name", "case_cause", "doc_type",
                                   "judgment_date", "claim_amount", "judgment_amount", "execution_status",
                                   "plaintiff", "defendant", "enforcement_deadline",
                                   "court_level", "case_type"]),
    "执行裁定": ("legal_documents", ["case_number", "court_name", "case_cause", "doc_type",
                                     "judgment_date", "claim_amount", "judgment_amount", "execution_status",
                                     "plaintiff", "defendant", "enforcement_deadline",
                                     "court_level", "case_type"]),
    "财务报表": ("financial_snapshots", ["report_period", "report_type", "other_receivables", "prepayments",
                                         "total_assets", "total_liabilities", "revenue", "operating_cost",
                                         "net_profit", "tax_reported_revenue", "tax_reported_cost"]),
    "银行流水": ("transaction_signatures", []),  # 特殊处理：批量写入
    # S2: 审批单据与银行流水共用同一表, 保留路由以防Dify单独发送
    "审批单据": ("transaction_signatures", ["doc_ref", "txn_date", "txn_amount", "counterparty",
                                            "maker", "reviewer", "approver"]),
    "担保合同": ("guarantors", ["entity_name", "guarantor_type", "guarantee_type", "guarantee_scope", "spouse_name"]),
    # M5: 不动产补充权属异议/物理占用/顺位等折扣因子字段
    "不动产权证": ("real_estate_evaluations", ["property_owner", "property_address", "real_estate_cert_no",
                                               "land_nature", "total_building_area", "land_use_area",
                                               "property_usage", "mortgage_status", "seal_status",
                                               "seal_expiry", "lease_status", "gross_value",
                                               "has_title_objection", "physical_occupation",
                                               "lien_priority", "sealing_court",
                                               "lease_annual_rent", "lease_start", "lease_end"]),
    "采矿许可证": ("mining_evaluations", ["mine_name", "mine_location", "permit_expiry", "production_scale",
                                           "mineral_type", "mine_scale", "mining_status",
                                           "safety_permit_status", "env_approval_status",
                                           "mining_right_mortgage", "mining_right_sealed",
                                           "proved_reserves", "estimated_value",
                                           "transfer_base_price", "in_ecological_redline"]),
    "煤矿重整方案": ("contacts", []),  # 特殊处理
    "勘探报告": ("mining_evaluations", ["mine_name", "report_org", "report_date", "mineral_type",
                                         "proved_reserves", "controlled_reserves", "inferred_resources",
                                         "total_reserves", "calorific_value", "ash_content_pct",
                                         "sulfur_content_pct", "coal_type"]),
    "环评批复": ("mining_evaluations", ["mine_name", "env_approval_status", "production_scale",
                                         "in_ecological_redline"]),
    "法院总对总": ("bank_accounts", []),  # 特殊处理
    "律师调查报告": ("risk_profiles", []),  # 特殊处理
    "开采设计与复垦": ("mining_evaluations", ["mine_name", "annual_capacity", "mining_status"]),
    "权证文件": ("real_estate_evaluations", []),
}


def _coerce_value(val, col_type: str):
    """根据数据库列类型强转值，空串→None，中文数字→int等"""
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    if col_type in ("numeric", "double precision", "real"):
        if isinstance(val, (int, float)):
            return val
        s = str(val).replace(",", "").replace("，", "")
        m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
        return float(m.group()) if m else None
    if col_type in ("integer", "bigint", "smallint"):
        if isinstance(val, int):
            return val
        s = str(val)
        cn_map = {"第一": 1, "第二": 2, "第三": 3, "第四": 4, "第五": 5,
                  "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                  "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        for cn, num in cn_map.items():
            if cn in s:
                return num
        m = re.search(r"[-+]?\d+", s)
        return int(m.group()) if m else None
    if col_type == "date":
        s = str(val).strip()
        m = re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", s)
        return m.group().replace("/", "-") if m else None
    if col_type == "boolean":
        if isinstance(val, bool):
            return val
        s = str(val).strip().lower()
        return s in ("true", "1", "是", "yes", "涉及", "已批复", "有效")
    return val


def _get_table_column_types(table: str) -> dict:
    """获取表的列名→数据类型映射"""
    rows = db.query(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name=%s AND table_schema='public'",
        (table,)
    )
    return {r["column_name"]: r["data_type"] for r in rows}


def _get_table_columns(table: str) -> list:
    """获取表的列名列表"""
    return list(_get_table_column_types(table).keys())


def _generic_insert(table: str, case_id: int, debtor_id: int, fields: dict, allowed_cols: list,
                    upsert_keys: list | None = None,
                    upsert_where: str | None = None,
                    upsert_nothing: bool = False):
    """通用INSERT：字段别名映射 + 类型强转 + 溢出字段存入extra_fields
    upsert_keys: 若提供，则以这些列为冲突键做UPSERT（合并而非新增行）
    upsert_where: 部分唯一索引的WHERE条件（如 'mine_name IS NOT NULL'）
    """
    # 1. 字段别名映射（Dify字段名 → DB列名）
    mapped = {}
    for k, v in fields.items():
        col = FIELD_ALIASES.get(k, k)
        mapped[col] = v

    # 2. 获取表结构
    col_types = _get_table_column_types(table)

    # 3. 分离：allowed_cols 内的走正常列，其余存 extra_fields
    cols_to_write = {k: v for k, v in mapped.items() if k in allowed_cols}
    overflow = {k: v for k, v in mapped.items()
                if k not in allowed_cols and k not in ("case_id", "debtor_id")
                and v is not None and v != ""}

    # 4. 类型强转
    for k in list(cols_to_write.keys()):
        ct = col_types.get(k)
        if ct:
            cols_to_write[k] = _coerce_value(cols_to_write[k], ct)

    # 去掉强转后为None的值
    cols_to_write = {k: v for k, v in cols_to_write.items() if v is not None}

    # 5. 写入 extra_fields（溢出字段）—— UPSERT时合并已有json
    if overflow and "extra_fields" in col_types:
        cols_to_write["extra_fields"] = json.dumps(overflow, ensure_ascii=False, default=str)

    if not cols_to_write:
        logger.warning("[_generic_insert] %s: 无有效字段可写入 | raw_fields=%s | mapped=%s | allowed=%s",
                       table, str(fields)[:300], str(mapped)[:200], allowed_cols)
        return None

    cols_to_write["case_id"] = case_id
    if "debtor_id" in col_types:
        cols_to_write["debtor_id"] = debtor_id

    col_names = list(cols_to_write.keys())
    placeholders = ["%s"] * len(col_names)
    values = list(cols_to_write.values())

    # UPSERT模式：冲突时合并非空字段（保留已有值 + 合并extra_fields）
    if upsert_keys:
        update_parts = []
        for c in col_names:
            if c in upsert_keys:
                continue
            if c == "extra_fields":
                # 合并JSON：已有extra_fields || 新extra_fields
                update_parts.append(f"extra_fields = COALESCE({table}.extra_fields, '{{}}'::jsonb) || COALESCE(EXCLUDED.extra_fields::jsonb, '{{}}'::jsonb)")
            else:
                # 用新值覆盖，但如果新值是NULL则保留旧值
                update_parts.append(f"{c} = COALESCE(EXCLUDED.{c}, {table}.{c})")
        conflict_cols = ",".join(upsert_keys)
        conflict_clause = f"({conflict_cols})"
        if upsert_where:
            conflict_clause += f" WHERE {upsert_where}"
        sql = (f"INSERT INTO {table} ({','.join(col_names)}) VALUES ({','.join(placeholders)}) "
               f"ON CONFLICT {conflict_clause} DO UPDATE SET {', '.join(update_parts)} "
               f"RETURNING *")
    elif upsert_nothing:
        sql = (f"INSERT INTO {table} ({','.join(col_names)}) VALUES ({','.join(placeholders)}) "
               f"ON CONFLICT DO NOTHING RETURNING *")
    else:
        sql = f"INSERT INTO {table} ({','.join(col_names)}) VALUES ({','.join(placeholders)}) RETURNING *"

    try:
        return db.execute_returning(sql, values)
    except Exception as e:
        logger.error("[_generic_insert] %s: SQL执行失败 | %s | sql=%s", table, str(e)[:200], sql[:200])
        # 如果是ON CONFLICT约束问题，降级策略
        error_str = str(e)
        if "ON CONFLICT" in error_str or "constraint" in error_str.lower():
            logger.warning("[_generic_insert] %s: 约束问题，降级处理", table)
            
            # 降级1：尝试 ON CONFLICT DO NOTHING（不指定冲突列）
            if upsert_keys or upsert_nothing:
                fallback_sql = f"INSERT INTO {table} ({','.join(col_names)}) VALUES ({','.join(placeholders)}) ON CONFLICT DO NOTHING RETURNING *"
                try:
                    result = db.execute_returning(fallback_sql, values)
                    if result:
                        logger.info("[_generic_insert] %s: 降级到DO NOTHING成功", table)
                        return result
                except Exception:
                    pass
            
            # 降级2：纯普通INSERT（无ON CONFLICT）
            logger.warning("[_generic_insert] %s: 继续降级为纯INSERT", table)
            bare_sql = f"INSERT INTO {table} ({','.join(col_names)}) VALUES ({','.join(placeholders)}) RETURNING *"
            try:
                return db.execute_returning(bare_sql, values)
            except Exception as e2:
                logger.error("[_generic_insert] %s: 纯INSERT也失败 | %s", table, str(e2)[:200])
                # 最后降级：纯插入+忽略主键冲突
                bare_sql_ignore = f"INSERT INTO {table} ({','.join(col_names)}) VALUES ({','.join(placeholders)}) ON CONFLICT DO NOTHING"
                try:
                    db.execute(bare_sql_ignore, values)
                    logger.warning("[_generic_insert] %s: 已写入（忽略重复）", table)
                    return None
                except Exception as e3:
                    logger.error("[_generic_insert] %s: 所有降级都失败 | %s", table, str(e3)[:200])
                    return None
        return None


@app.post("/api/ingest/structured-fields")
def ingest_structured_fields(req: IngestFieldsReq):
    """写库后失效该案件 get_full_context 缓存（finally 确保即使部分写入/异常也失效）。"""
    try:
        return _ingest_structured_fields_impl(req)
    finally:
        _invalidate_full_context_cache(req.case_id)


def _ingest_structured_fields_impl(req: IngestFieldsReq):
    meta = _normalize_doc_category_value(req.doc_category)
    cat = meta["name"] if meta else req.doc_category
    if cat not in INGEST_ROUTER:
        raise HTTPException(400, f"不支持的文档类型: {cat}")

    target_table, allowed = INGEST_ROUTER[cat]

    # 特殊处理：银行流水（批量交易）
    if cat == "银行流水":
        txns = req.fields.get("transactions", [])
        count = 0
        for t in txns:
            db.execute("""
                INSERT INTO transaction_signatures (case_id, debtor_id, txn_date, txn_amount,
                    txn_direction, counterparty, maker, reviewer, approver)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, (req.case_id, req.debtor_id,
                  _coerce_value(t.get("txn_date"), "date"),
                  _coerce_value(t.get("txn_amount"), "numeric"),
                  t.get("txn_direction"), t.get("counterparty"),
                  t.get("maker"), t.get("reviewer"), t.get("approver")))
            count += 1
        # --- F1: 自动标记关联方交易 ---
        # 收集所有已知关联方名称
        known_related = set()
        for row in db.query("SELECT entity_name FROM debtors WHERE case_id=%s", (req.case_id,)):
            if row["entity_name"]: known_related.add(row["entity_name"])
        for row in db.query("SELECT entity_name FROM guarantors WHERE case_id=%s", (req.case_id,)):
            if row["entity_name"]: known_related.add(row["entity_name"])
        for row in db.query("SELECT person_name FROM related_persons WHERE case_id=%s", (req.case_id,)):
            if row["person_name"]: known_related.add(row["person_name"])
        # 企业查控中的股东/高管 (enterprises通过uscc关联debtors)
        for row in db.query("""SELECT s.shareholder_name FROM shareholders s
            JOIN enterprises e ON e.enterprise_id=s.enterprise_id
            JOIN debtors d ON d.uscc=e.uscc
            WHERE d.case_id=%s""", (req.case_id,)):
            if row["shareholder_name"]: known_related.add(row["shareholder_name"])
        for row in db.query("""SELECT x.person_name FROM executives x
            JOIN enterprises e ON e.enterprise_id=x.enterprise_id
            JOIN debtors d ON d.uscc=e.uscc
            WHERE d.case_id=%s""", (req.case_id,)):
            if row["person_name"]: known_related.add(row["person_name"])
        if known_related:
            like_clauses = " OR ".join(["counterparty LIKE %s"] * len(known_related))
            params = [f"%{n}%" for n in known_related]
            db.execute(f"""
                UPDATE transaction_signatures SET is_related_party=TRUE
                WHERE case_id=%s AND is_related_party IS NOT TRUE
                  AND ({like_clauses})
            """, [req.case_id] + params)
        # --- F2: 自动标记可疑路由 ---
        # 检测回流：同一对手，先出后入（或反之），金额接近
        db.execute("""
            WITH pairs AS (
                SELECT a.id AS out_id, b.id AS in_id,
                       a.counterparty, a.txn_amount AS out_amt, b.txn_amount AS in_amt,
                       b.txn_date - a.txn_date AS day_gap
                FROM transaction_signatures a
                JOIN transaction_signatures b ON a.case_id=b.case_id
                    AND a.counterparty=b.counterparty
                    AND a.txn_direction='out' AND b.txn_direction='in'
                    AND b.txn_date >= a.txn_date
                    AND b.txn_date - a.txn_date <= 30
                WHERE a.case_id=%s AND a.txn_amount > 0 AND b.txn_amount > 0
                  AND ABS(a.txn_amount - b.txn_amount) / GREATEST(a.txn_amount, 1) < 0.1
            )
            UPDATE transaction_signatures SET routing_tag='疑似回流'
            WHERE id IN (SELECT out_id FROM pairs UNION SELECT in_id FROM pairs)
              AND routing_tag IS NULL
        """, (req.case_id,))
        # 检测拆分转账：同日同对手≥3笔且单笔<50万 但合计>50万
        db.execute("""
            WITH splits AS (
                SELECT counterparty, txn_date, COUNT(*) AS cnt, SUM(txn_amount) AS total
                FROM transaction_signatures
                WHERE case_id=%s AND txn_direction='out' AND txn_amount < 500000
                GROUP BY counterparty, txn_date
                HAVING COUNT(*) >= 3 AND SUM(txn_amount) > 500000
            )
            UPDATE transaction_signatures t SET routing_tag='疑似拆分'
            WHERE t.case_id=%s AND routing_tag IS NULL
              AND EXISTS (SELECT 1 FROM splits s
                          WHERE s.counterparty=t.counterparty AND s.txn_date=t.txn_date)
        """, (req.case_id, req.case_id))
        # --- F3: retention_seconds 近似（天级精度→秒） ---
        # 当天有进有出，retention_seconds = 0（快进快出）
        db.execute("""
            UPDATE transaction_signatures t SET retention_seconds = 0
            WHERE t.case_id=%s AND retention_seconds IS NULL AND txn_direction='out'
              AND EXISTS (
                  SELECT 1 FROM transaction_signatures t2
                  WHERE t2.case_id=t.case_id AND t2.txn_date=t.txn_date
                    AND t2.txn_direction='in' AND t2.id != t.id
              )
        """, (req.case_id,))
        return {"target_table": "transaction_signatures", "record_id": None, "message": f"写入{count}条交易记录"}

    # 特殊处理：法院总对总（多种资产）
    if cat == "法院总对总":
        count = 0
        # 收集溢出字段（证券/保险/其他线索）
        overflow = {}
        for k in ("securities_hits", "insurance_hits", "other_hits"):
            if req.fields.get(k):
                overflow[k] = req.fields[k]
        extra_json = json.dumps(overflow, ensure_ascii=False, default=str) if overflow else None
        inquiry_dt = _coerce_value(req.fields.get("inquiry_date") or req.fields.get("query_date"), "date")
        for dep in req.fields.get("bank_deposits", []):
            frozen = dep.get("frozen_amount")
            notes = f"冻结金额:{frozen}" if frozen else None
            db.execute("""
                INSERT INTO bank_accounts (case_id, account_holder, bank_name, account_number_masked,
                    balance_at_inquiry, account_status, holder_type, inquiry_date, notes, extra_fields)
                VALUES (%s,%s,%s,%s,%s,%s,'债务人',%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, (req.case_id, req.fields.get("target_name"), dep.get("bank_name"),
                  dep.get("account_masked"),
                  _coerce_value(dep.get("balance"), "numeric"),
                  dep.get("status"), inquiry_dt, notes, extra_json))
            count += 1
        for re_hit in req.fields.get("real_estate_hits", []):
            db.execute("""
                INSERT INTO hidden_assets (case_id, debtor_id, asset_category, description, discovery_method, extra_fields)
                VALUES (%s,%s,'不动产',%s,'法院总对总',%s)
            """, (req.case_id, req.debtor_id,
                  f"{re_hit.get('location','')} 证号:{re_hit.get('cert_no','')} 面积:{re_hit.get('area_sqm','')}m² 状态:{re_hit.get('status','')}",
                  extra_json))
            count += 1
        for v in req.fields.get("vehicle_hits", []):
            db.execute("""
                INSERT INTO hidden_assets (case_id, debtor_id, asset_category, vehicle_plate,
                    vehicle_brand_model, description, discovery_method)
                VALUES (%s,%s,'动产',%s,%s,%s,'法院总对总')
            """, (req.case_id, req.debtor_id, v.get("plate_no"), v.get("brand_model"), f"车辆-{v.get('status')}"))
            count += 1
        return {"target_table": "多表", "record_id": None, "message": f"法院总对总写入{count}条记录"}

    # 特殊处理：煤矿重整方案
    if cat == "煤矿重整方案":
        f = req.fields
        # 溢出字段：全部保留到 extra_fields
        overflow = {k: v for k, v in f.items()
                    if v is not None and v != "" and k not in
                    ("administrator", "administrator_contact", "investor_name", "investor_contact",
                     "total_debt", "secured_debt", "unsecured_debt", "court_name", "case_number",
                     "proposed_recovery_rate")}
        extra_json = json.dumps(overflow, ensure_ascii=False, default=str) if overflow else None
        if f.get("administrator"):
            db.execute("""
                INSERT INTO contacts (case_id, role, org_name, person_name, phone, notes, extra_fields)
                VALUES (%s,'破产管理人',%s,%s,%s,%s,%s)
            """, (req.case_id, f.get("administrator"), f.get("administrator"),
                  f.get("administrator_contact"),
                  f"法院:{f.get('court_name','')} 案号:{f.get('case_number','')}",
                  extra_json))
        if f.get("investor_name"):
            db.execute("""
                INSERT INTO contacts (case_id, role, org_name, person_name, phone, notes, extra_fields)
                VALUES (%s,'重整投资人',%s,%s,%s,%s,%s)
            """, (req.case_id, f.get("investor_name"), f.get("investor_name"),
                  f.get("investor_contact"),
                  f"清偿率:{f.get('proposed_recovery_rate','')}%",
                  extra_json))
        # 协议转让底价写入 mining_evaluations（供引擎2价值倒挂探测使用）
        if f.get("transfer_base_price") and f.get("mine_name"):
            db.execute("""
                UPDATE mining_evaluations
                SET transfer_base_price = %s, updated_at = now()
                WHERE case_id = %s AND mine_name = %s
            """, (f["transfer_base_price"], req.case_id, f["mine_name"]))
            logger.info("[DocParser] 煤矿重整方案: mine_name=%s transfer_base_price=%s 已写入 mining_evaluations",
                        f["mine_name"], f["transfer_base_price"])
        # 重整方案派生 claim 写入：按类型 upsert（幂等，不再累积重复行）。
        # guarantee_type 收敛为稳定值（重整方案/职工债权/税款债权），作为 upsert 类型键；
        # 清偿率写入数值列 proposed_recovery_rate，不再塞进 guarantee_type 文本。
        # 依赖部分唯一索引 uq_claims_restructuring_type(case_id,debtor_id,guarantee_type)。
        _UPSERT_KEYS = ["case_id", "debtor_id", "guarantee_type"]
        _UPSERT_WHERE = "guarantee_type IN ('重整方案','职工债权','税款债权')"
        debt_fields = {}
        if f.get("total_debt"): debt_fields["total_claim"] = f["total_debt"]
        if f.get("secured_debt"): debt_fields["priority_amount"] = f["secured_debt"]
        if f.get("unsecured_debt"): debt_fields["general_amount"] = f["unsecured_debt"]
        if f.get("court_name"): debt_fields["court_name"] = f["court_name"]
        if f.get("case_number"): debt_fields["exec_case_no"] = f["case_number"]
        _rate = f.get("proposed_recovery_rate")
        if _rate not in (None, "", "None"):  # 仅在有真实清偿率时写，避免 upsert 把旧值覆盖成空
            debt_fields["proposed_recovery_rate"] = _rate
        debt_fields["litigation_status"] = "重整中"
        debt_fields["guarantee_type"] = "重整方案"
        if debt_fields:
            _generic_insert("claims", req.case_id, req.debtor_id, debt_fields,
                            list(debt_fields.keys()) + ["case_id", "debtor_id"],
                            upsert_keys=_UPSERT_KEYS, upsert_where=_UPSERT_WHERE)
        # S4: 职工债权和税款债权单独写入claims（同样按类型 upsert）
        if f.get("employee_debt"):
            _generic_insert("claims", req.case_id, req.debtor_id,
                            {"total_claim": f["employee_debt"], "guarantee_type": "职工债权", "litigation_status": "重整中"},
                            ["total_claim", "guarantee_type", "litigation_status", "case_id", "debtor_id"],
                            upsert_keys=_UPSERT_KEYS, upsert_where=_UPSERT_WHERE)
        if f.get("tax_debt"):
            _generic_insert("claims", req.case_id, req.debtor_id,
                            {"total_claim": f["tax_debt"], "guarantee_type": "税款债权", "litigation_status": "重整中"},
                            ["total_claim", "guarantee_type", "litigation_status", "case_id", "debtor_id"],
                            upsert_keys=_UPSERT_KEYS, upsert_where=_UPSERT_WHERE)
        return {"target_table": "contacts+claims", "record_id": None, "message": "重整方案已入库"}

    # 特殊处理：律师调查报告
    if cat == "律师调查报告":
        f = req.fields
        operating = f.get("physical_address_status", "") == "正常经营"
        if f.get("physical_address_status") in ("停业", "人去楼空"):
            cash = "差"
        elif f.get("employee_status") in ("已遣散", "少量留守"):
            cash = "一般"
        else:
            cash = "正常"
        asset_parts = []
        if f.get("asset_on_site"): asset_parts.append(f"现场资产:{f['asset_on_site']}")
        if f.get("lease_situation"): asset_parts.append(f"租赁:{f['lease_situation']}")
        if f.get("investigation_conclusion"): asset_parts.append(f"结论:{f['investigation_conclusion']}")
        asset_desc = "; ".join(asset_parts) if asset_parts else "无"
        # 溢出字段：全部其他字段保存
        used_keys = {"physical_address_status", "employee_status", "asset_on_site",
                     "lease_situation", "investigation_conclusion", "debtor_name",
                     "key_person_contacts", "related_party_findings", "asset_transfer_clues"}
        overflow = {k: v for k, v in f.items() if k not in used_keys and v is not None and v != ""}
        extra_json = json.dumps(overflow, ensure_ascii=False, default=str) if overflow else None
        # M9: 使用实际调查日期而非 CURRENT_DATE
        snap_date = _coerce_value(f.get("investigation_date"), "date")
        db.execute("""
            INSERT INTO risk_profiles (case_id, debtor_id, is_operating, cash_flow_status,
                executable_assets, data_source, snapshot_date, extra_fields)
            VALUES (%s,%s,%s,%s,%s,'律师调查',COALESCE(%s, CURRENT_DATE),%s)
            ON CONFLICT DO NOTHING
        """, (req.case_id, req.debtor_id, operating, cash, asset_desc, snap_date, extra_json))
        # 从 DB 查询债务人名称（Dify可能不发 debtor_name）
        _debtor_row = db.query_one("SELECT entity_name FROM debtors WHERE debtor_id=%s", (req.debtor_id,))
        _debtor_name = (_debtor_row["entity_name"] if _debtor_row else None) or f.get("debtor_name", "")
        for kp in f.get("key_person_contacts", []):
            db.execute("""
                INSERT INTO related_persons (case_id, person_name, relation_type, related_to, phone, notes)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (req.case_id, kp.get("name"), kp.get("role"), _debtor_name,
                  kp.get("phone"), kp.get("info_provided")))
        if f.get("related_party_findings"):
            db.execute("""
                INSERT INTO hidden_assets (case_id, debtor_id, asset_category, description, discovery_method)
                VALUES (%s,%s,'关联方线索',%s,'律师调查')
            """, (req.case_id, req.debtor_id, f["related_party_findings"]))
        if f.get("asset_transfer_clues"):
            db.execute("""
                INSERT INTO hidden_assets (case_id, debtor_id, asset_category, description, discovery_method)
                VALUES (%s,%s,'资产转移线索',%s,'律师调查')
            """, (req.case_id, req.debtor_id, f["asset_transfer_clues"]))
        return {"target_table": "risk_profiles+related_persons+hidden_assets", "record_id": None, "message": "律师调查信息已入库"}

    # 特殊处理：贷款合同 — 额外将 guarantor_names 写入 guarantors 表
    if cat == "贷款合同":
        gnames = req.fields.pop("guarantor_names", None) or []
        if isinstance(gnames, str):
            gnames = [g.strip() for g in gnames.split(",") if g.strip()]
        result = _generic_insert(target_table, req.case_id, req.debtor_id, req.fields, allowed + ["case_id", "debtor_id"])
        rid = list(result.values())[0] if result else None
        for gn in gnames:
            db.execute("""
                INSERT INTO guarantors (case_id, entity_name, guarantor_type)
                VALUES (%s,%s,'企业保证人')
                ON CONFLICT DO NOTHING
            """, (req.case_id, gn))
        msg = f"{cat}数据已写入{target_table}"
        if gnames:
            msg += f"，另写入{len(gnames)}条保证人"
        return {"target_table": target_table, "record_id": rid, "message": msg}

    # 通用路径
    if allowed:
        ukeys = None
        uwhere = None
        # 各表 UPSERT 策略（与数据库唯一索引保持一致）
        if target_table == "mining_evaluations" and req.fields.get("mine_name"):
            ukeys = ["case_id", "mine_name"]
            uwhere = "mine_name IS NOT NULL"
        elif target_table == "financial_snapshots" and req.fields.get("report_period"):
            # 财务报表：如果没有report_type，改用DO NOTHING以避免唯一约束冲突
            if not req.fields.get("report_type"):
                logger.debug("[DocParser] 财务报表缺少report_type，改用DO NOTHING策略")
                result = _generic_insert(target_table, req.case_id, req.debtor_id, req.fields,
                                       allowed + ["case_id", "debtor_id"], upsert_nothing=True)
                rid = result.get("id") if result else None
                return {"target_table": target_table, "record_id": rid, "message": f"{cat}数据已写入{target_table}"}
            ukeys = ["case_id", "debtor_id", "report_period", "report_type"]
        elif target_table == "legal_documents" and req.fields.get("case_number"):
            ukeys = ["case_id", "case_number"]
            uwhere = "case_number IS NOT NULL"
        elif target_table == "guarantors" and (req.fields.get("entity_name") or req.fields.get("guarantor_name")):
            # 唯一索引为函数索引 COALESCE(entity_name,'')，ON CONFLICT (cols) 无法匹配，改用 DO NOTHING
            result = _generic_insert(target_table, req.case_id, req.debtor_id, req.fields,
                                     allowed + ["case_id", "debtor_id"], upsert_nothing=True)
            rid = result.get("id") if result else None
            return {"target_table": target_table, "record_id": rid, "message": f"{cat}数据已写入{target_table}"}
        result = _generic_insert(target_table, req.case_id, req.debtor_id, req.fields,
                                 allowed + ["case_id", "debtor_id"], upsert_keys=ukeys,
                                 upsert_where=uwhere)
        rid = result.get("id") if result else None
        return {"target_table": target_table, "record_id": rid, "message": f"{cat}数据已写入{target_table}"}

    logger.info("[DocParser][ingest_structured_fields] 未调用_generic_insert | cat=%s | target_table=%s", cat, target_table)
    return {"target_table": target_table, "record_id": None, "message": "已处理"}


# ============================================================================
# EP 4 / 12：引擎1 — 轧差审计（增强版）
# POST /api/audit/delta-check
#
# 增强：幂等保护、逐期轧差趋势、扩展监控科目(+net_profit)、
#       所有期ε(收入+成本)、趋势检测、风险评分0-100
# ============================================================================

@app.post("/api/audit/delta-check")
def audit_delta_check(req: AuditReq):
    t0 = time.time()
    logger.info("[Engine1-Delta] case_id=%d 开始轧差审计", req.case_id)

    # 幂等：清除旧结果
    db.execute("DELETE FROM delta_audit_results WHERE case_id=%s", (req.case_id,))

    snapshots = db.query("""
        SELECT report_period, other_receivables, prepayments, revenue,
               operating_cost, tax_reported_revenue, tax_reported_cost, net_profit
        FROM financial_snapshots WHERE case_id = %s ORDER BY report_period
    """, (req.case_id,))

    if len(snapshots) < 2:
        logger.info("[Engine1-Delta] case_id=%d 数据不足(快照数=%d)", req.case_id, len(snapshots))
        return {"delta_results": [], "epsilon_results": [], "period_trend": [],
                "epsilon_trend": [], "risk_score": None,
                "verdict_summary": "数据不足：需要至少2期财务快照"}

    claims = db.query_one("SELECT COALESCE(SUM(principal),0) AS total_principal FROM claims WHERE case_id=%s", (req.case_id,))
    loan = float(claims["total_principal"]) if claims else 1
    if loan == 0:
        loan = 1

    # --- 逐期轧差（相邻两期） ---
    monitored_fields = [("other_receivables", "其他应收款"), ("prepayments", "预付账款"), ("net_profit", "净利润")]
    period_trend = []
    max_match_ratio = 0.0

    for i in range(len(snapshots) - 1):
        sa, sb = snapshots[i], snapshots[i + 1]
        for field, label in monitored_fields:
            a_val = float(sa[field] or 0)
            b_val = float(sb[field] or 0)
            delta = b_val - a_val
            match_ratio = abs(delta) / loan if loan > 0 else 0
            max_match_ratio = max(max_match_ratio, match_ratio)

            verdict = "正常波动"
            if match_ratio > 0.7:
                verdict = "空壳化抽逃"
            elif match_ratio > 0.3:
                verdict = "体外循环"

            period_trend.append({
                "period_a": sa["report_period"],
                "period_b": sb["report_period"],
                "account_item": label,
                "value_a": a_val,
                "value_b": b_val,
                "delta": delta,
                "match_ratio": round(match_ratio, 4),
                "verdict": verdict,
            })

    # 趋势检测：同一科目连续delta同向递增 → 持续恶化
    for field, label in monitored_fields:
        items = [p for p in period_trend if p["account_item"] == label]
        consecutive_increase = 0
        for j in range(1, len(items)):
            if items[j]["delta"] > 0 and items[j]["delta"] > items[j - 1]["delta"]:
                consecutive_increase += 1
            else:
                consecutive_increase = 0
            if consecutive_increase >= 2:
                items[j]["verdict"] = items[j]["verdict"] + " | 持续恶化"

    # --- 向后兼容 delta_results：取首末两期 ---
    baseline = snapshots[0]
    explosion = snapshots[-1]
    delta_results = []
    for field, label in monitored_fields:
        b_val = float(baseline[field] or 0)
        e_val = float(explosion[field] or 0)
        delta = e_val - b_val
        match_ratio = abs(delta) / loan

        verdict = "正常波动"
        if match_ratio > 0.7:
            verdict = "空壳化抽逃"
        elif match_ratio > 0.3:
            verdict = "体外循环"

        db.execute_returning("""
            INSERT INTO delta_audit_results (case_id, debtor_id, baseline_period, explosion_period,
                account_item, baseline_value, explosion_value, delta, loan_injection, match_ratio, verdict)
            SELECT %s, d.debtor_id, %s, %s, %s, %s, %s, %s, %s, %s, %s
            FROM debtors d WHERE d.case_id = %s LIMIT 1
            RETURNING id
        """, (req.case_id, baseline["report_period"], explosion["report_period"],
              label, b_val, e_val, delta, loan, round(match_ratio, 4), verdict, req.case_id))

        delta_results.append({
            "account_item": label,
            "baseline_period": baseline["report_period"],
            "baseline_value": b_val,
            "explosion_period": explosion["report_period"],
            "explosion_value": e_val,
            "delta": delta,
            "loan_injection": loan,
            "match_ratio": round(match_ratio, 4),
            "verdict": verdict,
        })

    # --- 所有期ε残差（收入侧+成本侧） ---
    epsilon_results = []   # 向后兼容（最后一期）
    epsilon_trend = []
    max_epsilon_pct = 0.0

    for snap in snapshots:
        rev = float(snap.get("revenue") or 0)
        tax_rev = float(snap.get("tax_reported_revenue") or 0)
        cost = float(snap.get("operating_cost") or 0)
        tax_cost = float(snap.get("tax_reported_cost") or 0)

        eps_rev_pct = abs(rev - tax_rev) / tax_rev if tax_rev > 0 else 0
        eps_cost_pct = abs(cost - tax_cost) / tax_cost if tax_cost > 0 else 0
        max_epsilon_pct = max(max_epsilon_pct, eps_rev_pct, eps_cost_pct)

        ev_rev = "正常(<10%)" if eps_rev_pct < 0.1 else "预警(10-30%)" if eps_rev_pct < 0.3 else "体外循环(>30%)"

        # 更新 financial_snapshots
        if tax_rev > 0:
            db.execute("""
                UPDATE financial_snapshots SET epsilon=%s, epsilon_pct=%s, epsilon_verdict=%s
                WHERE case_id=%s AND report_period=%s
            """, (abs(rev - tax_rev), round(eps_rev_pct, 4), ev_rev, req.case_id, snap["report_period"]))

        trend_row = {
            "period": snap["report_period"],
            "revenue_book": rev,
            "revenue_tax": tax_rev,
            "epsilon_pct": round(eps_rev_pct * 100, 2),
            "cost_book": cost,
            "cost_tax": tax_cost,
            "epsilon_cost_pct": round(eps_cost_pct * 100, 2),
            "verdict": ev_rev,
        }
        epsilon_trend.append(trend_row)

    # 向后兼容 epsilon_results（最后一期）
    if epsilon_trend:
        last = epsilon_trend[-1]
        if last["revenue_tax"] > 0:
            epsilon_results.append({
                "period": last["period"],
                "revenue_book": last["revenue_book"],
                "revenue_tax": last["revenue_tax"],
                "epsilon": abs(last["revenue_book"] - last["revenue_tax"]),
                "epsilon_pct": last["epsilon_pct"],
                "verdict": last["verdict"],
            })

    # --- 综合判定 ---
    verdicts = [d["verdict"] for d in delta_results] + [e["verdict"] for e in epsilon_results]
    worst = "体外循环(>30%)" if any("体外" in v for v in verdicts) else \
            "空壳化抽逃" if any("空壳" in v for v in verdicts) else "正常"

    # --- 风险评分 ---
    delta_score = min(max_match_ratio * 60 + max_epsilon_pct * 40, 100)
    delta_score = round(delta_score, 2)

    _upsert_risk_score(req.case_id, delta_score=delta_score)

    logger.info("[Engine1-Delta] case_id=%d 完成 | verdict=%s | score=%.1f | delta条数=%d epsilon条数=%d 趋势=%d期 | 耗时%dms",
                req.case_id, worst, delta_score, len(delta_results), len(epsilon_results),
                len(period_trend), int((time.time()-t0)*1000))

    return {
        "delta_results": delta_results,
        "epsilon_results": epsilon_results,
        "period_trend": period_trend,
        "epsilon_trend": epsilon_trend,
        "risk_score": delta_score,
        "verdict_summary": worst,
    }


# ============================================================================
# EP 5 / 12：引擎2 — 瑕疵挤水（增强版）
# POST /api/audit/valuation-squeeze
#
# 增强：乘法折扣、分级不动产折扣、采矿权分级扣分、五同限定案件、
#       持久化 valuation_audit_results、风险评分0-100
# ============================================================================

@app.post("/api/audit/valuation-squeeze")
def audit_valuation_squeeze(req: AuditReq):
    t0 = time.time()
    logger.info("[Engine2-Squeeze] case_id=%d 开始瑕疵挤水", req.case_id)

    # 幂等：清除旧结果
    db.execute("DELETE FROM valuation_audit_results WHERE case_id=%s", (req.case_id,))

    re_rows = db.query("SELECT * FROM real_estate_evaluations WHERE case_id=%s", (req.case_id,))
    me_rows = db.query("SELECT * FROM mining_evaluations WHERE case_id=%s", (req.case_id,))

    # 五同审计：限定本案关联企业
    five_same = db.query("""
        SELECT v.ent_a_name, v.ent_b_name,
               v.same_addr+v.same_phone+v.same_legal_rep+v.same_executive+v.same_industry AS score
        FROM v_five_same_audit v
        WHERE v.same_addr+v.same_phone+v.same_legal_rep+v.same_executive+v.same_industry >= 2
          AND (v.ent_a_name IN (SELECT entity_name FROM debtors WHERE case_id=%s)
               OR v.ent_b_name IN (SELECT entity_name FROM debtors WHERE case_id=%s))
        ORDER BY score DESC LIMIT 10
    """, (req.case_id, req.case_id))

    mining_flags = db.query("SELECT * FROM v_mining_compliance_flags WHERE case_id=%s", (req.case_id,))

    re_valuations = []
    total_gross, total_net = 0, 0

    for r in re_rows:
        gross = float(r.get("gross_value") or 0)
        discount = 1.0
        factors = {}

        # 分级不动产折扣（乘法模型）
        lease = str(r.get("lease_status") or "")
        if "出租" in lease:
            # 分级：长期/年限>5年 → ×0.5，其余 → ×0.8
            if "长期" in lease or "长租" in lease:
                discount *= 0.5
                factors["长期租约"] = 0.50
            else:
                discount *= 0.8
                factors["一般租约"] = 0.80
        if r.get("has_title_objection"):
            discount *= 0.7
            factors["权属异议"] = 0.70
        if r.get("seal_status") and "查封" in str(r.get("seal_status", "")):
            discount *= 0.9
            factors["查封中"] = 0.90
        if r.get("physical_occupation") and "第三方" in str(r.get("physical_occupation", "")):
            discount *= 0.8
            factors["第三方占用"] = 0.80
        # 新增：抵押顺位>1
        lien = r.get("lien_priority")
        if lien is not None and int(lien) > 1:
            discount *= 0.7
            factors["非首席抵押"] = 0.70

        net = gross * max(discount, 0.05)  # 下限5%防归零

        db.execute("UPDATE real_estate_evaluations SET net_value=%s, discount_factors=%s::jsonb WHERE id=%s",
                   (net, json.dumps(factors, ensure_ascii=False), r["id"]))

        # 持久化到 valuation_audit_results
        verdict = "高风险" if discount < 0.5 else "中风险" if discount < 0.8 else "低风险"
        db.execute("""
            INSERT INTO valuation_audit_results
                (case_id, asset_type, asset_id, asset_name, gross_value, discount_factors,
                 discount_rate, net_value, verdict)
            VALUES (%s, 'real_estate', %s, %s, %s, %s::jsonb, %s, %s, %s)
        """, (req.case_id, r["id"],
              r.get("property_address") or r.get("project_name"),
              gross, json.dumps(factors, ensure_ascii=False),
              round(discount, 4), round(net, 2), verdict))

        total_gross += gross
        total_net += net
        re_valuations.append({
            "property": r.get("property_address") or r.get("project_name"),
            "gross_value": gross,
            "discount_factors": factors,
            "discount_rate": round(discount, 4),
            "net_value": round(net, 2),
            "verdict": verdict,
        })

    me_valuations = []
    for m in me_rows:
        val = float(m.get("estimated_value") or 0)
        # 采矿权分级扣分：按具体flag类型
        flags_row = [f for f in mining_flags if f.get("case_id") == req.case_id]
        discount = 1.0
        factors = {}

        if flags_row:
            fr = flags_row[0]
            # 证照/安全类 → ×0.85 each
            if fr.get("permit_expired"):
                discount *= 0.85
                factors["采矿证过期"] = 0.85
            if fr.get("safety_permit_expired"):
                discount *= 0.85
                factors["安全许可过期"] = 0.85
            # 环评/其他类 → ×0.95 each
            if fr.get("env_not_approved"):
                discount *= 0.95
                factors["环评未通过"] = 0.95
            if fr.get("mining_right_sealed"):
                discount *= 0.90
                factors["采矿权查封"] = 0.90
            if fr.get("mining_right_mortgaged"):
                discount *= 0.90
                factors["采矿权抵押"] = 0.90

        net = val * max(discount, 0.05)
        total_gross += val
        total_net += net

        verdict = "高风险" if discount < 0.5 else "中风险" if discount < 0.8 else "低风险"
        db.execute("""
            INSERT INTO valuation_audit_results
                (case_id, asset_type, asset_id, asset_name, gross_value, discount_factors,
                 discount_rate, net_value, verdict)
            VALUES (%s, 'mining', %s, %s, %s, %s::jsonb, %s, %s, %s)
        """, (req.case_id, m.get("id"),
              m.get("mine_name"), val,
              json.dumps(factors, ensure_ascii=False),
              round(discount, 4), round(net, 2), verdict))

        me_valuations.append({
            "mine": m.get("mine_name"),
            "gross_value": val,
            "discount_factors": factors,
            "discount_rate": round(discount, 4),
            "net_value": round(net, 2),
            "verdict": verdict,
            "permit_expiry": str(m["permit_expiry"]) if m.get("permit_expiry") else None,
            "mining_status": m.get("mining_status"),
            "mineral_type": m.get("mineral_type"),
            "proved_reserves": float(m["proved_reserves"]) if m.get("proved_reserves") else None,
            "total_reserves": float(m["total_reserves"]) if m.get("total_reserves") else None,
            "calorific_value": float(m["calorific_value"]) if m.get("calorific_value") else None,
            "ash_content_pct": float(m["ash_content_pct"]) if m.get("ash_content_pct") else None,
            "sulfur_content_pct": float(m["sulfur_content_pct"]) if m.get("sulfur_content_pct") else None,
            "coal_type": m.get("coal_type"),
            "annual_capacity": float(m["annual_capacity"]) if m.get("annual_capacity") else None,
            "env_approval_status": m.get("env_approval_status"),
            "safety_permit_status": m.get("safety_permit_status"),
        })

    claims_total = db.query_one("SELECT COALESCE(SUM(total_claim),1) AS t FROM claims WHERE case_id=%s", (req.case_id,))
    recovery = total_net / float(claims_total["t"]) if float(claims_total["t"]) > 0 else 0

    # 风险评分：(1 - recovery_rate) * 70 + min(five_same_count * 10, 30)
    valuation_score = min((1 - recovery) * 70 + min(len(five_same) * 10, 30), 100)
    valuation_score = round(max(valuation_score, 0), 2)
    _upsert_risk_score(req.case_id, valuation_score=valuation_score)

    logger.info("[Engine2-Squeeze] case_id=%d 完成 | 不动产%d项 采矿权%d项 | 账面%.2f万→净值%.2f万 回收率%.1f%% score=%.1f | 耗时%dms",
                req.case_id, len(re_valuations), len(me_valuations),
                total_gross/10000, total_net/10000, recovery*100,
                valuation_score, int((time.time()-t0)*1000))

    return {
        "real_estate_valuations": re_valuations,
        "mining_valuations": me_valuations,
        "five_same_audit": [dict(r) for r in five_same],
        "total_gross_value": round(total_gross, 2),
        "total_net_value": round(total_net, 2),
        "recovery_rate": round(recovery * 100, 2),
        "risk_score": valuation_score,
        "discount_summary": f"账面总值{total_gross/10000:.2f}万 → 去毒后{total_net/10000:.2f}万，回收率{recovery*100:.1f}%"
    }


# ============================================================================
# EP 6 / 12：引擎3 — 时效预警（增强版）
# POST /api/audit/deadline-scan
#
# 增强：已过期分类、动作建议文案增强、风险评分0-100
# ============================================================================

@app.post("/api/audit/deadline-scan")
def audit_deadline_scan(req: AuditReq):
    t0 = time.time()
    logger.info("[Engine3-Deadline] case_id=%d 开始时效预警扫描", req.case_id)

    db.execute("SELECT refresh_deadline_alerts()")
    alerts = db.query("SELECT * FROM deadline_alerts WHERE case_id=%s ORDER BY deadline_date", (req.case_id,))

    expired, red, yellow, green = [], [], [], []
    for a in alerts:
        d = dict(a)
        days = d.get("days_remaining")
        alert_type = str(d.get("alert_type") or "")
        base_action = str(d.get("action_required") or "")

        # 动作建议增强
        if days is not None and days < 0:
            d["suggested_action"] = f"已过期！需立即处理：{base_action}（已超期{abs(days)}天）"
        elif d.get("severity") == "red":
            if "查封" in alert_type:
                d["suggested_action"] = f"紧急：距到期仅{days}天，需立即向法院提交续封申请"
            elif "采矿" in alert_type:
                d["suggested_action"] = f"紧急：采矿许可即将到期，需在{days}天内申请延续登记"
            else:
                d["suggested_action"] = f"紧急：距到期{days}天，{base_action}"
        elif d.get("severity") == "yellow":
            d["suggested_action"] = f"预警：距到期{days}天，{base_action}"
        else:
            d["suggested_action"] = base_action

        # 序列化日期
        for k, v in d.items():
            if isinstance(v, (date, datetime)):
                d[k] = str(v)

        # 分类
        if days is not None and days < 0:
            expired.append(d)
        elif d.get("severity") == "red":
            red.append(d)
        elif d.get("severity") == "yellow":
            yellow.append(d)
        else:
            green.append(d)

    # 风险评分：expired×50 + red×30 + yellow×10, 上限100
    deadline_score = min(len(expired) * 50 + len(red) * 30 + len(yellow) * 10, 100)
    deadline_score = round(float(deadline_score), 2)
    _upsert_risk_score(req.case_id, deadline_score=deadline_score)

    logger.info("[Engine3-Deadline] case_id=%d 完成 | expired=%d red=%d yellow=%d green=%d score=%.1f | 耗时%dms",
                req.case_id, len(expired), len(red), len(yellow), len(green),
                deadline_score, int((time.time()-t0)*1000))

    return {
        "expired_alerts": expired,
        "red_alerts": red,
        "yellow_alerts": yellow,
        "green_alerts": green,
        "risk_score": deadline_score,
    }


# ============================================================================
# EP 7 / 12：引擎4 — 心理指纹（增强版）
# POST /api/audit/behavioral-scan
#
# 增强：幂等保护、时间模式检测(连续小额)、签字链异常检测(越权/独裁/关联方集中)、
#       白手套限定本案企业、金额异常(整数大额/拆分/过桥)、持久化、风险评分0-100
# ============================================================================

@app.post("/api/audit/behavioral-scan")
def audit_behavioral_scan(req: AuditReq):
    t0 = time.time()
    logger.info("[Engine4-Behavioral] case_id=%d 开始心理指纹扫描", req.case_id)

    # 幂等：清除旧结果
    db.execute("DELETE FROM behavioral_audit_results WHERE case_id=%s", (req.case_id,))

    # ---- 表演性还款标记 ----
    claims = db.query_one("SELECT COALESCE(SUM(principal),0) AS p FROM claims WHERE case_id=%s", (req.case_id,))
    principal = float(claims["p"]) if claims else 0

    if principal > 0:
        threshold = principal * 0.0001
        db.execute("""
            UPDATE repayment_behaviors SET
                is_performative = (payment_amount < %s),
                principal_ratio = payment_amount / %s,
                pattern_tag = CASE
                    WHEN payment_amount < %s THEN '表演性周期汇入'
                    WHEN payment_amount < %s * 0.01 THEN '选择性还款'
                    ELSE '实质还款' END
            WHERE case_id = %s
        """, (threshold, principal, threshold, principal, req.case_id))

    perf = db.query("""
        SELECT payment_date, payment_amount, principal_ratio, is_performative, pattern_tag
        FROM repayment_behaviors WHERE case_id=%s ORDER BY payment_date
    """, (req.case_id,))

    # 时间模式：按月统计，连续≥3月存在小额还款 → high_confidence
    high_confidence_performative = False
    if principal > 0:
        monthly = db.query("""
            SELECT to_char(payment_date, 'YYYY-MM') AS ym,
                   bool_or(payment_amount < %s) AS has_small
            FROM repayment_behaviors WHERE case_id=%s
            GROUP BY ym ORDER BY ym
        """, (principal * 0.0001, req.case_id))
        consec = 0
        for row in monthly:
            if row["has_small"]:
                consec += 1
                if consec >= 3:
                    high_confidence_performative = True
                    break
            else:
                consec = 0

    performative_count = sum(1 for p in perf if p.get("is_performative"))
    performative_ratio = performative_count / len(perf) if perf else 0

    # 持久化表演性还款
    if perf:
        db.execute("""
            INSERT INTO behavioral_audit_results (case_id, analysis_type, target_name, detail, risk_score, verdict)
            VALUES (%s, 'performative_payment', '还款行为', %s::jsonb, %s, %s)
        """, (req.case_id,
              json.dumps({"count": len(perf), "performative_count": performative_count,
                          "ratio": round(performative_ratio, 4),
                          "high_confidence": high_confidence_performative}, ensure_ascii=False),
              round(performative_ratio * 100, 2),
              "高置信表演性还款" if high_confidence_performative else
              "疑似表演性还款" if performative_ratio > 0.5 else "正常"))

    # ---- 签字链分析（保留原始） ----
    sigs = db.query("""
        SELECT approver, maker, reviewer, counterparty, is_related_party, routing_tag,
               COUNT(*) AS txn_count, SUM(txn_amount) AS total_amount
        FROM transaction_signatures WHERE case_id=%s
        GROUP BY approver, maker, reviewer, counterparty, is_related_party, routing_tag
        ORDER BY total_amount DESC
    """, (req.case_id,))

    # ---- 签字链异常检测 ----
    signature_anomalies = []

    # 1. 越权签字：maker = approver
    override = db.query("""
        SELECT maker, COUNT(*) AS txn_count, SUM(txn_amount) AS total_amount
        FROM transaction_signatures
        WHERE case_id=%s AND maker IS NOT NULL AND approver IS NOT NULL AND maker = approver
        GROUP BY maker
    """, (req.case_id,))
    for row in override:
        anomaly = {"type": "越权签字", "person": row["maker"],
                   "txn_count": row["txn_count"],
                   "total_amount": float(row["total_amount"] or 0)}
        signature_anomalies.append(anomaly)
        db.execute("""
            INSERT INTO behavioral_audit_results (case_id, analysis_type, target_name, detail, risk_score, verdict)
            VALUES (%s, 'signature_anomaly', %s, %s::jsonb, %s, '越权签字')
        """, (req.case_id, row["maker"], json.dumps(anomaly, ensure_ascii=False), 80))

    # 2. 独裁签字：单一approver覆盖>80%交易
    total_txn = db.query_one("SELECT COUNT(*) AS c FROM transaction_signatures WHERE case_id=%s", (req.case_id,))
    total_c = int(total_txn["c"]) if total_txn else 0
    if total_c > 0:
        top_approver = db.query("""
            SELECT approver, COUNT(*) AS cnt
            FROM transaction_signatures WHERE case_id=%s AND approver IS NOT NULL
            GROUP BY approver ORDER BY cnt DESC LIMIT 1
        """, (req.case_id,))
        if top_approver and int(top_approver[0]["cnt"]) / total_c > 0.8:
            anomaly = {"type": "独裁签字", "person": top_approver[0]["approver"],
                       "coverage": round(int(top_approver[0]["cnt"]) / total_c * 100, 1)}
            signature_anomalies.append(anomaly)
            db.execute("""
                INSERT INTO behavioral_audit_results (case_id, analysis_type, target_name, detail, risk_score, verdict)
                VALUES (%s, 'signature_anomaly', %s, %s::jsonb, %s, '独裁签字')
            """, (req.case_id, top_approver[0]["approver"],
                  json.dumps(anomaly, ensure_ascii=False), 70))

    # 3. 关联方签字集中
    related_approvers = db.query("""
        SELECT approver, COUNT(*) AS cnt, SUM(txn_amount) AS total_amount
        FROM transaction_signatures
        WHERE case_id=%s AND is_related_party=TRUE AND approver IS NOT NULL
        GROUP BY approver ORDER BY cnt DESC
    """, (req.case_id,))
    for ra in related_approvers:
        anomaly = {"type": "关联方签字集中", "person": ra["approver"],
                   "txn_count": ra["cnt"], "total_amount": float(ra["total_amount"] or 0)}
        signature_anomalies.append(anomaly)
        db.execute("""
            INSERT INTO behavioral_audit_results (case_id, analysis_type, target_name, detail, risk_score, verdict)
            VALUES (%s, 'signature_anomaly', %s, %s::jsonb, %s, '关联方签字集中')
        """, (req.case_id, ra["approver"], json.dumps(anomaly, ensure_ascii=False), 60))

    # ---- 金额异常检测 ----
    amount_anomalies = []

    # 整数大额：txn_amount % 1000000 = 0 且 >500000
    round_txns = db.query("""
        SELECT txn_date, txn_amount, counterparty
        FROM transaction_signatures
        WHERE case_id=%s AND txn_amount > 500000
          AND txn_amount::bigint %% 1000000 = 0
    """, (req.case_id,))
    for rt in round_txns:
        anomaly = {"type": "整数大额", "txn_date": str(rt["txn_date"]),
                   "amount": float(rt["txn_amount"] or 0), "counterparty": rt["counterparty"]}
        amount_anomalies.append(anomaly)

    # 拆分转账：同日同counterparty多笔，合计>50万但单笔<50万
    splits = db.query("""
        SELECT txn_date, counterparty, COUNT(*) AS cnt, SUM(txn_amount) AS total
        FROM transaction_signatures
        WHERE case_id=%s AND txn_amount < 500000
        GROUP BY txn_date, counterparty
        HAVING COUNT(*) >= 2 AND SUM(txn_amount) > 500000
    """, (req.case_id,))
    for sp in splits:
        anomaly = {"type": "疑似拆分", "txn_date": str(sp["txn_date"]),
                   "counterparty": sp["counterparty"], "count": sp["cnt"],
                   "total": float(sp["total"] or 0)}
        amount_anomalies.append(anomaly)

    # 资金滞留：retention_seconds < 300（5分钟内转出）
    bridge = db.query("""
        SELECT txn_date, txn_amount, counterparty, retention_seconds
        FROM transaction_signatures
        WHERE case_id=%s AND retention_seconds IS NOT NULL AND retention_seconds < 300
    """, (req.case_id,))
    for br in bridge:
        anomaly = {"type": "过桥资金", "txn_date": str(br["txn_date"]),
                   "amount": float(br["txn_amount"] or 0), "counterparty": br["counterparty"],
                   "retention_seconds": br["retention_seconds"]}
        amount_anomalies.append(anomaly)

    # 持久化金额异常
    for aa in amount_anomalies:
        db.execute("""
            INSERT INTO behavioral_audit_results (case_id, analysis_type, target_name, detail, risk_score, verdict)
            VALUES (%s, 'amount_anomaly', %s, %s::jsonb, %s, %s)
        """, (req.case_id, aa.get("counterparty", ""),
              json.dumps(aa, ensure_ascii=False), 50, aa["type"]))

    # ---- 白手套嫌疑人（限定本案关联企业） ----
    suspects = db.query("""
        SELECT ex.person_name, array_agg(DISTINCT e.entity_name) AS companies,
               array_agg(DISTINCT ex.position) AS positions, count(DISTINCT ex.enterprise_id) AS company_count
        FROM executives ex
        JOIN enterprises e ON ex.enterprise_id = e.enterprise_id
        JOIN debtors d ON d.case_id = %s
        WHERE ex.departure_date IS NULL
          AND e.entity_name IN (
              SELECT entity_name FROM debtors WHERE case_id = %s
              UNION
              SELECT ent_b_name FROM v_five_same_audit
              WHERE ent_a_name IN (SELECT entity_name FROM debtors WHERE case_id = %s)
                AND same_addr+same_phone+same_legal_rep+same_executive+same_industry >= 2
          )
        GROUP BY ex.person_name HAVING count(DISTINCT ex.enterprise_id) >= 2
        ORDER BY company_count DESC
    """, (req.case_id, req.case_id, req.case_id))

    # 持久化白手套
    for s in suspects:
        db.execute("""
            INSERT INTO behavioral_audit_results (case_id, analysis_type, target_name, detail, risk_score, verdict)
            VALUES (%s, 'whiteglove', %s, %s::jsonb, %s, '白手套嫌疑')
        """, (req.case_id, s["person_name"],
              json.dumps({"companies": s["companies"], "positions": s["positions"],
                          "company_count": s["company_count"]}, ensure_ascii=False),
              min(s["company_count"] * 30, 100)))

    # ---- 结果序列化 ----
    result_perf = []
    for p in perf:
        d = dict(p)
        for k, v in d.items():
            if isinstance(v, (date, datetime)):
                d[k] = str(v)
            elif hasattr(v, 'as_integer_ratio'):
                d[k] = float(v)
        result_perf.append(d)

    # ---- 风险评分 ----
    behavioral_score = min(
        performative_ratio * 30 +
        len(amount_anomalies) * 15 +
        len(suspects) * 20 +
        len(splits) * 10,
        100
    )
    behavioral_score = round(behavioral_score, 2)
    _upsert_risk_score(req.case_id, behavioral_score=behavioral_score)

    logger.info(
        "[Engine4-Behavioral] case_id=%d 完成 | 表演性还款=%d条 签字异常=%d 金额异常=%d 白手套=%d人 score=%.1f | 耗时%dms",
        req.case_id, len(result_perf), len(signature_anomalies), len(amount_anomalies),
        len(suspects), behavioral_score, int((time.time()-t0)*1000))

    return {
        "performative_payments": result_perf,
        "high_confidence_performative": high_confidence_performative,
        "signature_chain": [dict(s) for s in sigs],
        "signature_anomalies": signature_anomalies,
        "amount_anomalies": amount_anomalies,
        "whiteglove_suspects": [dict(s) for s in suspects],
        "risk_score": behavioral_score,
    }


# ============================================================================
# EP 8 / 13：案件列表
# GET /api/cases
# ============================================================================

@app.get(
    "/api/cases",
    tags=["案件查询"],
    summary="获取案件信息列表",
    description=(
        "分页返回案件列表，可按案件名称/债务人名称关键词、案件类型、案件状态筛选。"
        "传入 company_id 后启用租户隔离：普通用户仅可见 owner 或 case_member active 成员案件。"
        "is_company_admin / is_super_admin 仅在请求携带有效服务间 Authorization: Bearer <AUDIT_API_TOKEN> 时生效；"
        "未带服务 token 的管理员标记会被忽略。"
        "结果会附带债务人摘要、综合风险分、任务统计，适合列表页和工具调用。"
        "其中 composite_score 为综合风险分，delta_score / valuation_score / deadline_score / behavioral_score "
        "分别对应轧差审计、瑕疵挤水、时效预警、行为扫描四个引擎的分数。"
    ),
)
def list_cases(
    request: Request,
    keyword: Optional[str] = Query(None, description="关键词：匹配案件名称或债务人名称"),
    case_type: Optional[str] = Query(None, description="案件类型，如：单户/资产包/破产重整/执转破"),
    status: Optional[str] = Query(None, description="案件状态，如：进行中/已结案/暂停"),
    company_id: Optional[str] = Query(None, description="租户公司ID；传入后按公司隔离。不传时保留旧内部调用行为。"),
    user_id: Optional[str] = Query(None, description="当前用户ID；普通用户仅返回 owner 或 case_member active 成员案件。"),
    is_company_admin: bool = Query(False, description="是否公司管理员；仅带有效 AUDIT_API_TOKEN 的服务调用会采信。"),
    is_super_admin: bool = Query(False, description="是否全局超级管理员；仅带有效 AUDIT_API_TOKEN 的服务调用会采信。"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，最大100"),
):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    offset = (page - 1) * page_size

    where_clauses = []
    params = []

    if keyword:
        where_clauses.append("""
            (
                c.case_name ILIKE %s
                OR EXISTS (
                    SELECT 1 FROM debtors d2
                    WHERE d2.case_id = c.case_id
                      AND d2.entity_name ILIKE %s
                )
            )
        """)
        kw = f"%{keyword.strip()}%"
        params.extend([kw, kw])

    if case_type:
        where_clauses.append("c.case_type = %s")
        params.append(case_type)

    if status:
        where_clauses.append("c.status = %s")
        params.append(status)

    trusted_company_admin, trusted_super_admin = _trusted_admin_flags(
        request,
        is_company_admin=is_company_admin,
        is_super_admin=is_super_admin,
    )
    visibility_clauses, visibility_params = _case_visibility_clause(
        company_id=company_id,
        user_id=user_id,
        is_company_admin=trusted_company_admin,
        is_super_admin=trusted_super_admin,
        table_alias="c",
    )
    where_clauses.extend(visibility_clauses)
    params.extend(visibility_params)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    total_row = db.query_one(
        f"SELECT COUNT(*) AS total FROM cases c {where_sql}",
        tuple(params),
    )
    total = int(total_row["total"]) if total_row else 0

    rows = db.query(f"""
        SELECT
            c.case_id,
            c.case_name,
            c.case_type,
            c.status,
            c.company_id,
            c.owner_id,
            c.created_by,
            c.created_at,
            c.updated_at,
            COALESCE(d.debtor_count, 0) AS debtor_count,
            d.debtor_names,
            ars.composite_score,
            ars.delta_score,
            ars.valuation_score,
            ars.deadline_score,
            ars.behavioral_score,
            COALESCE(t.task_count, 0) AS task_count,
            COALESCE(t.pending_task_count, 0) AS pending_task_count
        FROM cases c
        LEFT JOIN (
            SELECT
                case_id,
                COUNT(*) AS debtor_count,
                string_agg(entity_name, ' | ' ORDER BY debtor_id) AS debtor_names
            FROM debtors
            GROUP BY case_id
        ) d ON d.case_id = c.case_id
        LEFT JOIN audit_risk_scores ars ON ars.case_id = c.case_id
        LEFT JOIN (
            SELECT
                case_id,
                COUNT(*) AS task_count,
                COUNT(*) FILTER (WHERE status IN ('待执行', '进行中', '逾期')) AS pending_task_count
            FROM tasks
            GROUP BY case_id
        ) t ON t.case_id = c.case_id
        {where_sql}
        ORDER BY c.created_at DESC, c.case_id DESC
        LIMIT %s OFFSET %s
    """, tuple(params + [page_size, offset]))

    cases = []
    for row in rows:
        d = dict(row)
        for k, v in d.items():
            if isinstance(v, (date, datetime)):
                d[k] = str(v)
            elif hasattr(v, 'as_integer_ratio') and not isinstance(v, (int, float)):
                d[k] = float(v)
        cases.append(d)

    logger.info("[ListCases] page=%d page_size=%d total=%d keyword=%s", page, page_size, total, keyword)
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "cases": cases,
    }


@app.get(
    "/api/cases/{case_id}/members",
    tags=["案件成员"],
    summary="查询案件成员",
    description=(
        "返回当前调用身份有权读取的案件成员。必须携带服务间 Authorization: Bearer <AUDIT_API_TOKEN>。"
        "普通用户需为案件 owner 或 active member；公司管理员仅可访问本公司案件；超级管理员可跨公司。"
    ),
    response_model=CaseMemberListResp,
)
def list_case_members(
    request: Request,
    case_id: int,
    company_id: Optional[str] = Query(None, description="当前身份所属公司ID。普通用户和公司管理员必传。"),
    user_id: Optional[str] = Query(None, description="当前操作用户ID。普通用户必传。"),
    is_company_admin: bool = Query(False, description="是否公司管理员；仅有效服务 token 调用会采信。"),
    is_super_admin: bool = Query(False, description="是否全局超级管理员；仅有效服务 token 调用会采信。"),
):
    _require_service_token(request)
    case, _, _ = _get_visible_case(
        request,
        case_id=case_id,
        company_id=company_id,
        user_id=user_id,
        is_company_admin=is_company_admin,
        is_super_admin=is_super_admin,
    )
    rows = db.query(
        """
        SELECT cm.case_id, cm.company_id, cm.user_id,
               COALESCE(u.username, '') AS username,
               cm.member_role, cm.status, cm.added_by,
               cm.created_at, cm.updated_at
        FROM case_member cm
        LEFT JOIN app_user u ON u.user_id = cm.user_id
        WHERE cm.case_id = %s AND cm.company_id = %s
        ORDER BY cm.status, cm.created_at, cm.user_id
        """,
        (case_id, case["company_id"]),
    )
    members = []
    for row in rows:
        item = dict(row)
        for key in ("created_at", "updated_at"):
            if item.get(key) is not None:
                item[key] = str(item[key])
        members.append(item)
    return {"case_id": case_id, "company_id": case["company_id"], "members": members}


@app.put(
    "/api/cases/{case_id}/members/{member_user_id}",
    tags=["案件成员"],
    summary="新增或更新案件成员",
    description=(
        "新增成员、修改案件内角色或把 status 设为 disabled 进行软移除。"
        "必须携带服务间 Authorization: Bearer <AUDIT_API_TOKEN>；仅案件 owner、公司管理员、全局超级管理员可操作。"
        "目标用户必须存在于 app_user 且与案件属于同一公司，company_id 由案件主表决定。"
    ),
    response_model=CaseMemberItem,
)
def upsert_case_member(
    request: Request,
    case_id: int,
    member_user_id: str,
    payload: CaseMemberUpsertReq,
    company_id: Optional[str] = Query(None, description="当前身份所属公司ID。公司管理员和普通 owner 必传。"),
    user_id: Optional[str] = Query(None, description="当前操作用户ID；写入 added_by，案件 owner 操作时必传。"),
    is_company_admin: bool = Query(False, description="是否公司管理员；仅有效服务 token 调用会采信。"),
    is_super_admin: bool = Query(False, description="是否全局超级管理员；仅有效服务 token 调用会采信。"),
):
    _require_service_token(request)
    actor_user_id = (user_id or "").strip()
    target_user_id = (member_user_id or "").strip()
    if not actor_user_id:
        raise HTTPException(422, "成员管理必须提供当前操作人 user_id")
    if not target_user_id:
        raise HTTPException(422, "member_user_id 不能为空")
    case, trusted_company_admin, trusted_super_admin = _get_visible_case(
        request,
        case_id=case_id,
        company_id=company_id,
        user_id=actor_user_id,
        is_company_admin=is_company_admin,
        is_super_admin=is_super_admin,
    )
    if not (trusted_super_admin or trusted_company_admin or case.get("owner_id") == actor_user_id):
        raise HTTPException(403, "仅案件 owner、公司管理员或全局超级管理员可管理成员")

    target_user = db.query_one(
        "SELECT user_id, username, company_id FROM app_user WHERE user_id = %s AND status = 'active'",
        (target_user_id,),
    )
    if not target_user:
        raise HTTPException(404, "目标用户不存在或已停用")
    if str(target_user.get("company_id") or "") != str(case["company_id"]):
        raise HTTPException(409, "目标用户与案件不属于同一公司")

    row = db.execute_returning(
        """
        INSERT INTO case_member (
            case_id, company_id, user_id, member_role, status, added_by
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (case_id, user_id) DO UPDATE SET
            company_id = EXCLUDED.company_id,
            member_role = EXCLUDED.member_role,
            status = EXCLUDED.status,
            added_by = EXCLUDED.added_by,
            updated_at = now()
        RETURNING case_id, company_id, user_id, member_role, status, added_by, created_at, updated_at
        """,
        (
            case_id,
            case["company_id"],
            target_user_id,
            payload.member_role.strip(),
            payload.status,
            actor_user_id,
        ),
    )
    result = dict(row)
    result["username"] = str(target_user.get("username") or "")
    for key in ("created_at", "updated_at"):
        if result.get(key) is not None:
            result[key] = str(result[key])
    return result


@app.get(
    "/api/cases/{case_id}/parties",
    tags=["案件参与方"],
    summary="查询案件参与方",
    description=(
        "返回债务人、资产购买方、债权人、保证人、管理人等结构化案件参与方。"
        "必须携带服务间 Authorization: Bearer <AUDIT_API_TOKEN>；普通用户需为案件 owner "
        "或 active member，公司管理员仅可访问本公司案件，超级管理员可跨公司。"
    ),
    response_model=CasePartyListResp,
)
def list_case_parties(
    request: Request,
    case_id: int,
    status: Optional[Literal["active", "disabled"]] = Query(None, description="可选参与方状态过滤。"),
    company_id: Optional[str] = Query(None, description="当前身份所属公司ID。普通用户和公司管理员必传。"),
    user_id: Optional[str] = Query(None, description="当前操作用户ID。普通用户必传。"),
    is_company_admin: bool = Query(False, description="是否公司管理员；仅有效服务 token 调用会采信。"),
    is_super_admin: bool = Query(False, description="是否全局超级管理员；仅有效服务 token 调用会采信。"),
):
    _require_service_token(request)
    _get_visible_case(
        request,
        case_id=case_id,
        company_id=company_id,
        user_id=user_id,
        is_company_admin=is_company_admin,
        is_super_admin=is_super_admin,
    )
    clauses = ["case_id = %s"]
    params: list[Any] = [case_id]
    if status:
        clauses.append("status = %s")
        params.append(status)
    rows = db.query(
        f"""
        SELECT party_id, case_id, debtor_id, party_name, party_role, uscc,
               is_primary, status, source_type, extra_fields, created_by,
               created_at, updated_at
        FROM case_party
        WHERE {' AND '.join(clauses)}
        ORDER BY status, party_role, is_primary DESC, party_id
        """,
        tuple(params),
    )
    parties = []
    for row in rows:
        item = dict(row)
        for key in ("created_at", "updated_at"):
            if item.get(key) is not None:
                item[key] = str(item[key])
        parties.append(item)
    return {"case_id": case_id, "parties": parties}


@app.post(
    "/api/cases/{case_id}/parties",
    tags=["案件参与方"],
    summary="新增或更新案件参与方",
    description=(
        "幂等登记资产购买方、债权人、保证人、管理人或其他非债务人角色。"
        "债务人只能通过建案/债务人专项流程维护，不能通过本接口写入。"
        "必须携带服务间 Authorization: Bearer <AUDIT_API_TOKEN>；仅案件 owner、公司管理员、"
        "全局超级管理员可操作。"
    ),
    response_model=CasePartyItem,
)
def upsert_case_party(
    request: Request,
    case_id: int,
    payload: CasePartyUpsertReq,
    company_id: Optional[str] = Query(None, description="当前身份所属公司ID。公司管理员和普通 owner 必传。"),
    user_id: Optional[str] = Query(None, description="当前操作用户ID；写入 created_by。"),
    is_company_admin: bool = Query(False, description="是否公司管理员；仅有效服务 token 调用会采信。"),
    is_super_admin: bool = Query(False, description="是否全局超级管理员；仅有效服务 token 调用会采信。"),
):
    _require_service_token(request)
    actor_user_id = (user_id or "").strip()
    party_name = (payload.party_name or "").strip()
    if not actor_user_id:
        raise HTTPException(422, "参与方管理必须提供当前操作人 user_id")
    if not party_name:
        raise HTTPException(422, "party_name 不能为空")
    case, trusted_company_admin, trusted_super_admin = _get_visible_case(
        request,
        case_id=case_id,
        company_id=company_id,
        user_id=actor_user_id,
        is_company_admin=is_company_admin,
        is_super_admin=is_super_admin,
    )
    if not (trusted_super_admin or trusted_company_admin or case.get("owner_id") == actor_user_id):
        raise HTTPException(403, "仅案件 owner、公司管理员或全局超级管理员可管理参与方")

    is_primary = bool(payload.is_primary and payload.status == "active")
    row = db.execute_returning(
        """
        INSERT INTO case_party (
            case_id, party_name, party_role, uscc, is_primary,
            status, source_type, extra_fields, created_by
        ) VALUES (%s, %s, %s, %s, %s, %s, 'manual', %s::jsonb, %s)
        ON CONFLICT (case_id, party_name, party_role) DO UPDATE SET
            uscc = COALESCE(EXCLUDED.uscc, case_party.uscc),
            is_primary = EXCLUDED.is_primary,
            status = EXCLUDED.status,
            extra_fields = EXCLUDED.extra_fields,
            created_by = EXCLUDED.created_by,
            updated_at = now()
        RETURNING party_id, case_id, debtor_id, party_name, party_role, uscc,
                  is_primary, status, source_type, extra_fields, created_by,
                  created_at, updated_at
        """,
        (
            case_id,
            party_name,
            payload.party_role,
            (payload.uscc or "").strip() or None,
            is_primary,
            payload.status,
            json.dumps(payload.extra_fields, ensure_ascii=False),
            actor_user_id,
        ),
    )
    result = dict(row)
    for key in ("created_at", "updated_at"):
        if result.get(key) is not None:
            result[key] = str(result[key])
    return result


# ============================================================================
# EP 8 / 12：案件全景（增强版 — 含综合风险评分）
# GET /api/case/{case_id}/profile
# ============================================================================

@app.get(
    "/api/case/{case_id}/profile",
    tags=["案件查询"],
    summary="获取案件画像",
    description=(
        "返回案件画像和关联数据。传入 company_id 后启用租户隔离：普通用户仅可访问 owner "
        "或 case_member active 成员案件。is_company_admin / is_super_admin 仅在请求携带有效服务间 "
        "Authorization: Bearer <AUDIT_API_TOKEN> 时生效；未带服务 token 的管理员标记会被忽略。"
    ),
)
def get_case_profile(
    request: Request,
    case_id: int,
    company_id: Optional[str] = Query(None, description="租户公司ID；传入后按公司隔离。不传时保留旧内部调用行为。"),
    user_id: Optional[str] = Query(None, description="当前用户ID；普通用户仅允许 owner 或 case_member active 成员访问。"),
    is_company_admin: bool = Query(False, description="是否公司管理员；仅带有效 AUDIT_API_TOKEN 的服务调用会采信。"),
    is_super_admin: bool = Query(False, description="是否全局超级管理员；仅带有效 AUDIT_API_TOKEN 的服务调用会采信。"),
):
    logger.info("[CaseProfile] case_id=%d 查询案件画像", case_id)
    where_clauses = ["c.case_id = %s"]
    params: list[Any] = [case_id]
    trusted_company_admin, trusted_super_admin = _trusted_admin_flags(
        request,
        is_company_admin=is_company_admin,
        is_super_admin=is_super_admin,
    )
    visibility_clauses, visibility_params = _case_visibility_clause(
        company_id=company_id,
        user_id=user_id,
        is_company_admin=trusted_company_admin,
        is_super_admin=trusted_super_admin,
        table_alias="c",
    )
    where_clauses.extend(visibility_clauses)
    params.extend(visibility_params)
    case = db.query_one(
        f"SELECT c.* FROM cases c WHERE {' AND '.join(where_clauses)}",
        tuple(params),
    )
    if not case:
        raise HTTPException(404, "案件不存在")

    debtors = db.query("SELECT * FROM debtors WHERE case_id=%s ORDER BY debtor_id", (case_id,))
    parties = db.query(
        """
        SELECT party_id, case_id, debtor_id, party_name, party_role, uscc,
               is_primary, status, source_type, extra_fields, created_by,
               created_at, updated_at
        FROM case_party
        WHERE case_id=%s
        ORDER BY status, party_role, is_primary DESC, party_id
        """,
        (case_id,),
    )
    claims = db.query("SELECT * FROM claims WHERE case_id=%s", (case_id,))
    guarantors = db.query("SELECT * FROM guarantors WHERE case_id=%s", (case_id,))
    risk = db.query_one("SELECT * FROM risk_profiles WHERE case_id=%s LIMIT 1", (case_id,))
    hidden = db.query("SELECT * FROM hidden_assets WHERE case_id=%s", (case_id,))
    snapshots = db.query("SELECT * FROM financial_snapshots WHERE case_id=%s ORDER BY report_period", (case_id,))
    legal_docs = db.query("SELECT * FROM legal_documents WHERE case_id=%s ORDER BY judgment_date", (case_id,))

    # 裁判文书网只读库 — 按债务人名称匹配（case_metadata JOIN case_entities）
    debtor_names = [d["entity_name"] for d in debtors if d.get("entity_name")]
    cpws_docs: list = []
    if debtor_names:
        try:
            cpws_docs = db.cpws_query(
                """
                SELECT DISTINCT ON (m.id)
                       m.id          AS cpws_case_id,
                       m.case_no,
                       m.title,
                       m.court,
                       m.doc_type,
                       m.doc_subtype,
                       m.case_type,
                       m.trial_procedure,
                       m.judge_date,
                       m.publish_date,
                       m.court_level,
                       m.cause,
                       m.province,
                       m.city,
                       m.result,
                       m.law_articles,
                       e.role  AS matched_role,
                       e.name  AS matched_name
                FROM case_metadata m
                JOIN case_entities e ON e.case_id = m.id
                WHERE e.name = ANY(%s)
                ORDER BY m.id, m.judge_date DESC NULLS LAST
                LIMIT 500
                """,
                (debtor_names,)
            )
            for doc in cpws_docs:
                doc["_source"] = "cpwsdata"
        except Exception as _cpws_err:
            logger.warning("cpwsdata 查询失败 case_id=%d: %s", case_id, _cpws_err)
    re_evals = db.query("SELECT * FROM real_estate_evaluations WHERE case_id=%s", (case_id,))
    me_evals = db.query("SELECT * FROM mining_evaluations WHERE case_id=%s", (case_id,))
    bank_accts = db.query("SELECT * FROM bank_accounts WHERE case_id=%s", (case_id,))
    contacts_list = db.query("SELECT * FROM contacts WHERE case_id=%s", (case_id,))
    sig_count = db.query_one("SELECT count(*) AS c FROM transaction_signatures WHERE case_id=%s", (case_id,))
    repay_count = db.query_one("SELECT count(*) AS c FROM repayment_behaviors WHERE case_id=%s", (case_id,))

    # 综合风险评分
    risk_scores = db.query_one("SELECT * FROM audit_risk_scores WHERE case_id=%s", (case_id,))

    def serialize(rows):
        result = []
        for row in (rows if isinstance(rows, list) else [rows] if rows else []):
            d = dict(row) if row else {}
            for k, v in d.items():
                if isinstance(v, (date, datetime)):
                    d[k] = str(v)
                elif hasattr(v, 'as_integer_ratio') and not isinstance(v, (int, float)):
                    d[k] = float(v)
            result.append(d)
        return result

    risk_scores_data = None
    if risk_scores:
        risk_scores_data = {
            "delta_score": float(risk_scores["delta_score"]) if risk_scores.get("delta_score") is not None else None,
            "valuation_score": float(risk_scores["valuation_score"]) if risk_scores.get("valuation_score") is not None else None,
            "deadline_score": float(risk_scores["deadline_score"]) if risk_scores.get("deadline_score") is not None else None,
            "behavioral_score": float(risk_scores["behavioral_score"]) if risk_scores.get("behavioral_score") is not None else None,
            "composite_score": float(risk_scores["composite_score"]) if risk_scores.get("composite_score") is not None else None,
            "weights": risk_scores.get("weights"),
            "cross_hits": risk_scores.get("cross_hits"),
            "calculated_at": str(risk_scores["calculated_at"]) if risk_scores.get("calculated_at") else None,
        }

    return {
        "case": serialize([case])[0] if case else None,
        "debtors": serialize(debtors),
        "parties": serialize(parties),
        "claims": serialize(claims),
        "guarantors": serialize(guarantors),
        "risk_profile": serialize([risk])[0] if risk else None,
        "hidden_assets": serialize(hidden),
        "financial_snapshots": serialize(snapshots),
        "legal_documents": serialize(legal_docs),
        "legal_documents_cpws": serialize(cpws_docs),
        "real_estate_evaluations": serialize(re_evals),
        "mining_evaluations": serialize(me_evals),
        "bank_accounts": serialize(bank_accts),
        "contacts": serialize(contacts_list),
        "risk_scores": risk_scores_data,
        "data_completeness": {
            "debtors": len(debtors) > 0,
            "parties": len(parties) > 0,
            "claims": len(claims) > 0,
            "financial_snapshots": len(snapshots) >= 2,
            "real_estate": len(re_evals) > 0,
            "mining": len(me_evals) > 0,
            "guarantors": len(guarantors) > 0,
            "risk_profile": risk is not None,
            "signatures": int(sig_count["c"]) > 0,
            "repayments": int(repay_count["c"]) > 0,
            "legal_documents": len(legal_docs) > 0,
            "legal_documents_cpws": len(cpws_docs) > 0,
            "bank_accounts": len(bank_accts) > 0,
            "contacts": len(contacts_list) > 0,
        }
    }


# ============================================================================
# 新增：裁判文书网语义搜索
# GET /api/case/{case_id}/legal-writ
# ============================================================================

@app.get("/api/case/{case_id}/legal-writ")
def get_legal_writ(
    case_id: int,
    q: Optional[str] = None,
    doc_type: Optional[str] = None,
    date_from: Optional[str] = None,
    limit: int = 20,
):
    """
    从 cpwsdata 裁判文书库（1032 万条）检索法律文书。

    无 q 参数：按债务人名称过滤 case_entities，返回 case_metadata（filter 模式）
    有 q 参数：embed(q) → case_search_chunks cosine 相似度检索，
               再过滤属于该债务人的文书（semantic 模式）

    可选过滤：doc_type（判决书/裁定书/通知书…）、date_from（YYYY-MM-DD）

    Schema（cpwsdata）：
      case_metadata.id  ↔  case_entities.case_id  ↔  case_search_chunks.case_id
      case_search_chunks.section_id  ↔  case_sections.id
      向量维度：1532（model=embo-01）
    """
    logger.info("[LegalWrit] case_id=%d q=%s doc_type=%s", case_id, q, doc_type)
    case = db.query_one("SELECT case_id FROM cases WHERE case_id=%s", (case_id,))
    if not case:
        raise HTTPException(404, "案件不存在")

    debtors = db.query("SELECT entity_name FROM debtors WHERE case_id=%s", (case_id,))
    debtor_names = [d["entity_name"] for d in debtors if d.get("entity_name")]
    if not debtor_names:
        return {"results": [], "total": 0, "mode": "no_debtor"}

    # 可选过滤（用 case_metadata 的真实列名）
    meta_filters: list[str] = []
    meta_params: list = []
    if doc_type:
        meta_filters.append("m.doc_type = %s")
        meta_params.append(doc_type)
    if date_from:
        meta_filters.append("m.judge_date >= %s")
        meta_params.append(date_from)
    filter_sql = ("AND " + " AND ".join(meta_filters)) if meta_filters else ""

    try:
        if q:
            # ── 语义搜索：embed → cosine 相似度 ──────────────────────────
            vec = llm_client.embed(q)
            vec_str = "[" + ",".join(str(x) for x in vec) + "]"
            # 先按债务人过滤候选 case_id，再做向量检索，避免全表扫描
            sql = f"""
                SELECT m.case_no,
                       m.title,
                       m.court,
                       m.doc_type,
                       m.doc_subtype,
                       m.case_type,
                       m.trial_procedure,
                       m.judge_date,
                       m.court_level,
                       m.cause,
                       m.province,
                       m.city,
                       m.result,
                       cs.section_type,
                       cs.section_title,
                       cs.content        AS matched_content,
                       1 - (ck.embedding <=> %s::vector) AS similarity
                FROM case_search_chunks ck
                JOIN case_sections cs ON cs.id = ck.section_id
                JOIN case_metadata  m  ON m.id  = ck.case_id
                WHERE ck.case_id IN (
                    SELECT case_id FROM case_entities WHERE name = ANY(%s)
                )
                  AND 1 - (ck.embedding <=> %s::vector) > 0.65
                  {filter_sql}
                ORDER BY similarity DESC
                LIMIT %s
            """
            rows = db.cpws_query(sql, [vec_str, debtor_names, vec_str] + meta_params + [limit])
            mode = "semantic"
        else:
            # ── 过滤模式：按名称匹配，DISTINCT ON 去重 ───────────────────
            sql = f"""
                SELECT DISTINCT ON (m.id)
                       m.id          AS cpws_case_id,
                       m.case_no,
                       m.title,
                       m.court,
                       m.doc_type,
                       m.doc_subtype,
                       m.case_type,
                       m.trial_procedure,
                       m.judge_date,
                       m.publish_date,
                       m.court_level,
                       m.cause,
                       m.province,
                       m.city,
                       m.result,
                       m.law_articles,
                       e.role  AS matched_role,
                       e.name  AS matched_name
                FROM case_metadata m
                JOIN case_entities e ON e.case_id = m.id
                WHERE e.name = ANY(%s)
                  {filter_sql}
                ORDER BY m.id, m.judge_date DESC NULLS LAST
                LIMIT %s
            """
            rows = db.cpws_query(sql, [debtor_names] + meta_params + [limit])
            mode = "filter"

    except Exception as e:
        logger.error("legal-writ cpwsdata 查询失败 case_id=%d: %s", case_id, e)
        raise HTTPException(502, f"裁判文书库查询失败: {e}")

    # 序列化（日期 → str，embedding 列不会出现在 SELECT 中，无需跳过）
    results = []
    for row in rows:
        d = {}
        for k, v in dict(row).items():
            if isinstance(v, (date, datetime)):
                d[k] = str(v)
            elif hasattr(v, "as_integer_ratio") and not isinstance(v, (int, float)):
                d[k] = float(v)
            else:
                d[k] = v
        results.append(d)

    return {
        "case_id": case_id,
        "debtor_names": debtor_names,
        "mode": mode,
        "total": len(results),
        "results": results,
    }


# ============================================================================
# EP 9 / 12：白手套分析
# GET /api/case/{case_id}/whiteglove
# ============================================================================

@app.get("/api/case/{case_id}/whiteglove")
def get_whiteglove(case_id: int):
    logger.info("[Whiteglove] case_id=%d 查询白手套分析", case_id)
    
    # 五同审计：限定本案关联企业（至少一方是本案债权人）
    five_same = db.query("""
        SELECT v.ent_a_name, v.ent_b_name, v.same_addr, v.same_phone, v.same_legal_rep, v.same_executive, v.same_industry,
               v.same_addr+v.same_phone+v.same_legal_rep+v.same_executive+v.same_industry AS score
        FROM v_five_same_audit v
        WHERE v.same_addr+v.same_phone+v.same_legal_rep+v.same_executive+v.same_industry >= 2
          AND (v.ent_a_name IN (SELECT entity_name FROM debtors WHERE case_id=%s)
               OR v.ent_b_name IN (SELECT entity_name FROM debtors WHERE case_id=%s))
        ORDER BY score DESC LIMIT 20
    """, (case_id, case_id))

    # 交叉任职：限定本案债权人企业中的人员
    case_debtors = db.query("SELECT entity_name FROM debtors WHERE case_id=%s", (case_id,))
    debtor_names = {row['entity_name'] for row in case_debtors}
    
    cross = db.query("""
        SELECT ea.person_name, ea.position AS pos_a, a.entity_name AS company_a,
               eb.position AS pos_b, b.entity_name AS company_b
        FROM executives ea
        JOIN executives eb ON ea.person_name = eb.person_name AND ea.enterprise_id < eb.enterprise_id
        JOIN enterprises a ON ea.enterprise_id = a.enterprise_id
        JOIN enterprises b ON eb.enterprise_id = b.enterprise_id
        WHERE ea.departure_date IS NULL AND eb.departure_date IS NULL
          AND (a.entity_name IN (SELECT entity_name FROM debtors WHERE case_id=%s)
               OR b.entity_name IN (SELECT entity_name FROM debtors WHERE case_id=%s))
    """, (case_id, case_id))

    # DNA关联人
    dna = db.query("SELECT * FROM related_persons WHERE case_id=%s", (case_id,))
    
    # 怀疑空壳公司：本案债权人和与他们有五同关系的企业中的空壳
    shells = db.query("""
        SELECT DISTINCT e.entity_name, e.legal_rep, e.registered_addr, e.established, e.reg_capital
        FROM enterprises e
        WHERE (e.entity_name IN (SELECT entity_name FROM debtors WHERE case_id=%s)
               OR e.entity_name IN (
                   SELECT ent_a_name FROM v_five_same_audit 
                   WHERE ent_b_name IN (SELECT entity_name FROM debtors WHERE case_id=%s)
                   UNION ALL
                   SELECT ent_b_name FROM v_five_same_audit
                   WHERE ent_a_name IN (SELECT entity_name FROM debtors WHERE case_id=%s)
               ))
          AND (e.reg_capital < 100 OR e.status IN ('注销','吊销'))
        ORDER BY e.established DESC LIMIT 10
    """, (case_id, case_id, case_id))

    return {
        "five_same_hits": [dict(r) for r in five_same],
        "cross_position_persons": [dict(r) for r in cross],
        "dna_related_persons": [dict(r) for r in dna],
        "suspect_shell_companies": [dict(r) for r in shells],
        "risk_summary": f"五同命中{len(five_same)}对，交叉任职{len(cross)}人，DNA关联人{len(dna)}个"
    }


# ============================================================================
# EP 10 / 12：资金拓扑
# GET /api/case/{case_id}/fund-flow
# ============================================================================

@app.get("/api/case/{case_id}/fund-flow")
def get_fund_flow(case_id: int):
    logger.info("[FundFlow] case_id=%d 查询资金流向", case_id)
    txns = db.query("""
        SELECT counterparty, txn_direction, SUM(txn_amount) AS total, routing_tag, is_related_party,
               COUNT(*) AS txn_count
        FROM transaction_signatures WHERE case_id=%s
        GROUP BY counterparty, txn_direction, routing_tag, is_related_party
        ORDER BY total DESC
    """, (case_id,))

    debtor = db.query_one("SELECT entity_name FROM debtors WHERE case_id=%s LIMIT 1", (case_id,))
    debtor_name = debtor["entity_name"] if debtor else "债务人"

    # 过滤掉 counterparty 为 NULL 或空串的行，以及 counterparty 等于债务人自身的行（避免节点ID冲突）
    txns = [t for t in txns if t["counterparty"] and t["counterparty"].strip()]

    total_in = sum(float(t["total"]) for t in txns if t["txn_direction"] == "in")
    total_out = sum(float(t["total"]) for t in txns if t["txn_direction"] == "out")

    # 生成安全的 Mermaid 节点 ID（只保留字母数字下划线）
    import re
    _id_cache = {}
    _id_counter = [0]
    def safe_id(name):
        if name in _id_cache:
            return _id_cache[name]
        _id_counter[0] += 1
        _id_cache[name] = f"N{_id_counter[0]}"
        return _id_cache[name]

    # 构建Mermaid — 金额已经是万元，不再除10000
    lines = ["graph LR"]
    dn = safe_id(debtor_name)

    lines.append(f'    subgraph SG1["第三方/债权方"]')
    seen = set()
    for t in txns:
        cp = t["counterparty"]
        if t["txn_direction"] == "in" and not t["is_related_party"] and cp not in seen:
            seen.add(cp)
            lines.append(f'        {safe_id(cp)}["{cp}"]')
    lines.append("    end")

    lines.append(f'    subgraph SG2["债务主体"]')
    lines.append(f'        {dn}["{debtor_name}"]')
    lines.append("    end")

    lines.append(f'    subgraph SG3["关联方/利益共同体"]')
    seen_rel = set()
    for t in txns:
        cp = t["counterparty"]
        if t["is_related_party"] and cp != debtor_name and cp not in seen_rel:
            seen_rel.add(cp)
            lines.append(f'        {safe_id(cp)}["{cp}"]')
    lines.append("    end")

    lines.append(f'    subgraph SG4["异常流入/伪装还款"]')
    for t in txns:
        cp = t["counterparty"]
        if t["txn_direction"] == "in" and t["is_related_party"] and cp != debtor_name:
            rid = safe_id(f"回流_{cp}")
            lines.append(f'        {rid}["{cp} 回流"]')
    lines.append("    end")

    # 不再重复出现 counterparty == debtor_name 的出入关系
    lines.append(f'    subgraph SG5["出方向"]')
    seen_out = set()
    for t in txns:
        cp = t["counterparty"]
        if t["txn_direction"] == "out" and not t["is_related_party"] and cp not in seen_out:
            seen_out.add(cp)
            lines.append(f'        {safe_id(cp)}["{cp}"]')
    lines.append("    end")

    for t in txns:
        cp = t["counterparty"]
        cn = safe_id(cp)
        amt = float(t["total"])
        tag = t["routing_tag"] or ""
        if t["txn_direction"] == "in" and not t["is_related_party"]:
            lines.append(f'    {cn} -->|"{amt:.1f}万"| {dn}')
        elif t["txn_direction"] == "out" and t["is_related_party"] and cp != debtor_name:
            label = f"{amt:.1f}万 {tag}".strip()
            lines.append(f'    {dn} -->|"{label}"| {cn}')
        elif t["txn_direction"] == "out" and not t["is_related_party"]:
            lines.append(f'    {dn} -->|"{amt:.1f}万"| {cn}')
        elif t["txn_direction"] == "in" and t["is_related_party"] and cp != debtor_name:
            rid = safe_id(f"回流_{cp}")
            lines.append(f'    {rid} -.->|"{amt:.1f}万 伪装"| {dn}')

    suspicious = [dict(t) for t in txns if t["routing_tag"] and "疑似" in t["routing_tag"]]
    for s in suspicious:
        for k, v in s.items():
            if hasattr(v, 'as_integer_ratio') and not isinstance(v, (int, float)):
                s[k] = float(v)

    return {
        "mermaid_code": "\n".join(lines),
        "total_inflow": round(total_in, 2),
        "total_outflow": round(total_out, 2),
        "suspicious_flows": suspicious,
    }


# ============================================================================
# EP 聚合：战前情报收割 — 并发调用全部引擎，脱水后一次性返回
# POST /api/audit/get_full_context
#
# 设计目标：
#   1. 替代 Dify 端 14 个工具的 Agent 节点
#   2. 后端并发执行，3-5 秒内返回完整案件数字全景
#   3. LLM 只做阅读推理，不再调工具
# ============================================================================

def _safe_json_value(v):
    """将 Decimal/date 等不可 JSON 序列化的值转为可序列化"""
    if isinstance(v, (date, datetime)):
        return str(v)
    if hasattr(v, 'as_integer_ratio') and not isinstance(v, (int, float)):
        return float(v)
    return v


def _safe_json_rows(rows):
    """序列化 list[RealDictRow] → list[dict]"""
    if not isinstance(rows, list):
        return rows
    result = []
    for r in rows:
        if hasattr(r, 'keys'):
            result.append({k: _safe_json_value(v) for k, v in dict(r).items()})
        else:
            result.append(_safe_json_value(r))
    return result


def _dehydrate(result: dict, limits: dict) -> dict:
    """通用脱水：对指定 key 的列表截断到上限，保留总数提示"""
    if not isinstance(result, dict):
        return result
    d = dict(result)
    for key, max_len in limits.items():
        arr = d.get(key)
        if isinstance(arr, list) and len(arr) > max_len:
            original_len = len(arr)
            # 策略：高优先级数据保留头部，低优先级保留头部即可
            d[key] = arr[:max_len]
            d[f"_{key}_total"] = original_len
            d[f"_{key}_note"] = f"共{original_len}条，已脱水显示前{max_len}条"
    return d


def _dehydrate_real_estate(rows: list) -> dict:
    """
    不动产高密度脱水：
    1. 算总账（总项数、账面总值、去毒净值）
    2. 提纯 T1：按 net_value 降序，保留价值占比前 80% 的核心资产（最多 10 项）
    3. 打包碎片：剩余资产按 property_usage 合并为资产包
    4. 提取毒点：命中以下任一条件则生成 drill_down_flags
       - has_title_objection = true
       - lease_start/lease_end 跨度 > 5年（长租约陷阱）
       - lien_priority > 1（非首席抵押）
    """
    if not rows:
        return {
            "_meta": {"total_count": 0, "total_gross_value": 0, "total_net_value": 0,
                      "note": "无不动产数据"},
            "core_assets_topN": [], "bundled_assets": [], "drill_down_flags": []
        }

    # 统一转为可序列化的 dict
    assets = []
    for r in rows:
        if hasattr(r, 'keys'):
            assets.append({k: _safe_json_value(v) for k, v in dict(r).items()})
        else:
            assets.append(r)

    # ── 1. 算总账 ──
    total_count = len(assets)
    total_gross = sum(float(a.get("gross_value") or 0) for a in assets)
    total_net = sum(float(a.get("net_value") or 0) for a in assets)

    # ── 2. 提纯 T1（按净值降序，保留价值占比前 80%，最多 10 项） ──
    sorted_by_value = sorted(assets, key=lambda x: float(x.get("net_value") or 0), reverse=True)
    core_assets = []
    core_net_sum = 0.0
    for a in sorted_by_value:
        if len(core_assets) >= 10:
            break
        core_assets.append(a)
        core_net_sum += float(a.get("net_value") or 0)
        if core_net_sum >= total_net * 0.8 and len(core_assets) >= 1:
            break

    # ── 3. 打包碎片（剩余资产按 property_usage 合并） ──
    core_ids = {a.get("id") for a in core_assets}
    remaining = [a for a in assets if a.get("id") not in core_ids]
    bundles = {}
    for a in remaining:
        usage = a.get("property_usage") or "其他"
        if usage not in bundles:
            bundles[usage] = {"count": 0, "total_net_value": 0.0}
        bundles[usage]["count"] += 1
        bundles[usage]["total_net_value"] += float(a.get("net_value") or 0)
    bundled_assets = [
        {"bundle_type": k, "count": v["count"], "total_net_value": round(v["total_net_value"], 2)}
        for k, v in bundles.items()
    ]

    # ── 4. 提取毒点（遍历全部资产，致命标签强制保留指纹） ──
    drill_down_flags = []
    for a in assets:
        asset_id = a.get("id")
        # 4a. 案外人执行异议
        if a.get("has_title_objection") or (a.get("objection_status") and "异议" in str(a.get("objection_status", ""))):
            drill_down_flags.append({
                "asset_id": asset_id,
                "risk_type": "物理抗辩",
                "desc": f"存在案外人执行异议: {a.get('objection_status') or '权属异议已标记'}"
            })
        # 4b. 长租约陷阱（>5年）
        try:
            lease_start = a.get("lease_start")
            lease_end = a.get("lease_end")
            if lease_start and lease_end:
                if isinstance(lease_start, str):
                    lease_start = datetime.strptime(lease_start, "%Y-%m-%d").date()
                if isinstance(lease_end, str):
                    lease_end = datetime.strptime(lease_end, "%Y-%m-%d").date()
                if hasattr(lease_end, 'year') and hasattr(lease_start, 'year'):
                    years = (lease_end.year - lease_start.year) - ((lease_end.month, lease_end.day) < (lease_start.month, lease_start.day))
                    if years > 5:
                        drill_down_flags.append({
                            "asset_id": asset_id,
                            "risk_type": "买卖不破租赁陷阱",
                            "desc": f"存在长租约: {lease_start} 至 {lease_end}（约{years}年）"
                        })
        except Exception:
            pass
        # 4c. 抵押顺位 > 1
        lien = a.get("lien_priority")
        if lien is not None:
            try:
                if int(lien) > 1:
                    drill_down_flags.append({
                        "asset_id": asset_id,
                        "risk_type": "非首席抵押",
                        "desc": f"抵押顺位为第{int(lien)}顺位，非首席抵押权人"
                    })
            except (ValueError, TypeError):
                pass

    return {
        "_meta": {
            "total_count": total_count,
            "total_gross_value": round(total_gross, 2),
            "total_net_value": round(total_net, 2),
            "core_assets_count": len(core_assets),
            "core_assets_value_coverage_pct": round(core_net_sum / total_net * 100, 1) if total_net > 0 else 0,
            "bundled_assets_count": len(bundled_assets),
            "drill_down_flags_count": len(drill_down_flags),
            "note": "碎片资产已按用途打包，高危瑕疵已提取指纹"
        },
        "core_assets_topN": core_assets,
        "bundled_assets": bundled_assets,
        "drill_down_flags": drill_down_flags
    }


def _dehydrate_mining(rows: list, transfer_prices: dict = None) -> dict:
    """
    矿权高密度脱水：
    1. 核心三围：矿名、核定产能(annual_capacity)、探明储量(proved_reserves)
    2. 时效斩首：计算 permit_expiry 距今剩余天数
    3. 价值倒挂探测：若 estimated_value 与 transfer_base_price 差距超过 30%，生成指纹
    4. 生态一票否决：in_ecological_redline = true 时强制提权
    """
    if not rows:
        return {
            "_meta": {"total_count": 0, "note": "无矿权数据"},
            "mines": [], "drill_down_flags": []
        }

    transfer_prices = transfer_prices or {}
    mines = []
    for r in rows:
        if hasattr(r, 'keys'):
            mines.append({k: _safe_json_value(v) for k, v in dict(r).items()})
        else:
            mines.append(r)

    total_count = len(mines)
    today = date.today()
    drill_down_flags = []

    for m in mines:
        asset_id = m.get("id")
        mine_name = m.get("mine_name") or "未命名矿权"
        estimated_value = float(m.get("estimated_value") or 0)

        # 2. 时效斩首：证照剩余有效期
        permit_expiry = m.get("permit_expiry")
        if permit_expiry:
            try:
                if isinstance(permit_expiry, str):
                    permit_expiry = datetime.strptime(permit_expiry, "%Y-%m-%d").date()
                if hasattr(permit_expiry, 'year'):
                    days_remaining = (permit_expiry - today).days
                    if days_remaining < 0:
                        drill_down_flags.append({
                            "asset_id": asset_id,
                            "risk_type": "证照死穴",
                            "desc": f"采矿许可证已于{permit_expiry}到期，当前处于行政审批盲区"
                        })
                    elif days_remaining < 365:
                        drill_down_flags.append({
                            "asset_id": asset_id,
                            "risk_type": "证照预警",
                            "desc": f"采矿许可证将于{permit_expiry}到期，仅剩{days_remaining}天"
                        })
            except Exception:
                pass

        # 3. 价值倒挂探测（>30% 差距）
        transfer_price = transfer_prices.get(mine_name) or transfer_prices.get(str(asset_id))
        if estimated_value > 0 and transfer_price and float(transfer_price) > 0:
            tp = float(transfer_price)
            discount_ratio = tp / estimated_value
            if discount_ratio < 0.7:  # 折价超过30%
                drill_down_flags.append({
                    "asset_id": asset_id,
                    "risk_type": "价值倒挂博弈",
                    "desc": f"账面评估{estimated_value/10000:.0f}万，协议转让底价仅{tp/10000:.0f}万，折价率{discount_ratio*100:.1f}%"
                })

        # 4. 生态一票否决
        if m.get("in_ecological_redline"):
            drill_down_flags.append({
                "asset_id": asset_id,
                "risk_type": "生态红线一票否决",
                "desc": "矿区位于生态红线或自然保护区内，存在政策性关闭风险"
            })

    return {
        "_meta": {
            "total_count": total_count,
            "drill_down_flags_count": len(drill_down_flags),
            "note": "已提取核心产能与合规红线指标"
        },
        "mines": [
            {
                "asset_id": m.get("id"),
                "mine_name": m.get("mine_name"),
                "capacity_10k_tons": float(m["annual_capacity"]) if m.get("annual_capacity") else None,
                "reserves_10k_tons": float(m["proved_reserves"]) if m.get("proved_reserves") else None,
                "status": m.get("mining_status")
            }
            for m in mines
        ],
        "drill_down_flags": drill_down_flags
    }


def _run_engine_safe(func, label: str, *args, **kwargs):
    """包装引擎调用，捕获异常不中断整体流程"""
    t0 = time.time()
    try:
        result = func(*args, **kwargs)
        logger.info("[FullContext] %s 完成 | 耗时%dms", label, int((time.time()-t0)*1000))
        return result
    except Exception as e:
        logger.error("[FullContext] %s 失败: %s", label, str(e)[:300])
        return {"_error": str(e)[:500], "_failed": True}


# ── get_full_context 结果缓存（compute/fetch 分离）──────────────────────────
# 默认读缓存命中即秒回，跳过 4 引擎重算+写库；recompute=true 或缓存缺失/过期则重算并回填；
# ingest 端点写库后失效缓存（见各 ingest 端点的 finally）。所有缓存操作 fail-safe：
# 缓存表不存在或任何异常都静默降级为"实时重算"，绝不影响主流程。
FULL_CONTEXT_CACHE_TTL_SECONDS = int(os.getenv("FULL_CONTEXT_CACHE_TTL_SECONDS", "86400"))


def _get_full_context_cache(case_id: int):
    """命中且未过 TTL 返回 payload dict，否则 None。任何异常→None（调用方重算）。"""
    try:
        row = db.query_one(
            "SELECT payload::text AS p, EXTRACT(EPOCH FROM (now()-computed_at)) AS age "
            "FROM engine_results_cache WHERE case_id=%s", (case_id,))
        if not row or row.get("age") is None:
            return None
        if float(row["age"]) > FULL_CONTEXT_CACHE_TTL_SECONDS:
            return None
        return json.loads(row["p"])
    except Exception as e:
        logger.warning("[FullContext] 读缓存跳过（降级为重算）: %s", str(e)[:200])
        return None


def _store_full_context_cache(case_id: int, payload: dict):
    """写缓存；best-effort，失败不影响主流程。"""
    try:
        db.execute(
            "INSERT INTO engine_results_cache (case_id, payload, computed_at) "
            "VALUES (%s, %s::jsonb, now()) "
            "ON CONFLICT (case_id) DO UPDATE SET payload=EXCLUDED.payload, computed_at=now()",
            (case_id, json.dumps(payload, ensure_ascii=False, default=str)))
    except Exception as e:
        logger.warning("[FullContext] 写缓存跳过: %s", str(e)[:200])


def _invalidate_full_context_cache(case_id: int):
    """失效某案件缓存（数据变更后调用）；best-effort。"""
    try:
        db.execute("DELETE FROM engine_results_cache WHERE case_id=%s", (case_id,))
        logger.info("[FullContext] case_id=%s 缓存已失效", case_id)
    except Exception as e:
        logger.warning("[FullContext] 失效缓存跳过: %s", str(e)[:200])


@app.post("/api/audit/get_full_context")
def get_full_context(req: AuditReq):
    """compute/fetch 分离：默认读缓存命中即秒回；recompute=true 或缓存缺失/过期则重算并回填缓存。"""
    case_id = req.case_id
    if not getattr(req, "recompute", False):
        cached = _get_full_context_cache(case_id)
        if cached is not None:
            if isinstance(cached.get("_meta"), dict):
                cached["_meta"]["cache_hit"] = True
            logger.info("[FullContext] case_id=%d 命中缓存，跳过引擎重算直接返回", case_id)
            return cached
    payload = _compute_full_context(req)
    if isinstance(payload.get("_meta"), dict):
        payload["_meta"]["cache_hit"] = False
    _store_full_context_cache(case_id, payload)
    return payload


def _compute_full_context(req: AuditReq):
    """
    并发执行四大引擎 + 白手套 + 资金拓扑 + 案件全景，
    脱水后组装成一个巨大的 JSON 返回给 Dify LLM 节点。
    """
    case_id = req.case_id
    t0 = time.time()
    logger.info("[FullContext] case_id=%d 开始聚合全量上下文", case_id)

    # ── 并发执行 6 个数据查询/引擎（线程池） ──
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        f_delta   = executor.submit(_run_engine_safe, audit_delta_check,   "引擎1-轧差",       AuditReq(case_id=case_id))
        f_val     = executor.submit(_run_engine_safe, audit_valuation_squeeze, "引擎2-挤水",   AuditReq(case_id=case_id))
        f_dead    = executor.submit(_run_engine_safe, audit_deadline_scan, "引擎3-时效",       AuditReq(case_id=case_id))
        f_behav   = executor.submit(_run_engine_safe, audit_behavioral_scan, "引擎4-行为",     AuditReq(case_id=case_id))
        f_white   = executor.submit(_run_engine_safe, get_whiteglove,      "白手套",           case_id)
        f_fund    = executor.submit(_run_engine_safe, get_fund_flow,       "资金拓扑",         case_id)

        delta_result      = f_delta.result()
        valuation_result  = f_val.result()
        deadline_result   = f_dead.result()
        behavioral_result = f_behav.result()
        whiteglove_result = f_white.result()
        fundflow_result   = f_fund.result()

    # ── 案件基础数据（主线程查询，数据量可控） ──
    case = db.query_one("SELECT case_id, case_name, case_type, status, created_at FROM cases WHERE case_id=%s", (case_id,))
    debtors = db.query("SELECT debtor_id, entity_name, uscc, operating_status, actual_controller, legal_representative, registered_capital FROM debtors WHERE case_id=%s", (case_id,))
    claims = db.query("SELECT claim_id, principal, interest, penalty, total_claim, guarantee_type, litigation_status, collateral_desc, lien_priority FROM claims WHERE case_id=%s", (case_id,))
    guarantors = db.query("SELECT guarantor_id, entity_name, guarantor_type, guarantee_type, spouse_name FROM guarantors WHERE case_id=%s", (case_id,))
    snapshots = db.query("SELECT report_period, total_assets, total_liabilities, revenue, net_profit, epsilon_verdict FROM financial_snapshots WHERE case_id=%s ORDER BY report_period", (case_id,))
    re_evals = db.query("""
        SELECT id, property_address, project_name, property_usage, gross_value, net_value,
               discount_factors, overall_rating, seal_status, mortgage_status, lease_status,
               has_title_objection, objection_status, lien_priority,
               lease_start, lease_end, physical_occupation, co_owner_info
        FROM real_estate_evaluations WHERE case_id=%s
    """, (case_id,))
    me_evals = db.query("""
        SELECT id, mine_name, estimated_value, permit_expiry, mining_status, overall_rating,
               production_scale, proved_reserves, annual_capacity,
               in_ecological_redline, env_approval_status, safety_permit_status,
               calorific_value, coal_type, mine_scale, transfer_base_price
        FROM mining_evaluations WHERE case_id=%s
    """, (case_id,))

    # ── 脱水处理 ──
    delta_dehyd = _dehydrate(delta_result, {
        "period_trend": 30,
        "epsilon_trend": 30,
    })
    deadline_dehyd = _dehydrate(deadline_result, {
        "green_alerts": 10,
    })
    behavioral_dehyd = _dehydrate(behavioral_result, {
        "performative_payments": 50,
        "signature_chain": 30,
    })
    whiteglove_dehyd = _dehydrate(whiteglove_result, {
        "five_same_hits": 20,
        "cross_position_persons": 20,
        "dna_related_persons": 20,
        "suspect_shell_companies": 20,
    })
    fundflow_dehyd = _dehydrate(fundflow_result, {
        "suspicious_flows": 20,
    })

    # ── 不动产 & 矿权 高密度脱水（战术沙盘） ──
    re_dehydrated = _dehydrate_real_estate(re_evals)
    # 自动从数据库提取 transfer_base_price，与外部传入参数合并（外部参数优先覆盖）
    db_transfer_prices = {}
    for r in me_evals:
        if hasattr(r, 'keys'):
            r = dict(r)
        mine_name = r.get("mine_name")
        tbp = r.get("transfer_base_price")
        if mine_name and tbp is not None:
            db_transfer_prices[mine_name] = float(tbp)
    merged_transfer_prices = {**db_transfer_prices, **(req.mining_transfer_prices or {})}
    me_dehydrated = _dehydrate_mining(me_evals, merged_transfer_prices if merged_transfer_prices else None)

    # 对旧字段做向后兼容的轻度脱水
    re_fallback = _dehydrate({"real_estate_evaluations": _safe_json_rows(re_evals)}, {"real_estate_evaluations": 3})
    me_fallback = _dehydrate({"mining_evaluations": _safe_json_rows(me_evals)}, {"mining_evaluations": 3})

    # 引擎2 嵌套数组脱水
    valuation_dehyd = dict(valuation_result) if isinstance(valuation_result, dict) else {"_error": "valuation_result 非字典"}
    if isinstance(valuation_dehyd, dict) and not valuation_dehyd.get("_failed"):
        re_val_count = len(valuation_dehyd.get("real_estate_valuations", []))
        me_val_count = len(valuation_dehyd.get("mining_valuations", []))
        if re_val_count > 10:
            valuation_dehyd["real_estate_valuations"] = valuation_dehyd["real_estate_valuations"][:10]
            valuation_dehyd["_real_estate_valuations_total"] = re_val_count
            valuation_dehyd["_real_estate_valuations_note"] = f"共{re_val_count}项不动产估值，已脱水显示前10项"
        if me_val_count > 5:
            valuation_dehyd["mining_valuations"] = valuation_dehyd["mining_valuations"][:5]
            valuation_dehyd["_mining_valuations_total"] = me_val_count
            valuation_dehyd["_mining_valuations_note"] = f"共{me_val_count}项矿权估值，已脱水显示前5项"

    duration_ms = int((time.time() - t0) * 1000)
    logger.info("[FullContext] case_id=%d 聚合完成 | 耗时%dms | 不动产%d项(毒点%d) | 矿权%d项(毒点%d)",
                case_id, duration_ms,
                re_dehydrated["_meta"]["total_count"], re_dehydrated["_meta"]["drill_down_flags_count"],
                me_dehydrated["_meta"].get("total_count", 0), me_dehydrated["_meta"].get("drill_down_flags_count", 0))

    return {
        "case_id": case_id,
        "case": _safe_json_value(dict(case)) if case else None,
        "debtors": _safe_json_rows(debtors),
        "claims": _safe_json_rows(claims),
        "guarantors": _safe_json_rows(guarantors),
        "financial_snapshots": _safe_json_rows(snapshots),
        # 【权威】高密度脱水后的战术沙盘（全量总账 + 核心 topN + 碎片打包 + 毒点指纹）
        "real_estate_dehydrated": re_dehydrated,
        "mining_dehydrated": me_dehydrated,
        # 【DEPRECATED】旧字段轻度脱水，仅截断前 3 项、会丢资产，保留仅为向后兼容（Dify 旧节点）。
        # 新接入方请改用 real_estate_dehydrated / mining_dehydrated +
        # engine_results.valuation_squeeze.{real_estate_valuations,mining_valuations}（去毒明细）。
        "real_estate_evaluations": re_fallback.get("real_estate_evaluations", []),
        "_real_estate_evaluations_total": re_fallback.get("_real_estate_evaluations_total"),
        "mining_evaluations": me_fallback.get("mining_evaluations", []),
        "_mining_evaluations_total": me_fallback.get("_mining_evaluations_total"),
        "engine_results": {
            "delta_check": delta_dehyd,
            "valuation_squeeze": valuation_dehyd,
            "deadline_scan": deadline_dehyd,
            "behavioral_scan": behavioral_dehyd,
        },
        "whiteglove": whiteglove_dehyd,
        "fund_flow": fundflow_dehyd,
        "_meta": {
            "duration_ms": duration_ms,
            "dehydrated": True,
            "note": "不动产/矿权已升级为高密度脱水（战术沙盘），低优先级长列表已截断",
            # 字段契约：明确哪些字段权威、哪些已废弃，供下游（ai_hunter / Dify）对齐
            "field_contract": {
                "authoritative": {
                    "assets_real_estate": "real_estate_dehydrated（全量总账+核心topN+碎片打包+毒点）",
                    "assets_mining": "mining_dehydrated（同上）",
                    "valuation_detail": "engine_results.valuation_squeeze.{real_estate_valuations,mining_valuations}（去毒明细：net_value/discount_factors/verdict）",
                    "deadline_board": "engine_results.deadline_scan（四级时效看板）",
                    "behavioral": "engine_results.behavioral_scan（白手套/资金异常）",
                    "claims": "claims（原始本息明细：principal/interest/penalty/delayed_interest/total_claim）",
                },
                "deprecated": {
                    "real_estate_evaluations": "仅前3项、会丢资产，勿用于完整资产清单；改用 real_estate_dehydrated",
                    "mining_evaluations": "同上；改用 mining_dehydrated",
                },
                "notes": [
                    "回收率口径：上游 valuation_squeeze.recovery_rate 分母为 SUM(total_claim)（含罚息/复利）；下游若需『终审本息』口径请用 claims 自行重算。",
                ],
            },
        },
    }


# ============================================================================
# EP 11 / 12：批量创建任务
# POST /api/tasks/create-batch
# ============================================================================

@app.post("/api/tasks/create-batch")
def create_task_batch(req: TaskBatchReq):
    """
    批量创建督办任务。
    幂等性：同一 case_id + 同一 action 的任务，已存在（非已取消）则跳过。
    容错性：单条失败只记录日志，不抛错，不截断后续任务。
    """
    logger.info("[TaskBatch] case_id=%d 开始创建任务 | 任务数=%d", req.case_id, len(req.tasks))

    # 1. 空任务保护
    if not req.tasks:
        logger.warning("[TaskBatch] case_id=%d 任务列表为空，直接返回", req.case_id)
        return {
            "case_id": req.case_id,
            "tasks_created": 0,
            "tasks_skipped": 0,
            "tasks_failed": 0,
            "tasks": [],
            "skipped": [],
            "failed": [],
            "note": "任务列表为空，未创建任何任务"
        }

    created = []
    skipped = []
    failed = []

    for t in req.tasks:
        try:
            action = t.get("action")
            if not action:
                logger.warning("[TaskBatch] case_id=%d 跳过空action任务 | task=%s",
                               req.case_id, str(t)[:200])
                skipped.append({"reason": "action为空", "task": t})
                continue

            # 2. 幂等检查：同一 case + 同一 action，已有非已取消状态的任务则跳过
            existing = db.query_one("""
                SELECT task_id, status FROM tasks
                WHERE case_id = %s AND action = %s AND status != '已取消'
                LIMIT 1
            """, (req.case_id, action))

            if existing:
                logger.info("[TaskBatch] case_id=%d action='%s' 已存在(task_id=%s, status=%s)，跳过",
                            req.case_id, action, existing["task_id"], existing["status"])
                skipped.append({
                    "reason": "任务已存在",
                    "task_id": existing["task_id"],
                    "action": action,
                    "status": existing["status"]
                })
                continue

            # 3. 插入新任务
            row = db.execute_returning("""
                INSERT INTO tasks (case_id, task_no, action, detail, assigned_role, deadline,
                    deliverable, priority, source_engine)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING task_id
            """, (
                req.case_id, t.get("task_no"), action, t.get("detail"),
                t.get("assigned_role") or t.get("role"),
                t.get("deadline"),
                t.get("deliverable") or t.get("delivery"),
                t.get("priority", "中"),
                t.get("source_engine") or t.get("engine"),
            ))
            created.append({"task_id": row["task_id"], "task_no": t.get("task_no"), "action": action})

        except Exception as e:
            # 4. 失败只记录日志，不抛错，continue 处理下一条
            logger.error("[TaskBatch] case_id=%d 任务创建失败 | action=%s | 错误=%s",
                         req.case_id, t.get("action"), str(e)[:500])
            failed.append({"action": t.get("action"), "error": str(e)[:500]})
            continue

    logger.info("[TaskBatch] case_id=%d 完成 | 创建%d/跳过%d/失败%d",
                req.case_id, len(created), len(skipped), len(failed))

    return {
        "case_id": req.case_id,
        "tasks_created": len(created),
        "tasks_skipped": len(skipped),
        "tasks_failed": len(failed),
        "tasks": created,
        "skipped": skipped,
        "failed": failed,
    }


# ============================================================================
# EP 12 / 12：任务管理
# POST /api/tasks/manage
# ============================================================================

@app.post("/api/tasks/manage")
def manage_tasks(req: ManageTaskReq):
    logger.info("[ManageTasks] case_id=%d action=%s task_id=%s", req.case_id, req.action, req.task_id)
    if req.action == "list":
        sql = "SELECT * FROM tasks WHERE case_id=%s"
        params = [req.case_id]
        if req.filter_status:
            sql += " AND status=%s"
            params.append(req.filter_status)
        sql += " ORDER BY CASE priority WHEN '紧急' THEN 1 WHEN '高' THEN 2 WHEN '中' THEN 3 WHEN '低' THEN 4 END, deadline"
        tasks = db.query(sql, params)
        result = []
        for t in tasks:
            d = dict(t)
            for k, v in d.items():
                if isinstance(v, (date, datetime)):
                    d[k] = str(v)
            result.append(d)
        logger.info("[ManageTasks] case_id=%d list 返回%d条任务", req.case_id, len(result))
        return {"case_id": req.case_id, "total": len(result), "tasks": result}

    elif req.action == "update":
        if not req.task_id or not req.new_status:
            raise HTTPException(400, "update需要task_id和new_status")
        extra = ""
        params = [req.new_status]
        if req.new_status == "进行中":
            extra = ", started_at=now()"
        elif req.new_status == "已完成":
            extra = ", completed_at=now(), completion_note=%s"
            params.append(req.completion_note or "")
        params.extend([req.case_id, req.task_id])
        db.execute(f"UPDATE tasks SET status=%s, updated_at=now(){extra} WHERE case_id=%s AND task_id=%s", params)
        logger.info("[ManageTasks] case_id=%d task_id=%s 状态更新为 %s", req.case_id, req.task_id, req.new_status)
        return {"task_id": req.task_id, "new_status": req.new_status, "message": "任务状态已更新"}

    elif req.action == "assign":
        if not req.task_id or not req.assigned_to:
            raise HTTPException(400, "assign需要task_id和assigned_to")
        db.execute("UPDATE tasks SET assigned_to=%s, updated_at=now() WHERE case_id=%s AND task_id=%s",
                   (req.assigned_to, req.case_id, req.task_id))
        logger.info("[ManageTasks] case_id=%d task_id=%s 指派给 %s", req.case_id, req.task_id, req.assigned_to)
        return {"task_id": req.task_id, "assigned_to": req.assigned_to, "message": "任务已指派"}

    elif req.action == "summary":
        row = db.query_one("""
            SELECT count(*) AS total,
                count(*) FILTER (WHERE status='待执行') AS pending,
                count(*) FILTER (WHERE status='进行中') AS in_progress,
                count(*) FILTER (WHERE status='已完成') AS completed,
                count(*) FILTER (WHERE status='逾期') AS overdue,
                count(*) FILTER (WHERE priority='紧急') AS urgent,
                min(deadline) FILTER (WHERE status IN ('待执行','进行中')) AS nearest_deadline
            FROM tasks WHERE case_id=%s
        """, (req.case_id,))
        d = dict(row)
        if d.get("nearest_deadline"):
            d["nearest_deadline"] = str(d["nearest_deadline"])
        logger.info("[ManageTasks] case_id=%d summary: 总%s/待执行%s/已完成%s",
                    req.case_id, d.get("total"), d.get("pending"), d.get("completed"))
        return d

    raise HTTPException(400, f"不支持的action: {req.action}")


# ============================================================================
# EP 13：API 调用日志查询
# GET /api/logs
# ============================================================================

@app.get("/api/logs")
def get_api_logs(
    case_id: int,  # 必填参数，防止全库查询
    path: Optional[str] = None,
    endpoint_name: Optional[str] = None,
    limit: int = 50,
):
    sql = "SELECT id, request_id, method, path, query_params, request_body, response_status, response_body, duration_ms, client_ip, case_id, endpoint_name, error_message, created_at FROM api_call_logs WHERE case_id = %s"
    params = [case_id]
    if path:
        sql += " AND path = %s"
        params.append(path)
    if endpoint_name:
        sql += " AND endpoint_name = %s"
        params.append(endpoint_name)
    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(min(limit, 500))

    rows = db.query(sql, params)
    results = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, (date, datetime)):
                d[k] = str(v)
        results.append(d)
    return {"total": len(results), "logs": results}


# ============================================================================
# 健康检查
# ============================================================================

@app.get("/health")
@app.get("/api/v1/check")
def health():
    try:
        db.query_one("SELECT 1")
        return {"status": "ok", "db": "connected", "llm_provider": LLM_PROVIDER}
    except Exception as e:
        return {"status": "error", "db": str(e)}

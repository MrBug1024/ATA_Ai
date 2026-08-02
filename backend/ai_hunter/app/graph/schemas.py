"""Typed schemas for structured graph outputs, knowledge graph payloads, and API contracts."""

from datetime import date
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .capabilities import BUSINESS_LINE_IDS, CAPABILITY_IDS, get_capability_spec


ISO_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


class TaskItemModel(BaseModel):
    action: str = Field(description="具体执行的动作")
    role: str = Field(description="执行角色，如法务、调查、审计")
    deadline: str = Field(description="推荐时限，YYYY-MM-DD 格式")
    deliverable: str = Field(description="验收交付物")
    priority: Literal["高", "中", "低"] = Field(description="紧急程度")

    @field_validator("deadline", mode="before")
    @classmethod
    def normalize_deadline(cls, value) -> str:
        raw = str(value or "").strip()
        match = ISO_DATE_PATTERN.search(raw)
        if match is None:
            raise ValueError("deadline 必须包含 YYYY-MM-DD 日期")
        candidate = match.group(0)
        try:
            date.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError("deadline 必须是有效的 YYYY-MM-DD 日期") from exc
        return candidate


class TaskExtractionModel(BaseModel):
    tasks: list[TaskItemModel] = Field(default_factory=list)


class RouteDecisionModel(BaseModel):
    route_version: str = Field(default="v2", description="路由契约版本")
    business_line: str = Field(
        description="一级业务线",
        json_schema_extra={"enum": list(BUSINESS_LINE_IDS)},
    )
    capability: str = Field(
        description="二级业务能力",
        json_schema_extra={"enum": list(CAPABILITY_IDS)},
    )
    intent: Literal["full_audit", "drilldown", "re_audit", "review"] = Field(
        default="drilldown",
        description="兼容现有主图的执行意图，由 capability 确定性派生",
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="分类置信度")
    needs_clarification: bool = Field(default=False, description="是否必须先向用户澄清")
    source: Literal["rule", "model", "context", "fallback"] = Field(default="model", description="判定来源")
    case_id: int | None = Field(default=None, description="从请求或上下文解析出的案件 ID")
    action: str = Field(default="", description="查询、创建、完成、指派等具体动作")
    target_id: str = Field(default="", description="任务、批次等操作目标 ID")
    clarification_question: str = Field(default="", description="需要澄清时向用户提出的单个问题")

    @field_validator("business_line")
    @classmethod
    def validate_business_line(cls, value: str) -> str:
        if value not in BUSINESS_LINE_IDS:
            raise ValueError(f"未知业务线: {value}")
        return value

    @field_validator("capability")
    @classmethod
    def validate_capability(cls, value: str) -> str:
        if get_capability_spec(value) is None:
            raise ValueError(f"未知 capability: {value}")
        return value

    @model_validator(mode="after")
    def derive_compatible_intent(self):
        spec = get_capability_spec(self.capability)
        if spec is None:
            raise ValueError(f"未知 capability: {self.capability}")
        self.business_line = spec.business_line
        self.intent = spec.legacy_intent
        if self.capability == "clarify" or self.confidence < 0.60:
            self.needs_clarification = True
        if self.needs_clarification and not self.clarification_question:
            self.clarification_question = "请明确您要处理的业务、案件和具体操作。"
        return self


class WriteCommandModel(BaseModel):
    """Trusted command slots supplied by the frontend for deterministic writes."""

    model_config = ConfigDict(extra="forbid")

    capability: Literal["case.create", "material.upload", "task.write"] | None = Field(
        default=None,
        description="可选写能力强信号；必须与实际命令字段和路由结果一致。",
    )
    case_name: str = Field(default="", max_length=200, description="建案时的案件名称。")
    debtor_name: str = Field(default="", max_length=200, description="建案时的债务人名称。")
    case_type: Literal["单户", "资产包", "破产重整", "执转破"] | None = Field(
        default=None,
        description="建案类型；为空时使用破产重整。",
    )
    debtor_uscc: str = Field(default="", max_length=64, description="债务人统一社会信用代码。")
    asset_purchaser_name: str = Field(default="", max_length=200, description="可选资产购买方。")

    task_action: Literal["create", "complete", "assign", "update"] | None = Field(
        default=None,
        description="任务写动作。",
    )
    task_id: int | None = Field(default=None, ge=1, description="任务编号。")
    task_title: str = Field(default="", max_length=500, description="创建任务时的动作标题。")
    task_detail: str = Field(default="", max_length=2000, description="任务详情。")
    assigned_to: str = Field(default="", max_length=200, description="指派到的用户或姓名。")
    assigned_role: str = Field(default="", max_length=100, description="创建任务时的执行角色。")
    new_status: Literal["待执行", "进行中", "已完成", "逾期", "已取消"] | None = Field(
        default=None,
        description="更新后的任务状态。",
    )
    completion_note: str = Field(default="", max_length=2000, description="完成说明。")
    deadline: str = Field(default="", max_length=32, description="任务期限，建议 YYYY-MM-DD。")
    deliverable: str = Field(default="", max_length=500, description="任务交付物。")
    priority: Literal["紧急", "高", "中", "低"] | None = Field(
        default=None,
        description="任务优先级。",
    )


class IntentRouteModel(BaseModel):
    """Legacy three-way router schema kept for compatibility with older callers."""

    intent: Literal["full_audit", "drilldown", "re_audit"] = Field(
        description="生成新报告选 full_audit，局部追问或任务管理选 drilldown，修正并重审选 re_audit"
    )


class CorrectionModel(BaseModel):
    target: str = Field(description="修正的资产、标的或结论对象")
    instruction: str = Field(description="强制修正指令")


class CorrectionLedgerItemModel(BaseModel):
    target: str = Field(description="修正作用的标的")
    instruction: str = Field(description="修正内容")
    source_query: str = Field(description="触发修正的原始用户话术")


class RecoveryItemModel(BaseModel):
    amount: float = Field(description="已实际收到的回款金额（元，数字）")
    recovered_at: str = Field(default="", description="收款日期 YYYY-MM-DD；无则空")
    source_desc: str = Field(default="", description="回款来源/资产说明，如某房产拍卖款、分红")
    disposal_path: str = Field(default="", description="处置路径：清算拍卖/破产重整/协商和解/执行/分红/其它")


class RecoveryExtractionModel(BaseModel):
    records: list[RecoveryItemModel] = Field(
        default_factory=list,
        description="文本中明确**已实际发生**的回款记录；忽略预期/计划/目标；无则空列表",
    )


class ParseDocumentResultModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    case_id: int = 0
    debtor_id: int = 0
    debtor_name: str = ""
    categories_found: list[str] = Field(default_factory=list)
    records_inserted: int = 0
    details: list[dict] = Field(default_factory=list)
    message: str = ""


class DocCategoryDefinitionModel(BaseModel):
    code: str = Field(description="稳定类别编码。")
    name: str = Field(description="类别中文名称。")
    description: str = Field(default="", description="类别说明。")
    sort_order: int = Field(default=0, description="前端排序号。")
    enabled: bool = Field(default=True, description="该类别是否启用。")
    fields: list[str] = Field(default_factory=list, description="手动补录时可用字段列表。")


class DocCategoryCatalogModel(BaseModel):
    categories: list[DocCategoryDefinitionModel] = Field(default_factory=list, description="标准卷宗类别字典。")


class CaseDocCategoryStatusItemModel(BaseModel):
    code: str = Field(description="稳定类别编码。")
    name: str = Field(description="类别中文名称。")
    uploaded: bool = Field(default=False, description="当前案件是否已有该类材料。")
    file_count: int = Field(default=0, description="该类已上传文件数。")
    record_count: int = Field(default=0, description="该类已入库记录数。")
    last_uploaded_at: str | None = Field(default=None, description="最近一次上传时间。")


class CaseDocCategoryStatusModel(BaseModel):
    case_id: int = Field(default=0, description="案件 ID。")
    categories: list[CaseDocCategoryStatusItemModel] = Field(default_factory=list, description="案件类别覆盖情况。")
    missing_categories: list[str] = Field(default_factory=list, description="当前仍缺失的类别编码。")


class ValidateDocCategoryRequestModel(BaseModel):
    case_id: int = Field(default=0, description="案件 ID。")
    doc_category: str = Field(description="用户选择的卷宗类别编码。")
    file_names: list[str] = Field(default_factory=list, description="待上传文件名列表。")
    text_preview: str = Field(default="", description="可选文本预览，用于轻校验。")


class ValidateDocCategoryResultModel(BaseModel):
    ok: bool = Field(default=True, description="是否通过基础校验。")
    suspected_mismatch: bool = Field(default=False, description="是否疑似错分类型。")
    suspected_duplicate: bool = Field(default=False, description="是否疑似重复。")
    duplicate_files: list[str] = Field(default_factory=list, description="疑似重复文件名列表。")
    suspected_mismatch_files: list[str] = Field(default_factory=list, description="疑似类别不匹配文件名列表。")
    message: str = Field(default="", description="校验结果说明。")


class FullContextResultModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    case_id: int = 0
    case_profile: dict = Field(default_factory=dict)
    delta_check: dict = Field(default_factory=dict)
    valuation_squeeze: dict = Field(default_factory=dict)
    deadline_scan: dict = Field(default_factory=dict)
    behavioral_scan: dict = Field(default_factory=dict)
    whiteglove: dict = Field(default_factory=dict)
    fund_flow: dict | str | list = Field(default_factory=dict)
    real_estate_evaluations: list[dict] = Field(default_factory=list)
    mining_evaluations: list[dict] = Field(default_factory=list)


class ChunkBBoxModel(BaseModel):
    x: float = Field(description="高亮框左上角 X 坐标。")
    y: float = Field(description="高亮框左上角 Y 坐标。")
    w: float = Field(description="高亮框宽度。")
    h: float = Field(description="高亮框高度。")


class SourceChunkModel(BaseModel):
    chunk_id: str = Field(description="稳定 chunk ID。")
    case_id: int = Field(description="所属案件 ID。")
    file_id: int = Field(description="所属文件 ID。")
    page_id: int = Field(description="所属页 ID。")
    page_no: int = Field(description="所在页码。")
    chunk_index: int = Field(description="页内 chunk 顺序号。")
    chunk_type: str = Field(description="chunk 类型，如 text、table、title。")
    chunk_text: str = Field(description="chunk 正文文本。")
    chunk_text_sha256: str = Field(description="chunk 文本 SHA256。")
    anchor_text: str = Field(default="", description="用于回显的短锚文本。")
    bbox_list: list[ChunkBBoxModel] = Field(default_factory=list, description="该 chunk 命中的坐标框列表。")
    span_start: int = Field(default=0, description="chunk 在页文本中的起始字符位置。")
    span_end: int = Field(default=0, description="chunk 在页文本中的结束字符位置。")
    token_count: int = Field(default=0, description="该 chunk 的近似 token 数。")
    metadata: dict[str, Any] = Field(default_factory=dict, description="chunk 扩展元数据。")


class ExtractedEntityModel(BaseModel):
    entity_temp_id: str = Field(description="本批抽取内的临时实体 ID，用于 relation 引用。")
    entity_type: str = Field(description="实体类型，如 company、person、asset。")
    name: str = Field(description="抽取到的实体名称。")
    aliases: list[str] = Field(default_factory=list, description="实体别名列表。")
    attributes: dict[str, Any] = Field(default_factory=dict, description="实体扩展属性。")
    evidence_chunk_ids: list[str] = Field(default_factory=list, description="支撑该实体的证据 chunk_id 列表。")
    confidence: float = Field(description="实体抽取置信度。")


class ExtractedRelationModel(BaseModel):
    relation_temp_id: str = Field(description="本批抽取内的临时关系 ID。")
    from_entity_temp_id: str = Field(description="关系起点临时实体 ID。")
    to_entity_temp_id: str = Field(description="关系终点临时实体 ID。")
    relation_type: str = Field(description="关系类型编码，如 guarantee、bank_flow。")
    relation_label: str = Field(description="关系显示标签。")
    amount: float | None = Field(default=None, description="关系相关金额。")
    amount_currency: str = Field(default="CNY", description="金额币种。")
    event_date: str | None = Field(default=None, description="关系发生日期。")
    attributes: dict[str, Any] = Field(default_factory=dict, description="关系扩展属性。")
    evidence_chunk_ids: list[str] = Field(default_factory=list, description="支撑该关系的证据 chunk_id 列表。")
    confidence: float = Field(description="关系抽取置信度。")


class ExtractionClaimModel(BaseModel):
    claim_type: str = Field(description="断言类型，如 entity_fact、relation_fact、risk_signal。")
    claim_text: str = Field(description="断言自然语言文本。")
    entity_name: str = Field(default="", description="可选，claim 关联实体名称，供跨批解析与 unresolved 治理使用。")
    entity_key: str = Field(default="", description="可选，claim 关联实体稳定键，供跨批解析使用。")
    entity_temp_id: str | None = Field(default=None, description="关联的临时实体 ID。")
    relation_key: str = Field(default="", description="可选，claim 关联关系稳定键，供跨批解析使用。")
    relation_temp_id: str | None = Field(default=None, description="关联的临时关系 ID。")
    claim_value: dict[str, Any] = Field(default_factory=dict, description="断言结构化值。")
    evidence_chunk_ids: list[str] = Field(default_factory=list, description="支撑该断言的证据 chunk_id 列表。")
    confidence: float = Field(description="断言置信度。")
    status: str = Field(default="active", description="断言事实状态，如 active、superseded、invalid。")
    review_status: str = Field(default="pending", description="人工审核状态，如 pending、approved、rejected、corrected。")


class ExtractionBundleModel(BaseModel):
    entities: list[ExtractedEntityModel] = Field(default_factory=list, description="抽取到的实体列表。")
    relations: list[ExtractedRelationModel] = Field(default_factory=list, description="抽取到的关系列表。")
    claims: list[ExtractionClaimModel] = Field(default_factory=list, description="抽取到的断言列表。")


class UnresolvedRelationItemModel(BaseModel):
    relation_temp_id: str = Field(default="", description="本批关系临时 ID。")
    relation_key: str = Field(default="", description="关系稳定键。")
    relation_type: str = Field(default="", description="关系类型。")
    relation_label: str = Field(default="", description="关系显示标签。")
    from_entity_temp_id: str = Field(default="", description="关系起点临时实体 ID。")
    to_entity_temp_id: str = Field(default="", description="关系终点临时实体 ID。")
    missing_dependencies: list[str] = Field(default_factory=list, description="缺失的依赖项，如 from_entity、to_entity。")
    reason: str = Field(default="", description="未能落库的原因。")
    evidence_chunk_ids: list[str] = Field(default_factory=list, description="关系关联的证据 chunk 列表。")


class UnresolvedClaimItemModel(BaseModel):
    claim_type: str = Field(default="", description="断言类型。")
    claim_text: str = Field(default="", description="断言文本。")
    entity_name: str = Field(default="", description="claim 关联实体名称。")
    entity_key: str = Field(default="", description="claim 关联实体稳定键。")
    entity_temp_id: str = Field(default="", description="claim 关联实体临时 ID。")
    relation_key: str = Field(default="", description="claim 关联关系稳定键。")
    relation_temp_id: str = Field(default="", description="claim 关联关系临时 ID。")
    missing_dependencies: list[str] = Field(default_factory=list, description="缺失的依赖项，如 entity、relation。")
    reason: str = Field(default="", description="未能落库的原因。")
    evidence_chunk_ids: list[str] = Field(default_factory=list, description="claim 关联的证据 chunk 列表。")


class GraphDeltaDecisionModel(BaseModel):
    new_claim_text: str = Field(description="本次新增 claim 文本。")
    action: Literal["ADD", "OVERRIDE"] = Field(description="新增事实用 ADD，推翻旧结论用 OVERRIDE。")
    supersede_claim_ids: list[int] = Field(default_factory=list, description="若为 OVERRIDE，需要软失效的旧 claim_id 列表。")
    rationale: str = Field(default="", description="简短说明判断依据。")


class GraphDeltaDecisionBundleModel(BaseModel):
    decisions: list[GraphDeltaDecisionModel] = Field(default_factory=list, description="逐条新增 claim 的增量对账裁决。")


class ReconciliationLedgerItemModel(BaseModel):
    case_id: int = Field(default=0, description="案件 ID。")
    action: Literal["ADD", "OVERRIDE"] = Field(default="ADD", description="增量对账动作。")
    new_claim_id: int | None = Field(default=None, description="本次新增 claim_id；relation 型条目为空。")
    new_claim_text: str = Field(default="", description="本次新增 claim 文本。")
    superseded_claim_id: int | None = Field(default=None, description="被软失效的旧 claim_id；relation 型条目为空。")
    superseded_claim_text: str = Field(default="", description="被软失效的旧 claim 文本。")
    new_relation_id: int | None = Field(default=None, description="本次新增 relation_id；claim 型条目为空。")
    superseded_relation_id: int | None = Field(default=None, description="被软失效的旧 relation_id；claim 型条目为空。")
    rationale: str = Field(default="", description="裁决原因说明。")
    evidence_chunk_ids: list[str] = Field(default_factory=list, description="支持本次裁决的新增证据 chunk_id。")
    decision_payload: dict[str, Any] = Field(default_factory=dict, description="裁决时保留的补充元数据。")


class GraphNodeModel(BaseModel):
    id: str = Field(description="前端图谱节点 ID。")
    entity_id: int = Field(description="实体主键 ID。")
    label: str = Field(description="节点显示名称。")
    entity_type: str = Field(description="节点实体类型。")
    risk_level: str = Field(default="unknown", description="节点风险等级。")


class GraphEdgeModel(BaseModel):
    id: str = Field(description="前端图谱边 ID。")
    relation_id: int = Field(description="关系主键 ID。")
    source: str = Field(description="起点节点 ID。")
    target: str = Field(description="终点节点 ID。")
    label: str = Field(description="边显示名称。")
    relation_type: str = Field(description="关系类型。")
    confidence: float = Field(default=0, description="关系置信度。")


class EvidenceItemModel(BaseModel):
    chunk_id: str = Field(description="证据 chunk ID。")
    file_id: int = Field(description="所属文件 ID。")
    file_name: str = Field(default="", description="所属文件名。")
    page_no: int = Field(description="所在页码。")
    quote_text: str = Field(default="", description="证据原文片段。")
    bbox_list: list[ChunkBBoxModel] = Field(default_factory=list, description="高亮框列表。")
    page_image_ref: str = Field(default="", description="页图引用。")
    source_page_id: int = Field(default=0, description="来源页 ID。")
    source_file_url: str = Field(default="", description="原始文件公网 URL，前端据此渲染页面与 bbox 高亮（图片用 img、PDF 用 PDF.js 按 page_no）。")
    content_type: str = Field(
        default="",
        description=(
            "源文件 MIME 类型，供前端切换渲染模式："
            "text/* 等纯文本类源文件天然无页面排版（page_width/height=0、bbox_list 恒空、page_image_ref 空），"
            "前端应只用 quote_text 文本展示；其它类型（application/pdf、image/* 等）才走 source_file_url + bbox 高亮。"
        ),
    )
    entity_id: int = Field(default=0, description="该证据所属 claim 关联的实体 ID，可直接传给 /graph/subgraph 的 center_entity_id。")


class TraceItemModel(BaseModel):
    citation_id: str = Field(default="", description="报告内可点击的稳定引用 ID。")
    claim_id: int = Field(description="断言 ID。")
    claim_type: str = Field(default="", description="断言类型。")
    claim_text: str = Field(default="", description="断言文本。")
    confidence: float = Field(default=0, description="断言置信度。")
    entity_id: int = Field(default=0, description="该断言关联的实体 ID，可直接传给 /graph/subgraph 的 center_entity_id。")
    evidences: list[EvidenceItemModel] = Field(default_factory=list, description="支撑断言的证据列表。")


class CitationCoverageMissingItemModel(BaseModel):
    citation_id: str = Field(default="", description="已分配的报告角标 ID。")
    claim_id: int = Field(default=0, description="未命中正文角标的断言 ID。")
    claim_type: str = Field(default="", description="断言类型。")
    claim_text: str = Field(default="", description="未命中正文角标的断言文本。")


class CitationCoverageModel(BaseModel):
    total_claims: int = Field(default=0, description="纳入报告角标规划的断言总数。")
    cited_claims: int = Field(default=0, description="正文内已命中角标的断言数。")
    uncited_claims: int = Field(default=0, description="正文内未命中角标的断言数。")
    coverage_ratio: float = Field(default=0, description="正文角标覆盖率，0-1。")
    missing_items: list[CitationCoverageMissingItemModel] = Field(
        default_factory=list,
        description="当前仍未在正文命中的关键断言列表。",
    )


class EvidenceResolveRequestModel(BaseModel):
    case_id: int = Field(description="案件 ID。")
    report_ref: str = Field(default="", description="报告引用 ID；通常对应 final_report_ref。")
    citation_id: str = Field(default="", description="报告内的角标引用 ID。")
    claim_id: int = Field(default=0, description="断言 ID；如果前端只拿到 citation_id，可不传。")


class EvidenceDrawerPageModel(BaseModel):
    file_id: int = Field(default=0, description="抽屉默认展示的文件 ID。")
    page_no: int = Field(default=0, description="抽屉默认展示的页码。")
    page_width: int = Field(default=0, description="页图宽度。")
    page_height: int = Field(default=0, description="页图高度。")
    page_image_ref: str = Field(default="", description="页图引用。")
    source_file_url: str = Field(default="", description="该页原始文件公网 URL，前端据此渲染页面与 bbox 高亮。")
    content_type: str = Field(default="", description="源文件 MIME 类型；text/* 等纯文本类只用 quote_text 渲染，详见 EvidenceItem.content_type。")
    anchors: list[EvidenceItemModel] = Field(default_factory=list, description="该页可直接高亮的锚点列表。")


class EvidenceResolveResponseModel(BaseModel):
    case_id: int = Field(description="案件 ID。")
    report_ref: str = Field(default="", description="报告引用 ID。")
    citation_id: str = Field(default="", description="报告内的角标引用 ID。")
    claim_id: int = Field(description="断言 ID。")
    claim_text: str = Field(default="", description="断言文本。")
    evidences: list[EvidenceItemModel] = Field(default_factory=list, description="证据列表。")
    primary_evidence: EvidenceItemModel | None = Field(default=None, description="抽屉首屏默认聚焦的主证据。")
    primary_page: EvidenceDrawerPageModel | None = Field(
        default=None,
        description="主证据所在页的高亮锚点数据，前端可直接用于首屏展示。",
    )
    resolution_status: str = Field(
        default="ok",
        description=(
            "解析状态，便于前端区分『空结果』的原因："
            "ok=已解析到证据；no_evidence=claim 有效但暂无证据；"
            "citation_not_found=report_ref 有效但该 citation 不存在；"
            "ref_not_found=report_ref 在库中不存在（通常是前端自拼了无效 ref，"
            "应改为透传 /chat/invoke 或 messages 返回的真实 final_report_ref）。"
        ),
    )


class RelationEvidenceRequestModel(BaseModel):
    case_id: int = Field(description="案件 ID。")
    relation_id: int = Field(description="关系 ID。")


class RelationEvidenceResponseModel(BaseModel):
    case_id: int = Field(description="案件 ID。")
    relation_id: int = Field(description="关系 ID。")
    trace_items: list[TraceItemModel] = Field(default_factory=list, description="该关系关联的 claim 与证据链。")


class DemoCaseTraceValidationRequestModel(BaseModel):
    case_id: int = Field(description="标杆案件 ID。")
    report_ref: str = Field(default="", description="待验收的最终报告引用 ID。")
    citation_ids: list[str] = Field(default_factory=list, description="可选；只校验指定角标。为空时校验该报告全部角标。")


class DemoCaseTraceCheckModel(BaseModel):
    citation_id: str = Field(default="", description="报告角标 ID。")
    claim_id: int = Field(default=0, description="角标映射到的断言 ID。")
    claim_text: str = Field(default="", description="断言文本。")
    ok: bool = Field(default=False, description="该角标的回源链路是否通过。")
    evidence_count: int = Field(default=0, description="claim 下证据数量。")
    anchor_count: int = Field(default=0, description="主证据页锚点数量。")
    file_id: int = Field(default=0, description="主证据文件 ID。")
    page_no: int = Field(default=0, description="主证据页码。")
    issues: list[str] = Field(default_factory=list, description="未通过时的具体问题列表。")


class DemoCaseTraceValidationResponseModel(BaseModel):
    case_id: int = Field(description="标杆案件 ID。")
    report_ref: str = Field(default="", description="被校验的报告引用 ID。")
    ready: bool = Field(default=False, description="是否达到可演示状态。")
    total_citations: int = Field(default=0, description="本次纳入校验的角标数。")
    passed_citations: int = Field(default=0, description="通过校验的角标数。")
    failed_citations: int = Field(default=0, description="未通过校验的角标数。")
    checks: list[DemoCaseTraceCheckModel] = Field(default_factory=list, description="逐角标校验结果。")
    issues: list[str] = Field(default_factory=list, description="聚合后的问题摘要。")


class GraphSubgraphRequestModel(BaseModel):
    case_id: int = Field(description="案件 ID。")
    center_entity_id: int = Field(description="中心实体 ID。")
    depth: int = Field(default=2, description="向外展开层数。")
    relation_types: list[str] = Field(default_factory=list, description="限定的关系类型列表。")


class GraphSubgraphResponseModel(BaseModel):
    case_id: int = Field(description="案件 ID。")
    nodes: list[GraphNodeModel] = Field(default_factory=list, description="子图节点列表。")
    edges: list[GraphEdgeModel] = Field(default_factory=list, description="子图边列表。")


class EntityListItemModel(BaseModel):
    entity_id: int = Field(description="实体主键 ID，可传给 /graph/subgraph 的 center_entity_id。")
    label: str = Field(default="", description="实体显示名称。")
    entity_type: str = Field(default="", description="实体类型。")
    degree: int = Field(default=0, description="该实体在案件关系图中的连接度数（越高越适合当图谱中心）。")


class CaseEntityListResponse(BaseModel):
    case_id: int = Field(description="案件 ID。")
    entities: list[EntityListItemModel] = Field(default_factory=list, description="案件实体列表，按连接度数降序。")


class PageAnchorsResponseModel(BaseModel):
    file_id: int = Field(description="文件 ID。")
    file_name: str = Field(default="", description="该文件的原始文件名，前端可直接用于『文件名 — 第 N 页』展示。")
    page_no: int = Field(description="页码。")
    page_width: int = Field(default=0, description="页图宽度。")
    page_height: int = Field(default=0, description="页图高度。")
    page_image_ref: str = Field(default="", description="页图引用。")
    source_file_url: str = Field(default="", description="该页原始文件公网 URL，前端据此渲染页面与 bbox 高亮。")
    content_type: str = Field(default="", description="源文件 MIME 类型；text/* 等纯文本类只用 quote_text 渲染，详见 EvidenceItem.content_type。")
    anchors: list[EvidenceItemModel] = Field(default_factory=list, description="本页命中的证据锚点列表。")

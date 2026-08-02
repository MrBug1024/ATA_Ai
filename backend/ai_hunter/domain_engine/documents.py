# ============================================================================
# AI 猎手 — 文档智能分段 + 分类 + 逐类精准提取
#
# 接收 MinerU OCR 输出的 markdown 文本，自动：
#   ① 按页/章节切段
#   ② 分类（规则优先 + LLM 兜底）
#   ③ 逐类调 LLM 精准提取结构化字段
#   ④ 调现有 ingestStructuredFields 入库
#
# 端点：POST /api/ingest/parse-document
# ============================================================================

import json
import logging
import re
import time
import asyncio
import concurrent.futures
import threading
import hashlib
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import db, llm_client

logger = logging.getLogger("ai_hunter.doc_parser")

router = APIRouter()


def _normalize_party_name(name: str) -> str:
    """Normalize names only for exact identity comparison, without role inference."""
    return re.sub(r"\s+", "", str(name or "")).strip()


def _resolve_existing_case_debtor(
    case_id: int,
    debtor_id: Optional[int],
    debtor_name: Optional[str],
) -> tuple[int, str]:
    """Resolve one authoritative debtor for an existing case or fail closed."""
    if debtor_id:
        debtor = db.query_one(
            "SELECT debtor_id, entity_name FROM debtors WHERE case_id=%s AND debtor_id=%s",
            (case_id, debtor_id),
        )
        if not debtor:
            raise HTTPException(404, f"债务人 {debtor_id} 不属于案件 {case_id}")
    else:
        debtors = db.query(
            "SELECT debtor_id, entity_name FROM debtors WHERE case_id=%s ORDER BY debtor_id",
            (case_id,),
        )
        if not debtors:
            raise HTTPException(409, f"案件 {case_id} 尚未建立债务人，请先通过建案流程维护主数据")
        if len(debtors) > 1:
            raise HTTPException(409, f"案件 {case_id} 存在多个债务人，请显式传入 debtor_id")
        debtor = debtors[0]

    resolved_id = int(debtor["debtor_id"])
    authoritative_name = (debtor.get("entity_name") or "").strip()
    if not authoritative_name:
        raise HTTPException(409, f"债务人 {resolved_id} 缺少有效名称，请先修复案件主数据")
    supplied_name = (debtor_name or "").strip()
    if supplied_name and _normalize_party_name(supplied_name) != _normalize_party_name(authoritative_name):
        raise HTTPException(409, "debtor_name 与案件债务人主数据不一致")
    return resolved_id, authoritative_name

# 幂等锁：防止 Dify 超时重试导致同一文件被并发解析两次
# key: (case_id, source_filename) → 开始时间戳
_parse_in_progress: dict[tuple, float] = {}
_parse_results: dict[tuple, dict] = {}          # 缓存上次成功解析的完整响应
_parse_lock = threading.Lock()

# ============================================================================
# 13 类文档分类定义
# ============================================================================

DOC_CATEGORIES = {
    "贷款合同": {
        "keywords": ["贷款合同", "借款合同", "授信合同", "金融借款", "贷款本金", "贷款期限",
                      "还款方式", "年利率", "罚息", "逾期利息", "信用额度"],
        "fields": {
            "principal": "贷款本金（元）",
            "interest": "利息（元）",
            "penalty": "罚息（元）",
            "delayed_interest": "迟延履行利息（元）",
            "total_claim": "债权总额（元）",
            "guarantee_type": "担保方式（信用/抵押/质押/保证）",
            "collateral_desc": "抵押物/质押物描述",
            "lien_priority": "抵押顺位（数字）",
            "court_name": "执行法院",
            "exec_case_no": "执行案号",
            "litigation_status": "诉讼状态（未诉/已诉/已判/执行中/终本）",
            "guarantor_names": "保证人名称列表（逗号分隔）",
        },
    },
    "判决书": {
        "keywords": ["判决书", "裁定书", "调解书", "执行裁定", "民事判决", "民事裁定",
                      "本院认为", "判决如下", "裁定如下", "案号", "原告", "被告",
                      "申请执行人", "被执行人", "执行进展", "查封", "冻结"],
        "fields": {
            "case_number": "案号，如(2023)晋XX民初XXX号",
            "court_name": "法院名称",
            "case_cause": "案由",
            "doc_type": "文书类型（判决书/裁定书/调解书/执行裁定）",
            "judgment_date": "裁判日期（YYYY-MM-DD）",
            "plaintiff": "原告列表",
            "defendant": "被告列表",
            "claim_amount": "诉请金额（元）",
            "judgment_amount": "判决金额（元）",
            "execution_status": "执行状态",
            "enforcement_deadline": "执行时效截止日（YYYY-MM-DD，如有）",
            "court_level": "法院级别（基层/中级/高级，如有）",
            "case_type": "案件类型（民事/执行/破产，如有）",
            "sealed_real_estates": "查封不动产列表（数组），每条含：owner(产权人), address(地址), cert_no(产权证号), seal_start(查封起始日YYYY-MM-DD), seal_end(查封到期日YYYY-MM-DD)",
            "sealed_vehicles": "查封车辆列表（数组），每条含：owner(车主), plate_no(车牌号), seal_start(查封起始日YYYY-MM-DD), seal_end(查封到期日YYYY-MM-DD)",
            "sealed_mining_rights": "查封采矿权描述（如有）",
        },
    },
    "财务报表": {
        "keywords": ["资产负债表", "利润表", "损益表", "财务报表", "审计报告",
                      "其他应收款", "预付账款", "资产总额", "负债总额", "营业收入",
                      "净利润", "所有者权益", "流动资产", "固定资产"],
        "fields": {
            "report_period": "报告期间（如2022-12）",
            "report_type": "报表类型（资产负债表/利润表）",
            "other_receivables": "其他应收款（元）",
            "prepayments": "预付账款（元）",
            "total_assets": "资产总额（元）",
            "total_liabilities": "负债总额（元）",
            "revenue": "营业收入（元）",
            "operating_cost": "营业成本（元）",
            "net_profit": "净利润（元）",
            "tax_reported_revenue": "税务申报营收（如有，元）",
            "tax_reported_cost": "税务申报成本（如有，元）",
        },
    },
    "不动产权证": {
        "keywords": ["不动产权证", "不动产权", "房屋所有权证", "土地使用权证", "房产证",
                      "国有土地使用证", "坐落", "建筑面积", "土地面积", "房屋用途",
                      "不动产单元号"],
        "fields": {
            "property_owner": "物权人",
            "property_address": "坐落地址",
            "real_estate_cert_no": "不动产权证号",
            "land_nature": "土地性质（出让/划拨）",
            "total_building_area": "建筑面积（㎡）",
            "land_use_area": "土地面积（㎡）",
            "property_usage": "用途（住宅/商业/工业）",
            "mortgage_status": "抵押状态",
            "seal_status": "查封状态",
            "seal_expiry": "查封到期日（YYYY-MM-DD，如有）",
            "lease_status": "租赁状态（如有）",
            "gross_value": "评估价值（如有，元）",
            "has_title_objection": "是否有权属异议（是/否）",
            "physical_occupation": "第三方占用情况（如有描述）",
            "lien_priority": "抵押顺位（数字，如有）",
            "sealing_court": "查封法院（如有）",
            "lease_annual_rent": "年租金（元，如有）",
            "lease_start": "租赁起始日（YYYY-MM-DD，如有）",
            "lease_end": "租赁到期日（YYYY-MM-DD，如有）",
        },
    },
    "采矿许可证": {
        "keywords": ["采矿许可证", "采矿权", "矿区范围", "开采矿种", "生产规模",
                      "有效期限", "矿山名称", "采矿权人"],
        "fields": {
            "mine_name": "矿名",
            "mine_location": "矿区位置",
            "permit_expiry": "许可证到期日（YYYY-MM-DD）",
            "production_scale": "生产规模（万吨/年）",
            "mineral_type": "矿种",
            "mine_scale": "矿山规模（大型/中型/小型）",
            "mining_status": "开采状态",
            "safety_permit_status": "安全生产许可证状态",
            "env_approval_status": "环评批复状态",
            "mining_right_mortgage": "抵押状态",
            "mining_right_sealed": "查封状态",
            "proved_reserves": "探明储量（万吨，如有）",
            "estimated_value": "估值（如有，元）",
            "eco_redline_status": "是否涉及生态红线（涉及/未涉及）",
        },
    },
    "银行流水": {
        "keywords": ["银行流水", "交易明细", "交易流水", "转账记录", "对账单",
                      "交易时间", "交易金额", "付款人", "收款人", "摘要",
                      "审批单", "制单人", "复核人", "审批人"],
        "fields": {
            "transactions": "交易列表（数组），每条含：txn_date(交易日期), txn_amount(金额/元), txn_direction(方向in/out), counterparty(交易对手), maker(制单人), reviewer(复核人), approver(审批人)",
        },
    },
    "担保合同": {
        "keywords": ["担保合同", "保证合同", "保证人", "连带保证", "一般保证",
                      "保证责任", "保证期间", "保证范围", "配偶"],
        "fields": {
            "guarantor_name": "保证人名称",
            "guarantor_type": "企业保证人/自然人保证人",
            "guarantee_type": "连带保证/一般保证",
            "guarantee_scope": "保证范围",
            "spouse_name": "配偶姓名（如有）",
        },
    },
    "煤矿重整方案": {
        "keywords": ["重整方案", "重整计划", "破产重整", "重整投资", "管理人",
                      "债权人会议", "清偿率", "普通债权", "担保债权", "职工债权"],
        "fields": {
            "mine_name": "矿名",
            "debtor_name": "重整申请人/债务人名称",
            "administrator": "破产管理人名称",
            "administrator_contact": "管理人联系人及电话",
            "investor_name": "重整投资人名称（如有）",
            "investor_contact": "投资人联系人及电话",
            "total_debt": "债务总额（元）",
            "secured_debt": "有担保债权总额（元）",
            "unsecured_debt": "普通债权总额（元）",
            "employee_debt": "职工债权总额（元）",
            "tax_debt": "税款债权总额（元）",
            "proposed_recovery_rate": "方案提出的清偿率（%）",
            "transfer_base_price": "协议转让底价/重整投资对价（元）",
            "asset_list_summary": "资产清单概述",
            "restructuring_timeline": "重整计划时间表",
            "court_name": "受理法院",
            "case_number": "破产案号",
            "key_conditions": "重整方案核心条件",
        },
    },
    "勘探报告": {
        "keywords": ["勘探报告", "勘查报告", "地质报告", "储量报告", "资源量",
                      "探明储量", "控制储量", "煤层", "地质构造", "水文地质",
                      "瓦斯等级", "发热量", "灰分", "硫分"],
        "fields": {
            "mine_name": "矿名",
            "report_name": "报告全称",
            "report_date": "报告日期",
            "report_org": "编制单位",
            "approval_org": "审批机构",
            "approval_date": "批复日期",
            "approval_number": "批复文号",
            "mineral_type": "矿种",
            "proved_reserves": "探明储量（万吨）",
            "controlled_reserves": "控制储量（万吨）",
            "inferred_resources": "推断资源量（万吨）",
            "total_reserves": "总储量（万吨）",
            "mining_area_km2": "矿区面积（k㎡）",
            "seam_count": "可采煤层数",
            "avg_seam_thickness": "平均煤层厚度（m）",
            "burial_depth_range": "埋深范围（m）",
            "calorific_value": "发热量（cal/g）",
            "ash_content_pct": "灰分（%）",
            "sulfur_content_pct": "硫分（%）",
            "coal_type": "煤种",
            "hydrogeology": "水文地质条件（简单/中等/复杂）",
            "gas_level": "瓦斯等级（低瓦斯/高瓦斯/煤与瓦斯突出）",
            "geological_complexity": "构造复杂程度（简单/中等/复杂）",
        },
    },
    "环评批复": {
        "keywords": ["环评批复", "环境影响", "环评报告", "环保审批", "环评审批",
                      "排放标准", "环保措施", "生态红线", "环境影响评价"],
        "fields": {
            "mine_name": "矿名/项目名",
            "env_approval_status": "环评状态（已批复/未批复/已过期/整改中）",
            "approval_org": "审批机构",
            "approval_date": "批复日期",
            "approval_number": "批复文号",
            "project_scale": "项目规模（万吨/年）",
            "env_impact_summary": "主要环境影响概述",
            "required_measures": "批复要求的环保措施清单",
            "emission_limits": "排放限值要求（如有）",
            "eco_redline_status": "是否涉及生态红线（涉及/未涉及）",
            "validity_period": "批复有效期（如有）",
            "rectification_requirements": "整改要求（如有）",
            "total_env_investment": "环保投资总额（万元，如有）",
        },
    },
    "法院总对总": {
        "keywords": ["总对总", "网络查控", "查控系统", "被执行人财产", "银行存款查询",
                      "不动产查询", "车辆查询", "证券查询", "冻结", "账户余额"],
        "fields": {
            "target_name": "被查询人姓名/公司名",
            "query_date": "查询日期",
            "bank_deposits": "银行存款查询结果（数组），每条含：bank_name(银行名称), account_masked(账号脱敏), balance(余额/元), status(状态:正常/冻结/销户), frozen_amount(冻结金额)",
            "real_estate_hits": "不动产查询结果（数组），每条含：location(坐落), cert_no(权证号), area_sqm(面积), status(状态:正常/查封/抵押)",
            "vehicle_hits": "车辆查询结果（数组），每条含：plate_no(车牌号), brand_model(品牌型号), status(状态)",
            "securities_hits": "证券/基金查询结果（如有）",
            "insurance_hits": "保险查询结果（如有）",
            "other_hits": "其他财产线索",
        },
    },
    "律师调查报告": {
        "keywords": ["律师调查", "实地调查", "现场调查", "调查报告", "走访",
                      "人去楼空", "停业", "经营状况", "留守", "看门人"],
        "fields": {
            "investigator": "调查律师姓名",
            "investigation_date": "调查日期",
            "investigation_scope": "调查范围概述",
            "debtor_operating_status": "实际经营状况描述",
            "physical_address_verified": "实际地址是否核实（是/否）",
            "physical_address_status": "实地情况（正常经营/停业/人去楼空/被他人占用）",
            "employee_status": "员工情况（正常/已遣散/少量留守）",
            "asset_on_site": "现场可见资产描述",
            "lease_situation": "租赁情况描述",
            "key_person_contacts": "关键人员联系方式（数组），每条含name(姓名), role(身份), phone(电话), info_provided(提供的信息摘要)",
            "related_party_findings": "关联方线索",
            "asset_transfer_clues": "资产转移线索",
            "legal_proceedings_info": "诉讼/执行信息",
            "local_reputation": "当地口碑/舆情",
            "photos_description": "照片内容摘要",
            "investigation_conclusion": "调查结论/建议",
        },
    },
    "开采设计与复垦": {
        "keywords": ["初步设计", "开采设计", "开采方案", "复垦方案", "复垦备案",
                      "采煤方法", "服务年限", "设计产能", "建设工期", "安全设施",
                      "复垦面积", "复垦保证金"],
        "fields": {
            "mine_name": "矿名",
            "doc_subtype": "子类型（初步设计/开采设计方案/开采设计批复/复垦方案/复垦备案）",
            "design_org": "设计单位",
            "design_date": "设计日期",
            "approval_org": "批复机构（如有）",
            "approval_date": "批复日期（如有）",
            "approval_number": "批复文号（如有）",
            "designed_capacity": "设计产能（万吨/年）",
            "mining_method": "采煤方法",
            "service_life_years": "设计服务年限（年）",
            "total_investment": "项目总投资（万元）",
            "construction_period": "建设工期（月）",
            "safety_facilities_investment": "安全设施投资（万元）",
            "reclamation_area_ha": "复垦面积（公顷，复垦类）",
            "reclamation_deposit": "复垦保证金（万元，复垦类）",
            "reclamation_deadline": "复垦完成时限（复垦类）",
            "current_status": "当前状态（在建/已建成/停工/未开工）",
        },
    },
}


# ============================================================================
# 文本分段器：按 MinerU 输出的 markdown 结构切分
# ============================================================================

def _split_segments(text: str) -> list[dict]:
    """
    将 MinerU markdown 输出切分为段落。策略：
    1. 优先按 --- (分页符) 切分
    2. 再按 ## / # 标题切分
    3. 每段保留标题上下文，控制在 ~4000 字以内
    4. 子段落携带页面上下文头，防止分类丢失
    """
    segments = []

    # 先按分页符切
    pages = re.split(r'\n-{3,}\n|\n={3,}\n|\f', text)
    if len(pages) <= 1:
        pages = [text]

    for page_idx, page in enumerate(pages):
        page = page.strip()
        if not page:
            continue

        # 提取页面上下文头（前3行非空行），供子段落继承分类
        _lines = [l for l in page.split('\n') if l.strip()]
        page_context = "\n".join(_lines[:3])

        # 如果单页太长（>6000字），按标题二次切分
        if len(page) > 6000:
            sub_parts = re.split(r'\n(?=#{1,3}\s)', page)
            for sub_idx, sub in enumerate(sub_parts):
                sub = sub.strip()
                if not sub:
                    continue
                # 仍然太长的段落，在换行处切分（避免切断表格行）
                if len(sub) > 6000:
                    # 提取本子段自己的标题头，用于续块的 context（而非父页面上下文）
                    sub_lines = [l for l in sub.split('\n') if l.strip()]
                    sub_context = "\n".join(sub_lines[:3]) if sub_lines else page_context
                    lines = sub.split('\n')
                    chunk_lines, chunk_len = [], 0
                    is_first = True
                    for line in lines:
                        if chunk_len + len(line) > 5000 and chunk_lines:
                            segments.append({
                                "text": "\n".join(chunk_lines),
                                "page": page_idx + 1,
                                "context": "" if is_first else sub_context,
                            })
                            chunk_lines, chunk_len = [], 0
                            is_first = False
                        chunk_lines.append(line)
                        chunk_len += len(line) + 1
                    if chunk_lines:
                        segments.append({
                            "text": "\n".join(chunk_lines),
                            "page": page_idx + 1,
                            "context": "" if is_first else sub_context,
                        })
                else:
                    # 按标题切分的子段落自带 # 标题头，不需继承父页面 context
                    # 只有无标题的纯续段才回退到 page_context
                    has_own_header = sub.lstrip().startswith('#')
                    segments.append({
                        "text": sub,
                        "page": page_idx + 1,
                        "context": "" if (sub_idx == 0 or has_own_header) else page_context,
                    })
        else:
            segments.append({"text": page, "page": page_idx + 1, "context": ""})

    return segments


# ============================================================================
# 分类器：规则优先 + LLM 兜底
# ============================================================================

def _classify_by_rules(text: str) -> list[str]:
    """关键词命中分类，返回命中的类别列表（可能多个）"""
    text_lower = text.lower()
    hits = []
    for cat, cfg in DOC_CATEGORIES.items():
        score = sum(1 for kw in cfg["keywords"] if kw in text_lower)
        if score >= 2:
            hits.append((cat, score))
    # 按命中数降序
    hits.sort(key=lambda x: -x[1])
    return [h[0] for h in hits]


def _classify_by_llm(text: str) -> list[str]:
    """LLM 兜底分类：当规则分类器无法判断时调用"""
    categories_list = "、".join(DOC_CATEGORIES.keys())
    system = (
        "你是文档类型分类器。根据文本内容判断它属于以下哪个或哪几个类别，"
        "只返回类别名称，用逗号分隔，不要解释。如果无法判断返回'未知'。\n"
        f"可选类别：{categories_list}"
    )
    # 只取前 2000 字给 LLM 分类，节省 token
    snippet = text[:2000]
    try:
        raw = llm_client.chat(system, snippet, temperature=0.05, max_tokens=100)
    except Exception as e:
        # LLM 分类失败（如 422 敏感内容），跳过该段而不是崩溃整个请求
        logger.warning("[DocParser] LLM分类失败，跳过该段: %s | 段落前50字: %.50s",
                       str(e), text)
        return []
    # 解析返回的类别
    result = []
    for cat in DOC_CATEGORIES:
        if cat in raw:
            result.append(cat)
    return result


def classify_segment(text: str, context: str = "") -> list[str]:
    """对一个段落做分类,返回类别列表。context 是父页面上下文头，用于续段回退分类"""
    cats = _classify_by_rules(text)
    if cats:
        return cats
    # 续段：用页面上下文头补充分类（解决表格续页无关键词的问题）
    if context:
        cats = _classify_by_rules(context + "\n" + text)
        if cats:
            return cats
    # 规则未命中，LLM 兜底（附带上下文）
    llm_text = (context + "\n" + text) if context else text
    cats = _classify_by_llm(llm_text)
    return cats if cats else []


# ============================================================================
# 逐类精准提取：每次只传该段文本 + 该类字段定义
# ============================================================================

def _build_extraction_prompt(category: str, fields: dict) -> str:
    """构建某一类别的提取 system prompt"""
    field_lines = "\n".join(f'  - {k}: {v}' for k, v in fields.items())
    return (
        f"你是专业的不良资产数据提取员。从用户提供的文本中提取【{category}】的结构化数据。\n\n"
        f"需提取字段：\n{field_lines}\n\n"
        "规则：\n"
        "1. 只返回JSON对象，不要解释，不要markdown代码块标记\n"
        "2. 找不到的字段不要包含在JSON中，不要编造\n"
        "3. 金额统一为元（数字），日期格式YYYY-MM-DD\n"
        "4. 数组字段返回JSON数组\n"
        "5. 如果文本中有多个报告期（如多年财务报表），返回数组，每个元素是一个报告期的数据"
    )


def extract_fields_for_category(category: str, text: str) -> dict | list | None:
    """对指定类别从文本中提取结构化字段"""
    cfg = DOC_CATEGORIES.get(category)
    if not cfg:
        return None
    system = _build_extraction_prompt(category, cfg["fields"])
    try:
        result = llm_client.chat_json(system, text, temperature=0.05)
    except Exception as e:
        logger.error("提取失败[%s]: LLM异常=%s", category, str(e))
        return None
    if isinstance(result, list):
        return result
    if result.get("parse_error"):
        logger.warning("提取失败[%s]: JSON解析错误", category)
        return None
    return result


# ============================================================================
# 调用现有 ingestStructuredFields 入库
# ============================================================================

def _log_asset_details(category: str, fields: dict):
    """根据不同分类记录关键字段详情（进度追踪）"""
    if not fields or not isinstance(fields, dict):
        return
    
    # 不动产权证/权证文件
    if category in ("不动产权证", "权证文件"):
        details = []
        if fields.get("property_address"):
            details.append(f"地址:{fields['property_address']}")
        if fields.get("total_building_area"):
            details.append(f"建筑面积:{fields['total_building_area']}m²")
        if fields.get("land_use_area"):
            details.append(f"土地面积:{fields['land_use_area']}m²")
        if fields.get("mortgage_status"):
            details.append(f"抵押:{fields['mortgage_status']}")
        if fields.get("seal_status"):
            details.append(f"查封:{fields['seal_status']}")
        if fields.get("seal_expiry"):
            details.append(f"查封到期:{fields['seal_expiry']}")
        if fields.get("gross_value"):
            details.append(f"评估值:¥{fields['gross_value']}")
        if details:
            logger.info("[DocParser][Step 4/4] 不动产详情 | %s", " | ".join(details))
    
    # 采矿权相关（采矿许可证、勘探报告、环评批复、开采设计）
    elif category in ("采矿许可证", "勘探报告", "环评批复", "开采设计与复垦"):
        details = []
        if fields.get("mine_name"):
            details.append(f"矿山:{fields['mine_name']}")
        if fields.get("mineral_type"):
            details.append(f"矿产类型:{fields['mineral_type']}")
        if fields.get("mine_scale"):
            details.append(f"规模:{fields['mine_scale']}")
        if fields.get("mining_status"):
            details.append(f"采矿状态:{fields['mining_status']}")
        if fields.get("permit_expiry"):
            details.append(f"许可期限:{fields['permit_expiry']}")
        if fields.get("proved_reserves"):
            details.append(f"查明储量:{fields['proved_reserves']}吨")
        if fields.get("estimated_value"):
            details.append(f"评估值:¥{fields['estimated_value']}")
        if category == "勘探报告" and fields.get("coal_type"):
            details.append(f"煤种:{fields['coal_type']}")
        if details:
            logger.info("[DocParser][Step 4/4] 采矿权详情 | %s", " | ".join(details))
    
    # 执行进展（判决书/执行裁定）
    elif category in ("判决书", "执行裁定"):
        details = []
        if fields.get("case_number"):
            details.append(f"案号:{fields['case_number']}")
        if fields.get("defendant"):
            defendant_str = str(fields['defendant']) if isinstance(fields['defendant'], (list, tuple)) else fields['defendant']
            details.append(f"被执行人:{defendant_str[:50]}")
        if fields.get("judgment_amount"):
            details.append(f"判决金额:¥{fields['judgment_amount']}")
        if fields.get("execution_status"):
            details.append(f"执行状态:{fields['execution_status']}")
        if fields.get("enforcement_deadline"):
            details.append(f"执行期限:{fields['enforcement_deadline']}")
        if details:
            logger.info("[DocParser][Step 4/4] 执行进展 | %s", " | ".join(details))
    
    # 法院总对总（包含多资产类型）
    elif category == "法院总对总":
        details = []
        # 不动产
        if isinstance(fields.get("real_estate_hits"), list):
            for idx, asset in enumerate(fields["real_estate_hits"]):
                if isinstance(asset, dict):
                    re_details = []
                    if asset.get("location"):
                        re_details.append(asset['location'])
                    if asset.get("area_sqm"):
                        re_details.append(f"{asset['area_sqm']}m²")
                    if asset.get("status"):
                        re_details.append(asset['status'])
                    if re_details:
                        logger.info("[DocParser][Step 4/4] 不动产#%d | %s", idx+1, " | ".join(re_details))
        # 车辆
        if isinstance(fields.get("vehicle_hits"), list):
            for idx, vehicle in enumerate(fields["vehicle_hits"]):
                if isinstance(vehicle, dict):
                    v_details = []
                    if vehicle.get("plate_no"):
                        v_details.append(f"车牌:{vehicle['plate_no']}")
                    if vehicle.get("brand_model"):
                        v_details.append(f"品牌:{vehicle['brand_model']}")
                    if vehicle.get("status"):
                        v_details.append(f"状态:{vehicle['status']}")
                    if v_details:
                        logger.info("[DocParser][Step 4/4] 车辆#%d | %s", idx+1, " | ".join(v_details))
        # 银行存款
        if isinstance(fields.get("bank_deposits"), list):
            for idx, bank in enumerate(fields["bank_deposits"]):
                if isinstance(bank, dict):
                    b_details = []
                    if bank.get("bank_name"):
                        b_details.append(f"银行:{bank['bank_name']}")
                    if bank.get("balance"):
                        b_details.append(f"余额:¥{bank['balance']}")
                    if bank.get("frozen_amount"):
                        b_details.append(f"冻结:¥{bank['frozen_amount']}")
                    if b_details:
                        logger.info("[DocParser][Step 4/4] 存款#%d | %s", idx+1, " | ".join(b_details))
    
    # 财务报表
    elif category == "财务报表":
        details = []
        if fields.get("report_period"):
            details.append(f"报告期:{fields['report_period']}")
        if fields.get("revenue"):
            details.append(f"营收:¥{fields['revenue']}")
        if fields.get("net_profit"):
            details.append(f"净利润:¥{fields['net_profit']}")
        if fields.get("total_assets"):
            details.append(f"资产:¥{fields['total_assets']}")
        if details:
            logger.info("[DocParser][Step 4/4] 财务详情 | %s", " | ".join(details))
    
    # 贷款合同
    elif category == "贷款合同":
        details = []
        if fields.get("principal"):
            details.append(f"本金:¥{fields['principal']}")
        if fields.get("total_claim"):
            details.append(f"债权:¥{fields['total_claim']}")
        if fields.get("guarantee_type"):
            details.append(f"担保:{fields['guarantee_type']}")
        if fields.get("collateral_desc"):
            details.append(f"抵押物:{fields['collateral_desc'][:30]}")
        if details:
            logger.info("[DocParser][Step 4/4] 贷款详情 | %s", " | ".join(details))


def _ingest_one(case_id: int, debtor_id: int, category: str, fields: dict) -> dict:
    """调用 main.py 的 ingest_structured_fields 函数入库"""
    # 延迟导入避免循环引用
    from main import ingest_structured_fields, IngestFieldsReq
    req = IngestFieldsReq(case_id=case_id, debtor_id=debtor_id,
                          doc_category=category, fields=fields)
    try:
        return ingest_structured_fields(req)
    except HTTPException as e:
        return {"error": str(e.detail), "category": category}
    except Exception as e:
        logger.error("入库异常[%s]: %s", category, str(e))
        return {"error": str(e), "category": category}


# ============================================================================
# 自动建案 + 企查查穿透（当不传 case_id 时）
# ============================================================================

def _auto_create_case(debtor_name: str, case_name: Optional[str] = None) -> dict:
    """自动建案，返回 {case_id, debtor_id}；若同名债务人已存在则复用最新案件"""
    from main import _find_existing_case

    existing = _find_existing_case(debtor_name)
    if existing:
        logger.info("[DocParser] 复用已有案件 | debtor=%s | case_id=%d | debtor_id=%d",
                    debtor_name, existing["case_id"], existing["debtor_id"])
        return {"case_id": existing["case_id"], "debtor_id": existing["debtor_id"]}
    # 不存在则新建
    from main import create_case, CreateCaseReq
    if not case_name:
        case_name = f"{debtor_name} — 自动采集"
    req = CreateCaseReq(case_name=case_name, debtor_name=debtor_name)
    result = create_case(req)
    return {"case_id": result["case_id"], "debtor_id": result["debtor_id"]}


async def _auto_fetch_enterprise(case_id: int, company_name: str):
    """自动调用 fetchEnterprise 穿透关联企业"""
    from main import fetch_enterprise, FetchEnterpriseReq
    try:
        req = FetchEnterpriseReq(case_id=case_id, company_name=company_name, depth=2)
        return await fetch_enterprise(req)
    except Exception as e:
        logger.warning("[DocParser] 企查查穿透失败: %s", str(e))
        return {"error": str(e)}


# ============================================================================
# 主端点：POST /api/ingest/parse-document
# ============================================================================

class ParseDocumentReq(BaseModel):
    # 方式A：传 case_id + debtor_id（已有案件，追加入库）
    case_id: Optional[int] = Field(default=None, description="已有案件ID；上传卷宗时应优先传入。")
    debtor_id: Optional[int] = Field(
        default=None,
        description="已有债务人ID；多债务人案件必传，并校验必须属于 case_id。",
    )
    # 方式B：传 debtor_name（自动建案 + 企查查 + 提取入库，一站式）
    debtor_name: Optional[str] = Field(
        default=None,
        description="显式确认的债务人名称；已有案件中仅用于一致性校验，不覆盖案件主数据。",
    )
    case_name: Optional[str] = None
    # 必填
    text: str                           # MinerU 输出的 markdown 文本
    source_filename: Optional[str] = None  # 原始文件名（可选，辅助分类）
    max_workers: int = 2                # LLM 并发提取数（限制并发避免429限流）


@router.post("/api/ingest/parse-document")
async def parse_document(req: ParseDocumentReq):
    t0 = time.time()

    # ── 最早期校验：文本为空直接拒绝，不创建任何资源 ──
    if not req.text or len(req.text.strip()) < 50:
        logger.warning("[DocParser] 请求拒绝: 文本内容过短 | 文件=%s | 长度=%d",
                       req.source_filename or "未知", len(req.text or ""))
        raise HTTPException(400, "文本内容过短，无法提取")

    # ── 参数校验与自动建案 ──
    if req.case_id:
        case_id = req.case_id
        debtor_id, debtor_name = _resolve_existing_case_debtor(
            case_id,
            req.debtor_id,
            req.debtor_name,
        )
        logger.info("[DocParser] 主数据债务人解析 | case_id=%d → debtor_id=%d", case_id, debtor_id)
        enterprise_task = None
    elif req.debtor_name:
        # 自动建案（或复用已有案件）
        case_info = _auto_create_case(req.debtor_name, req.case_name)
        case_id = case_info["case_id"]
        debtor_id = case_info["debtor_id"]
        debtor_name = req.debtor_name
        # 注：_auto_create_case 内部已打印"复用已有案件"或"新建案件"，此处仅记录结果
        logger.info("[DocParser] 案件准备完成 | case_id=%d | debtor=%s", case_id, debtor_name)
        # 异步发起企查查穿透（与提取并行）
        enterprise_task = asyncio.ensure_future(_auto_fetch_enterprise(case_id, debtor_name))
    else:
        raise HTTPException(400, "必须提供 case_id+debtor_id 或 debtor_name")

    # ── 幂等校验：同一 case_id + 文本内容hash 在10分钟内只允许一个解析进程 ──
    text_hash = hashlib.md5(req.text.encode()).hexdigest()[:16]
    idem_key = (case_id, text_hash)
    with _parse_lock:
        started_at = _parse_in_progress.get(idem_key)
        if started_at and (time.time() - started_at) < 600:
            cached = _parse_results.get(idem_key)
            if cached:
                logger.info("[DocParser] 重复请求命中缓存 | case_id=%d | text_hash=%s | 直接返回上次结果",
                            case_id, text_hash)
                return cached
            logger.warning("[DocParser] 重复解析请求已忽略 | case_id=%d | text_hash=%s | 已运行%.0fs",
                           case_id, text_hash, time.time() - started_at)
            return {
                "case_id": case_id,
                "debtor_id": debtor_id,
                "skipped": True,
                "reason": "该文件正在解析中，本次请求已忽略",
                "categories_found": [],
                "records_inserted": 0,
            }
        _parse_in_progress[idem_key] = time.time()

    logger.info("[DocParser] 开始解析 | case_id=%d | 文本长度=%d字 | 文件=%s",
                case_id, len(req.text), req.source_filename or "未知")

    try:
        # ── [Step 1/4] 分段 ──
        t_step = time.time()
        segments = _split_segments(req.text)
        logger.info("[DocParser][Step 1/4] 分段完成 | 共%d段 | 耗时%.1fs",
                    len(segments), time.time() - t_step)

        # ── [Step 2/4] 分类（合并同类段落）—— 并发执行，加速串行LLM分类瓶颈 ──
        logger.info("[DocParser][Step 2/4] 开始分类 | 共%d段 | 并发数=%d",
                    len(segments), min(req.max_workers, len(segments)))
        category_texts: dict[str, list[str]] = {}
        unclassified = []

        def _classify_one(seg):
            try:
                return seg, classify_segment(seg["text"], seg.get("context", ""))
            except Exception as _e:
                logger.warning("[DocParser] 分类异常 跳过该段: %s | 段落前50字: %.50s",
                               str(_e), seg["text"])
                return seg, []

        classify_workers = min(req.max_workers, len(segments))
        t_cls0 = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=classify_workers) as executor:
            # executor.map 保持原始顺序
            for seg, cats in executor.map(_classify_one, segments):
                if cats:
                    for cat in cats:
                        if cat not in category_texts:
                            category_texts[cat] = []
                        category_texts[cat].append(seg["text"])
                else:
                    unclassified.append(seg)

        logger.info("[DocParser][Step 2/4] 分类完成 | 命中类别=%s | 未分类段数=%d | 耗时%.1fs",
                    list(category_texts.keys()), len(unclassified), time.time() - t_cls0)

        # ── 第3步：逐类精准提取（并发） ──
        # 银行流水/财务报表等列表型数据不截断，改为分块提取再合并
        CHUNK_CATEGORIES = {"银行流水", "财务报表"}
        MAX_CHUNK = 10000          # 每块上限（给 LLM 留余量）
        MAX_SINGLE = 12000         # 非分块类别的截断上限

        extraction_tasks = []      # [(cat, text_or_chunks)]
        for cat, texts in category_texts.items():
            merged = "\n\n---\n\n".join(texts)
            if cat in CHUNK_CATEGORIES and len(merged) > MAX_CHUNK:
                # 分块：按段落切，每块不超过 MAX_CHUNK
                chunks, buf = [], ""
                for t in texts:
                    if buf and len(buf) + len(t) + 10 > MAX_CHUNK:
                        chunks.append(buf)
                        buf = t
                    else:
                        buf = (buf + "\n\n---\n\n" + t) if buf else t
                if buf:
                    chunks.append(buf)
                extraction_tasks.append((cat, chunks))
            else:
                if len(merged) > MAX_SINGLE:
                    merged = merged[:MAX_SINGLE] + "\n...(截断)"
                extraction_tasks.append((cat, merged))

        logger.info("[DocParser][Step 3/4] 开始提取 | 类别数=%d | 并发数=%d",
                    len(extraction_tasks), min(req.max_workers, max(len(extraction_tasks), 1)))
        extracted = {}

        def _do_extract(cat_text_pair):
            cat, text_or_chunks = cat_text_pair
            try:
                logger.info("[DocParser][Step 3/4] 提取[%s] 开始", cat)
                t_cat = time.time()
                if isinstance(text_or_chunks, list):
                    # 分块提取再合并
                    all_results = []
                    # 提取首块的前5行作为表头上下文（表名+列头）
                    first_lines = "\n".join(text_or_chunks[0].split("\n")[:5]) if text_or_chunks else ""
                    for i, chunk in enumerate(text_or_chunks):
                        logger.info("[DocParser][Step 3/4] 提取[%s] 块 %d/%d",
                                    cat, i + 1, len(text_or_chunks))
                        # 后续块前置表头上下文，让 LLM 理解列含义
                        if i > 0 and first_lines:
                            chunk = f"{first_lines}\n...\n{chunk}"
                        r = extract_fields_for_category(cat, chunk)
                        if r is None:
                            continue
                        if isinstance(r, list):
                            all_results.extend(r)
                        elif isinstance(r, dict):
                            # 银行流水：合并 transactions 数组
                            if cat == "银行流水" and "transactions" in r:
                                all_results.extend(r["transactions"])
                            else:
                                all_results.append(r)
                    # 重新组装
                    logger.info("[DocParser][Step 3/4] 提取[%s] 完成 | 记录数=%d | 耗时%.1fs",
                                cat, len(all_results), time.time() - t_cat)
                    if cat == "银行流水":
                        return (cat, {"transactions": all_results})
                    else:
                        return (cat, all_results if all_results else None)
                else:
                    result = extract_fields_for_category(cat, text_or_chunks)
                    logger.info("[DocParser][Step 3/4] 提取[%s] 完成 | 耗时%.1fs",
                                cat, time.time() - t_cat)
                    return (cat, result)
            except Exception as e:
                logger.error("[DocParser][Step 3/4] 提取异常[%s]: %s", cat, str(e))
                return (cat, None)

        # 并发提取
        workers = min(req.max_workers, len(extraction_tasks))
        if workers > 0:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                futures = executor.map(_do_extract, extraction_tasks)
                for cat, result in futures:
                    if result is not None:
                        extracted[cat] = result

        logger.info("[DocParser][Step 3/4] 提取全部完成 | 成功类别=%s", list(extracted.keys()))

        # ── [Step 4/4] 入库 ──
        logger.info("[DocParser][Step 4/4] 开始入库 | 类别数=%d", len(extracted))
        ingest_results = []
        for cat, fields_data in extracted.items():
            # 财务报表可能返回数组（多报告期）
            if isinstance(fields_data, list):
                for idx, item in enumerate(fields_data):
                    if isinstance(item, dict) and not item.get("parse_error"):
                        logger.info("[DocParser][Step 4/4] 入库[%s#%d/%d]", cat, idx+1, len(fields_data))
                        _log_asset_details(cat, item)  # 记录关键字段详情
                        r = _ingest_one(case_id, debtor_id, cat, item)
                        ingest_results.append({"category": cat, "result": r})
            elif isinstance(fields_data, dict) and not fields_data.get("parse_error"):
                logger.info("[DocParser][Step 4/4] 入库[%s]", cat)
                _log_asset_details(cat, fields_data)  # 记录关键字段详情
                r = _ingest_one(case_id, debtor_id, cat, fields_data)
                ingest_results.append({"category": cat, "result": r})

        # 等待企查查穿透完成（如果有）
        enterprise_result = None
        if enterprise_task is not None:
            try:
                enterprise_result = await enterprise_task
            except Exception as e:
                logger.warning("[DocParser] 企查查等待失败: %s", str(e))

        elapsed_ms = int((time.time() - t0) * 1000)
        success_count = sum(1 for r in ingest_results if "error" not in r.get("result", {}))
        categories_found = list(extracted.keys())

        logger.info("[DocParser][Step 4/4] 入库完成 | 入库记录=%d", success_count)
        logger.info("[DocParser] ✓ 全流程完成 | 耗时%dms | 类别=%d | 入库记录=%d",
                    elapsed_ms, len(categories_found), success_count)

        result = {
            "case_id": case_id,
            "debtor_id": debtor_id,
            "categories_found": categories_found,
            "total_segments": len(segments),
            "unclassified_segments": len(unclassified),
            "records_inserted": success_count,
            "elapsed_ms": elapsed_ms,
            "details": ingest_results,
            "source_filename": req.source_filename,
            "enterprise": enterprise_result,
        }
        # 缓存成功结果，供重复请求直接返回；顺便清理过期条目
        with _parse_lock:
            _parse_results[idem_key] = result
            now = time.time()
            expired = [k for k, t in _parse_in_progress.items() if now - t >= 600]
            for k in expired:
                _parse_in_progress.pop(k, None)
                _parse_results.pop(k, None)
        return result

    except Exception:
        # 解析异常时释放锁，允许后续请求重试
        with _parse_lock:
            _parse_in_progress.pop(idem_key, None)
        raise
    # 成功完成：不释放锁，让10分钟TTL自然过期，防止Dify重试导致重复解析

#!/usr/bin/env python3
"""
诊断脚本：分析PDF解析过程中的数据提取问题
用法（backend 目录）：python scripts/domain_engine/diagnose_pdf_extraction.py <case_id>
"""

import sys
import json
from ai_hunter.domain_engine import db

def diagnose_case(case_id: int):
    """诊断指定案件的数据提取情况"""
    
    print(f"\n{'='*80}")
    print(f"诊断案件 case_id={case_id} 的数据提取情况")
    print(f"{'='*80}\n")
    
    # 1. 查询案件基本信息
    case = db.query_one("SELECT * FROM cases WHERE case_id=%s", (case_id,))
    if not case:
        print(f"❌ 案件不存在: case_id={case_id}")
        return
    
    print(f"案件名称: {case['case_name']}")
    print(f"案件类型: {case['case_type']}")
    print(f"创建时间: {case['created_at']}\n")
    
    # 2. 查询债务人信息
    debtors = db.query("SELECT * FROM debtors WHERE case_id=%s", (case_id,))
    print(f"债务人数量: {len(debtors)}")
    for d in debtors:
        print(f"  - {d['entity_name']} (debtor_id={d['debtor_id']})")
    print()
    
    # 3. 查询各表的数据量
    tables = {
        "claims": "贷款合同/债权",
        "legal_documents": "判决书/裁定书",
        "financial_snapshots": "财务报表",
        "real_estate_evaluations": "不动产权证",
        "mining_evaluations": "采矿许可证/勘探报告",
        "guarantors": "担保合同",
        "transaction_signatures": "银行流水",
        "contacts": "煤矿重整方案",
        "risk_profiles": "律师调查报告",
        "bank_accounts": "法院总对总",
        "hidden_assets": "隐藏资产",
    }
    
    print("数据入库统计:")
    print(f"{'表名':<30} {'记录数':>10} {'说明'}")
    print("-" * 80)
    
    total_records = 0
    empty_tables = []
    
    for table, desc in tables.items():
        count_row = db.query_one(f"SELECT COUNT(*) as cnt FROM {table} WHERE case_id=%s", (case_id,))
        count = count_row['cnt'] if count_row else 0
        total_records += count
        
        status = "✅" if count > 0 else "⚠️ "
        print(f"{status} {table:<28} {count:>10} {desc}")
        
        if count == 0:
            empty_tables.append((table, desc))
    
    print("-" * 80)
    print(f"总记录数: {total_records}\n")
    
    # 4. 分析空表
    if empty_tables:
        print("⚠️  以下表没有数据（可能是文档中没有相关内容，或提取失败）:")
        for table, desc in empty_tables:
            print(f"  - {table} ({desc})")
        print()
    
    # 5. 查询API调用日志
    api_logs = db.query("""
        SELECT request_id, endpoint_name, response_status, duration_ms, 
               created_at, error_message,
               substring(response_body, 1, 500) as response_preview
        FROM api_call_logs 
        WHERE case_id=%s AND endpoint_name='/api/ingest/parse-document'
        ORDER BY created_at DESC
        LIMIT 5
    """, (case_id,))
    
    print(f"最近的parse-document调用记录 (共{len(api_logs)}次):")
    for log in api_logs:
        status_icon = "✅" if log['response_status'] == 200 else "❌"
        print(f"\n{status_icon} {log['created_at']} | 耗时{log['duration_ms']}ms | 状态{log['response_status']}")
        
        if log['error_message']:
            print(f"  错误: {log['error_message'][:200]}")
        
        # 解析响应预览
        try:
            resp = json.loads(log['response_preview']) if log['response_preview'] else {}
            if 'categories_found' in resp:
                print(f"  分类: {', '.join(resp['categories_found'])}")
            if 'records_inserted' in resp:
                print(f"  入库记录数: {resp['records_inserted']}")
        except:
            pass
    
    print()
    
    # 6. 检查mining_evaluations的详细数据
    mining_data = db.query("""
        SELECT mine_name, mineral_type, production_scale, mining_status,
               permit_expiry, proved_reserves, estimated_value,
               env_approval_status, safety_permit_status,
               created_at
        FROM mining_evaluations 
        WHERE case_id=%s
        ORDER BY created_at DESC
    """, (case_id,))
    
    if mining_data:
        print("采矿权数据详情:")
        for idx, m in enumerate(mining_data, 1):
            print(f"\n  [{idx}] {m['mine_name'] or '(未命名)'}")
            print(f"      矿种: {m['mineral_type'] or '未知'}")
            print(f"      规模: {m['production_scale'] or '未知'}万吨/年")
            print(f"      状态: {m['mining_status'] or '未知'}")
            print(f"      许可到期: {m['permit_expiry'] or '未知'}")
            print(f"      储量: {m['proved_reserves'] or '未知'}万吨")
            print(f"      估值: {m['estimated_value'] or '未知'}元")
            print(f"      环评: {m['env_approval_status'] or '未知'}")
            print(f"      安全许可: {m['safety_permit_status'] or '未知'}")
    
    # 7. 检查real_estate_evaluations的详细数据
    re_data = db.query("""
        SELECT property_address, property_owner, real_estate_cert_no,
               total_building_area, land_use_area, property_usage,
               mortgage_status, seal_status, gross_value, net_value,
               created_at
        FROM real_estate_evaluations 
        WHERE case_id=%s
        ORDER BY created_at DESC
    """, (case_id,))
    
    if re_data:
        print("\n不动产数据详情:")
        for idx, r in enumerate(re_data, 1):
            print(f"\n  [{idx}] {r['property_address'] or '(未命名)'}")
            print(f"      产权人: {r['property_owner'] or '未知'}")
            print(f"      权证号: {r['real_estate_cert_no'] or '未知'}")
            print(f"      建筑面积: {r['total_building_area'] or '未知'}㎡")
            print(f"      土地面积: {r['land_use_area'] or '未知'}㎡")
            print(f"      用途: {r['property_usage'] or '未知'}")
            print(f"      抵押: {r['mortgage_status'] or '未知'}")
            print(f"      查封: {r['seal_status'] or '未知'}")
            print(f"      评估值: {r['gross_value'] or '未知'}元")
            print(f"      净值: {r['net_value'] or '未知'}元")
    
    # 8. 检查financial_snapshots的详细数据
    fs_data = db.query("""
        SELECT report_period, report_type, revenue, operating_cost, net_profit,
               total_assets, total_liabilities, other_receivables, prepayments,
               created_at
        FROM financial_snapshots 
        WHERE case_id=%s
        ORDER BY report_period DESC
    """, (case_id,))
    
    if fs_data:
        print("\n财务报表数据详情:")
        for idx, f in enumerate(fs_data, 1):
            print(f"\n  [{idx}] {f['report_period']} ({f['report_type'] or '未知类型'})")
            print(f"      营业收入: {f['revenue'] or 0:,.2f}元")
            print(f"      营业成本: {f['operating_cost'] or 0:,.2f}元")
            print(f"      净利润: {f['net_profit'] or 0:,.2f}元")
            print(f"      资产总额: {f['total_assets'] or 0:,.2f}元")
            print(f"      负债总额: {f['total_liabilities'] or 0:,.2f}元")
            print(f"      其他应收款: {f['other_receivables'] or 0:,.2f}元")
            print(f"      预付账款: {f['prepayments'] or 0:,.2f}元")
    
    print(f"\n{'='*80}")
    print("诊断完成")
    print(f"{'='*80}\n")
    
    # 9. 给出建议
    print("💡 建议:")
    if total_records < 5:
        print("  ⚠️  数据量较少，可能是：")
        print("     1. PDF文档内容不完整")
        print("     2. LLM提取失败（返回None或空字典）")
        print("     3. 文档格式不符合预期（如表格被截断）")
        print("\n  建议操作：")
        print("     - 查看日志文件 logs/api.2026-04-15.log 搜索 '无有效字段可写入'")
        print("     - 检查LLM提取的原始响应（需要增强日志）")
        print("     - 手动检查PDF转markdown的质量")
    
    if not mining_data and not re_data:
        print("  ⚠️  核心资产数据（采矿权、不动产）为空")
        print("     这是最关键的数据，建议：")
        print("     1. 确认PDF中是否有相关章节")
        print("     2. 检查分段是否将表格切断")
        print("     3. 尝试手动提取测试（运行 _test_extraction.py）")
    
    if not fs_data:
        print("  ℹ️  财务报表数据为空")
        print("     法律尽职调查报告可能只有财务状况描述，没有完整报表")
        print("     这是正常的，可以忽略")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python _diagnose_pdf_extraction.py <case_id>")
        print("\n示例:")
        print("  python _diagnose_pdf_extraction.py 116")
        sys.exit(1)
    
    try:
        case_id = int(sys.argv[1])
        diagnose_case(case_id)
    except ValueError:
        print(f"❌ 无效的case_id: {sys.argv[1]}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 诊断失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

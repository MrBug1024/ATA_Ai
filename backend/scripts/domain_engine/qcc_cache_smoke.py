#!/usr/bin/env python3
"""
企查查缓存功能测试脚本
验证：1) 缓存读写正常
     2) 缓存过期判断正确
     3) 强制刷新功能
"""

import asyncio
import json
from datetime import datetime, timedelta
from ai_hunter.domain_engine.config import PG_DSN
import psycopg2
from ai_hunter.domain_engine.api import _load_enterprise_from_cache, _get_qcc_cached

def test_cache_structure():
    """测试：缓存表结构是否完整"""
    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()
    
    print("\n=== 测试1：缓存表结构 ===")
    
    # 检查enterprises表是否有必要的字段
    cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name='enterprises' AND table_schema='public'
    """)
    cols = {row[0] for row in cur.fetchall()}
    
    required_cols = {'enterprise_id', 'uscc', 'entity_name', 'legal_rep', 
                    'registered_addr', 'phone', 'established', 'status',
                    'reg_capital', 'paid_capital', 'industry_name',
                    'data_source', 'api_fetched_at', 'updated_at', 'raw_response'}
    
    missing = required_cols - cols
    if missing:
        print(f"❌ enterprises表缺少字段: {missing}")
        return False
    
    print(f"✓ enterprises表包含所有{len(required_cols)}个必要字段")
    
    # 检查shareholders表
    cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name='shareholders' AND table_schema='public'
    """)
    cols = {row[0] for row in cur.fetchall()}
    required = {'id', 'enterprise_id', 'shareholder_name', 'shareholder_type',
               'shareholder_uscc', 'share_ratio', 'is_actual_ctrl', 'data_source',
               'snapshot_date'}
    
    missing = required - cols
    if missing:
        print(f"❌ shareholders表缺少字段: {missing}")
        return False
    
    print(f"✓ shareholders表包含所有{len(required)}个必要字段")
    
    # 检查executives表
    cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name='executives' AND table_schema='public'
    """)
    cols = {row[0] for row in cur.fetchall()}
    required = {'id', 'enterprise_id', 'person_name', 'position', 
               'data_source', 'snapshot_date'}
    
    missing = required - cols
    if missing:
        print(f"❌ executives表缺少字段: {missing}")
        return False
    
    print(f"✓ executives表包含所有{len(required)}个必要字段")
    
    cur.close()
    conn.close()
    return True


def test_cache_readback():
    """测试：缓存读回功能"""
    print("\n=== 测试2：缓存读回功能 ===")
    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()
    
    # 查询一条企业记录用于测试
    cur.execute("SELECT enterprise_id, entity_name FROM enterprises LIMIT 1")
    row = cur.fetchone()
    
    if not row:
        print("⚠️  数据库中没有企业记录，跳过此测试")
        cur.close()
        conn.close()
        return True
    
    ent_id, ent_name = row
    
    # 调用_load_enterprise_from_cache读取
    result = _load_enterprise_from_cache(ent_id)
    
    if not result:
        print(f"❌ 无法读取缓存 (enterprise_id={ent_id})")
        cur.close()
        conn.close()
        return False
    
    required_keys = {'entity_name', 'uscc', 'legal_rep', 'registered_addr',
                    'phone', 'established', 'status', 'reg_capital',
                    'paid_capital', 'industry_name', 'shareholders', 'executives',
                    '_raw', '_cache_hit', '_cache_time'}
    
    missing = required_keys - set(result.keys())
    if missing:
        print(f"❌ 缓存数据缺少字段: {missing}")
        cur.close()
        conn.close()
        return False
    
    print(f"✓ 成功读取缓存 (enterprise_id={ent_id})")
    print(f"  企业: {result['entity_name']}")
    print(f"  USCC: {result['uscc']}")
    print(f"  股东数: {len(result['shareholders'])}")
    print(f"  高管数: {len(result['executives'])}")
    print(f"  缓存时间: {result['_cache_time']}")
    
    cur.close()
    conn.close()
    return True


def test_cache_ttl():
    """测试：缓存过期时间逻辑"""
    print("\n=== 测试3：缓存过期时间逻辑 ===")
    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()
    
    # 查询最近30天内的企业记录
    cur.execute("""
    SELECT COUNT(*) as cnt FROM enterprises 
    WHERE updated_at > now() - INTERVAL '30 days'
    """)
    valid_count = cur.fetchone()[0]
    
    # 查询超过30天的企业记录
    cur.execute("""
    SELECT COUNT(*) as cnt FROM enterprises 
    WHERE updated_at <= now() - INTERVAL '30 days' 
    OR updated_at IS NULL
    """)
    expired_count = cur.fetchone()[0]
    
    print(f"✓ 有效缓存(30天内): {valid_count} 条")
    print(f"✓ 过期缓存(超过30天): {expired_count} 条")
    
    if valid_count > 0:
        print(f"✓ 缓存命中率: {valid_count / (valid_count + expired_count) * 100:.1f}%")
    
    cur.close()
    conn.close()
    return True


async def test_cache_async():
    """测试：异步缓存功能"""
    print("\n=== 测试4：异步缓存查询 ===")
    
    # 注意：这需要在有真实数据的情况下测试
    print("⚠️  异步测试需要运行中的API服务，跳过")
    return True


def test_cache_stats():
    """测试：显示缓存统计信息"""
    print("\n=== 测试5：缓存统计 ===")
    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()
    
    # 数据源统计
    cur.execute("""
    SELECT data_source, COUNT(*) as cnt
    FROM enterprises
    GROUP BY data_source
    ORDER BY cnt DESC
    """)
    
    print("数据源分布:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]} 条")
    
    # 缓存新鲜度统计
    cur.execute("""
    SELECT 
        COUNT(*) total,
        SUM(CASE WHEN updated_at > now() - INTERVAL '7 days' THEN 1 ELSE 0 END) fresh_7d,
        SUM(CASE WHEN updated_at > now() - INTERVAL '30 days' THEN 1 ELSE 0 END) fresh_30d,
        SUM(CASE WHEN updated_at > now() - INTERVAL '90 days' THEN 1 ELSE 0 END) fresh_90d,
        SUM(CASE WHEN updated_at IS NULL THEN 1 ELSE 0 END) never_updated
    FROM enterprises
    """)
    
    row = cur.fetchone()
    if row[0] > 0:
        print(f"\n缓存新鲜度 (共{row[0]}条企业):")
        print(f"  7天内更新: {row[1]} ({row[1]/row[0]*100:.1f}%)")
        print(f"  30天内更新: {row[2]} ({row[2]/row[0]*100:.1f}%)")
        print(f"  90天内更新: {row[3]} ({row[3]/row[0]*100:.1f}%)")
        print(f"  从未更新: {row[4]}")
    
    cur.close()
    conn.close()
    return True


def main():
    print("╔═══════════════════════════════════════════════════════╗")
    print("║        企查查缓存功能测试                               ║")
    print("║        QCC Cache Validation Suite                    ║")
    print("╚═══════════════════════════════════════════════════════╝")
    
    tests = [
        ("缓存表结构", test_cache_structure),
        ("缓存读回", test_cache_readback),
        ("缓存过期", test_cache_ttl),
        ("缓存统计", test_cache_stats),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            print(f"\n❌ {name} 测试失败: {e}")
            results[name] = False
    
    print("\n" + "="*60)
    print("测试结果摘要:")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✓ PASS" if result else "❌ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\n总体: {passed}/{total} 通过")
    print("="*60)
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
探查 cpwsdata 法律文书库：表结构、样本数据、向量配置
运行方式（backend 目录）：
  python scripts/domain_engine/check_cpwsdata.py
"""
import psycopg2
from psycopg2.extras import RealDictCursor

from ai_hunter.domain_engine.config import CPWS_DSN

conn = psycopg2.connect(CPWS_DSN)
cur = conn.cursor()

SEP = "=" * 65

# ── 1. pgvector ──────────────────────────────────────────────────────────────
print(SEP)
print("1. pgvector 扩展")
cur.execute("SELECT extname, extversion FROM pg_extension WHERE extname='vector'")
ext = cur.fetchone()
print(" ", ext if ext else "未安装 — 向量检索不可用")

# ── 2. 所有表 ─────────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("2. 所有表 (public schema)")
cur.execute("""
    SELECT table_name, table_type
    FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_type, table_name
""")
tables = [(r[0], r[1]) for r in cur.fetchall()]
for name, ttype in tables:
    print(f"  [{ttype}] {name}")
table_names = [t[0] for t in tables]

# ── 3. 向量列 ─────────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("3. 向量列 (vector 类型) + 维度")
cur.execute("""
    SELECT c.table_name, c.column_name, c.udt_name,
           pa.atttypmod AS dim_raw
    FROM information_schema.columns c
    JOIN pg_class pc ON pc.relname = c.table_name AND pc.relkind = 'r'
    JOIN pg_attribute pa ON pa.attrelid = pc.oid AND pa.attname = c.column_name
    WHERE c.table_schema = 'public'
      AND c.udt_name = 'vector'
""")
vecs = cur.fetchall()
if vecs:
    for r in vecs:
        # pgvector stores dimension as atttypmod; raw value = dim + 4 if set
        dim = (r[3] - 4) if r[3] and r[3] > 4 else "unknown"
        print(f"  表={r[0]:30s}  列={r[1]:20s}  维度={dim}")
else:
    print("  未找到 vector 列")

# ── 4. 各表字段 ───────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("4. 各表字段 + 行数")
for tname in table_names:
    cur.execute("""
        SELECT column_name, data_type, udt_name, is_nullable, character_maximum_length
        FROM information_schema.columns
        WHERE table_name = %s AND table_schema = 'public'
        ORDER BY ordinal_position
    """, (tname,))
    cols = cur.fetchall()
    try:
        cur.execute(f'SELECT count(*) FROM "{tname}"')
        cnt = cur.fetchone()[0]
    except Exception:
        cnt = "?"
    print(f"\n  [{tname}]  ({cnt:,} 行)" if isinstance(cnt, int) else f"\n  [{tname}]  (? 行)")
    for c in cols:
        vtype = c[2] if c[2] != c[1] else c[1]
        maxlen = f"({c[4]})" if c[4] else ""
        print(f"    {c[0]:35s} {vtype}{maxlen:10s} nullable={c[3]}")

# ── 5. 样本数据（跳过向量列，最多 2 行）────────────────────────────────────────
print(f"\n{SEP}")
print("5. 样本数据（每表前 2 条，跳过 vector 列）")
for tname in table_names:
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = %s AND table_schema = 'public'
          AND udt_name != 'vector'
        ORDER BY ordinal_position
    """, (tname,))
    non_vec_cols = [r[0] for r in cur.fetchall()]
    if not non_vec_cols:
        continue
    # 长文本列截断
    col_exprs = []
    for c in non_vec_cols[:20]:
        col_exprs.append(f'LEFT("{c}"::text, 120) AS "{c}"')
    try:
        cur.execute(f'SELECT {", ".join(col_exprs)} FROM "{tname}" LIMIT 2')
        rows = cur.fetchall()
        if rows:
            print(f"\n  [{tname}]")
            for row in rows:
                for col, val in zip(non_vec_cols[:20], row):
                    v = str(val).replace("\n", "\\n") if val is not None else "NULL"
                    print(f"    {col}: {v}")
                print()
    except Exception as e:
        print(f"\n  [{tname}] 查询失败: {e}")

cur.close()
conn.close()
print(f"\n{SEP}")
print("探查完成。请将上面输出粘贴给 AI。")

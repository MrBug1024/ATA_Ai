"""检查科目余额表数据。"""
from ai_hunter.annual_audit.storage import mysql_connection
from ai_hunter.app.settings import get_settings

settings = get_settings()
with mysql_connection(settings) as conn:
    with conn.cursor() as cur:
        # 查看科目余额表前20行
        cur.execute("""
            SELECT account_code, account_name, opening_debit, opening_credit,
                   period_debit, period_credit, closing_debit, closing_credit
            FROM annual_account_balance
            WHERE engagement_id = 1
            ORDER BY account_code
            LIMIT 30
        """)
        rows = cur.fetchall()
        print("=== 科目余额表 (前30行) ===")
        for r in rows:
            print(f"  {r['account_code']} | {r['account_name']} | 期初借:{r['opening_debit']} 贷:{r['opening_credit']} | 本期借:{r['period_debit']} 贷:{r['period_credit']} | 期末借:{r['closing_debit']} 贷:{r['closing_credit']}")

        # 查看银行流水汇总
        cur.execute("""
            SELECT COUNT(*) AS cnt, SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS inflow,
                   SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) AS outflow
            FROM annual_bank_transaction
            WHERE engagement_id = 1
        """)
        bank = cur.fetchone()
        print(f"\n=== 银行流水汇总 ===")
        print(f"  行数: {bank['cnt']}, 流入: {bank['inflow']}, 流出: {bank['outflow']}")

        # 查看应收账款汇总
        cur.execute("""
            SELECT COUNT(*) AS cnt, SUM(balance) AS total_balance
            FROM annual_receivable_item
            WHERE engagement_id = 1
        """)
        recv = cur.fetchone()
        print(f"\n=== 应收账款汇总 ===")
        print(f"  行数: {recv['cnt']}, 余额合计: {recv['total_balance']}")

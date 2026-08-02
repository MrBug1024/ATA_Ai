"""内网验证：Kimi(faker 代理) 连通性 + 八段按 provider 分流 + 跨 provider 并行提速。

仅在能访问 faker-model.rhzy.ai（内网）的机器上运行；外部 dev 会被 WAF 拦（403）。
用法（仓库根目录，已配好 .env）：
    python3 scripts/verify_kimi_route.py
    python3 scripts/verify_kimi_route.py 116        # 指定 case_id（默认 116）

不是 pytest（scripts/ 不被收集）。
"""

import asyncio
import sys
import time
from pathlib import Path


def _read_env(prefix: str) -> dict:
    out = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def step1_kimi_connectivity():
    """① Kimi 是否真连通出活。"""
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    kv = _read_env("KIMI_")
    print(f"[1] Kimi 连通性  base={kv.get('KIMI_BASE_URL')} model={kv.get('KIMI_MODEL_REPORT_A')}")
    llm = ChatOpenAI(api_key=kv["KIMI_API_KEY"], base_url=kv["KIMI_BASE_URL"],
                     model=kv["KIMI_MODEL_REPORT_A"], temperature=0.3)
    t = time.time()
    r = llm.invoke([HumanMessage(content="用一句话(30字内)说明不良资产重整盘活的关键。")])
    print(f"    ✅ kimi 出活 {time.time() - t:.1f}s: {str(r.content)[:80]}")


def step2_kimi_concurrency():
    """② Kimi 端点并发能力（4 路并发长生成 vs 顺序）。"""
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    kv = _read_env("KIMI_")
    llm = ChatOpenAI(api_key=kv["KIMI_API_KEY"], base_url=kv["KIMI_BASE_URL"],
                     model=kv["KIMI_MODEL_REPORT_A"], temperature=0.3)
    LONG = [HumanMessage(content="写约1200字不良资产处置策略，分4小节。")]

    async def one():
        r = await llm.ainvoke(LONG)
        return len(str(r.content))

    async def main():
        t = time.time()
        res = await asyncio.gather(*[one() for _ in range(4)], return_exceptions=True)
        c = time.time() - t
        ok = [x for x in res if isinstance(x, int)]
        errs = [str(x)[:80] for x in res if not isinstance(x, int)]
        print(f"[2] Kimi 4 路并发长生成 {c:.1f}s 成功{len(ok)}/4" + (f" 错误{errs}" if errs else ""))

    asyncio.run(main())


def step3_full_audit_routing(case_id: int):
    """③ 八段按 provider 分流的全量审计：异步跑，确认完成 + 是否触发 kimi→minimax 回退。"""
    import logging
    logging.basicConfig(level=logging.WARNING)  # 段回退会打 WARNING: section_X provider=kimi failed ...
    from ai_hunter.app.graph.context_loader import resolve_final_report
    from ai_hunter.app.subgraphs.full_audit_graph import build_full_audit_graph
    g = build_full_audit_graph()
    inp = {"thread_id": f"verify-kimi-{case_id}", "query": f"对案件{case_id}出具完整审计报告", "current_case_id": case_id}

    async def main():
        t = time.time()
        res = await g.ainvoke(inp)
        return int(time.time() - t), res

    dur, res = asyncio.run(main())
    rep = resolve_final_report(res)
    print(f"[3] 按段分流全量审计 {dur}s 报告{len(rep)}字 段数={len(res.get('report_section_refs', {}))} "
          f"tasks={len(res.get('extracted_tasks', []))} json泄漏={'```json' in rep}")
    print("    若上方无 'section_X provider=kimi failed' 警告，则核心段真用了 kimi（未回退）。")


if __name__ == "__main__":
    case_id = int(sys.argv[1]) if len(sys.argv) > 1 else 116
    step1_kimi_connectivity()
    step2_kimi_concurrency()
    step3_full_audit_routing(case_id)

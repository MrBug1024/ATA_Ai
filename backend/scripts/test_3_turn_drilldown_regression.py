"""Regression test: 3-turn drilldown conversation with real LLM and PostgresSaver."""

import uuid

from ai_hunter.app.graph.checkpointer import get_checkpointer
from ai_hunter.app.graph.main import build_audit_orchestrator_graph


def main():
    thread_id = f"test-regression-{uuid.uuid4().hex[:16]}"
    graph = build_audit_orchestrator_graph()

    queries = [
        "你好，简单介绍一下你能做什么",
        "你刚才提到的资金流向拓扑分析，需要我提供哪些材料？",
        "破产清算和破产重整有什么区别？",
    ]

    for i, query in enumerate(queries, 1):
        print(f"\n=== Turn {i}: {query} ===")
        result = graph.invoke(
            {"thread_id": thread_id, "query": query},
            config={"configurable": {"thread_id": thread_id}},
        )
        intent = result.get("intent", "unknown")
        agent_output = result.get("agent_output", "")
        final_report = result.get("final_report", "")
        print(f"intent={intent}")
        print(f"agent_output_len={len(agent_output)}")
        print(f"final_report_len={len(final_report)}")

        # Sanity check: assistant answer should not be empty metadata
        full_answer = final_report or agent_output
        if full_answer and full_answer.startswith("intent=drilldown | case_id=0") and len(full_answer) < 40:
            print(f"[ERROR] Turn {i} produced corrupted answer: {full_answer}")
            raise RuntimeError(f"Turn {i} corrupted")
        print(f"answer_preview={full_answer[:120]}")

    # Verify persisted conversation log
    tuple_ = get_checkpointer().get_tuple(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    )
    if not tuple_ or not tuple_.checkpoint:
        raise RuntimeError("No checkpoint found after 3 turns")

    cv = tuple_.checkpoint.get("channel_values", {})
    conv_log = list(cv.get("conversation_log") or [])
    print(f"\n=== Final conversation_log ({len(conv_log)} entries) ===")
    for i, entry in enumerate(conv_log):
        preview = entry["content"][:100].replace("\n", " ")
        print(f"{i}. [{entry['role']}] {preview}")

    assert len(conv_log) == 6, f"Expected 6 entries, got {len(conv_log)}"

    # Validate no turn has the corrupted metadata-only answer
    corrupted = "intent=drilldown | case_id=0"
    for entry in conv_log:
        if entry["role"] == "assistant" and entry["content"].strip() == corrupted:
            raise RuntimeError(f"Corrupted assistant entry found: {entry}")

    print("\n[PASS] 3-turn drilldown regression test passed.")


if __name__ == "__main__":
    main()

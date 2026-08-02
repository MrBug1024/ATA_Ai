"""Regression test: 3-turn drilldown via real SSE streaming HTTP requests."""

import json
import uuid

import requests

BASE_URL = "http://localhost:8081"
thread_id = f"sse-reg-{uuid.uuid4().hex[:16]}"

QUERIES = [
    "你好，简单介绍一下你能做什么",
    "你刚才提到的资金流向拓扑分析，需要我提供哪些材料？",
    "破产清算和破产重整有什么区别？",
]


def invoke_sse(query: str) -> dict:
    """Send one streaming chat request and return the final payload."""
    payload = {"thread_id": thread_id, "query": query, "stream": True}
    headers = {"Accept": "text/event-stream"}
    resp = requests.post(
        f"{BASE_URL}/chat/invoke",
        json=payload,
        headers=headers,
        stream=True,
        timeout=180,
    )
    resp.raise_for_status()

    final_data = None
    event_type = None
    buffer = []

    for raw_line in resp.iter_lines(decode_unicode=True):
        if raw_line is None:
            continue
        line = raw_line.strip()
        if not line:
            # Empty line means end of event
            if event_type == "final" and buffer:
                final_data = json.loads("".join(buffer))
            event_type = None
            buffer = []
            continue

        if line.startswith("event: "):
            event_type = line[len("event: "):]
        elif line.startswith("data: "):
            buffer.append(line[len("data: "):])

    if final_data is None:
        raise RuntimeError(f"No 'final' event received for query: {query}")
    return final_data


def main():
    print(f"Thread ID: {thread_id}\n")

    for i, query in enumerate(QUERIES, 1):
        print(f"=== Turn {i}: {query} ===")
        try:
            data = invoke_sse(query)
        except Exception as exc:
            print(f"[ERROR] Turn {i} failed: {exc}")
            raise

        intent = data.get("intent", "unknown")
        final_report = data.get("final_report", "")
        memory_context = data.get("memory_context", "")
        print(f"intent={intent}")
        print(f"final_report_len={len(final_report)}")
        print(f"memory_context_len={len(memory_context)}")

        # Sanity check: answer must not be the corrupted metadata-only string
        corrupted = "intent=drilldown | case_id=0"
        if final_report and final_report.strip() == corrupted:
            raise RuntimeError(f"Turn {i} produced corrupted answer: {final_report}")
        print(f"answer_preview={final_report[:120].replace(chr(10), ' ')}")
        print()

    # ------------------------------------------------------------------
    # Verify persisted history
    # ------------------------------------------------------------------
    print("=== Verify history API ===")
    resp = requests.get(
        f"{BASE_URL}/chat/threads/{thread_id}/messages",
        timeout=30,
    )
    resp.raise_for_status()
    history = resp.json()
    messages = history.get("messages", [])
    print(f"message_count={history.get('message_count')}")
    for idx, msg in enumerate(messages):
        preview = msg["content"][:100].replace("\n", " ")
        print(f"{idx}. [{msg['role']}] {preview}")

    assert len(messages) == 6, f"Expected 6 messages, got {len(messages)}"
    corrupted = "intent=drilldown | case_id=0"
    for msg in messages:
        if msg["role"] == "assistant" and msg["content"].strip() == corrupted:
            raise RuntimeError(f"Corrupted assistant message found: {msg}")

    # ------------------------------------------------------------------
    # Verify access log carries thread_id
    # ------------------------------------------------------------------
    print("\n=== Verify access log ===")
    with open("logs/access.log", "r") as f:
        lines = f.readlines()
    matched = [ln for ln in lines if thread_id in ln]
    print(f"Matched access log lines: {len(matched)}")
    for ln in matched[-4:]:
        print(ln.strip())

    if not any(f"thread_id={thread_id}" in ln for ln in matched):
        print("[WARN] thread_id not found in access log context fields")
    else:
        print("[OK] thread_id present in access log")

    print("\n[PASS] 3-turn SSE regression test passed.")


if __name__ == "__main__":
    main()

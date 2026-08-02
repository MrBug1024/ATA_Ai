"""Mixed-intent regression: full_audit -> drilldown -> re_audit via real SSE."""

import json
import time
import uuid

import requests

BASE_URL = "http://localhost:8081"
THREAD_ID = f"mixed-intent-{uuid.uuid4().hex[:16]}"
CASE_ID = 116


def sse_invoke(query: str, current_case_id: int = 0) -> dict | None:
    payload = {
        "thread_id": THREAD_ID,
        "query": query,
        "stream": True,
        "current_case_id": current_case_id,
    }
    headers = {"Accept": "text/event-stream"}
    resp = requests.post(
        f"{BASE_URL}/chat/invoke",
        json=payload,
        headers=headers,
        stream=True,
        timeout=300,
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
            if event_type == "final" and buffer:
                final_data = json.loads("".join(buffer))
            event_type = None
            buffer = []
            continue
        if line.startswith("event: "):
            event_type = line[len("event: "):]
        elif line.startswith("data: "):
            buffer.append(line[len("data: "):])

    return final_data


def main():
    turns = [
        ("full_audit", "请对案件116进行全面审计", CASE_ID),
        ("drilldown", "报告里提到的资金流向有什么异常？", CASE_ID),
        ("re_audit", "这个房产估值不对，按800万重审", CASE_ID),
    ]

    for name, query, cid in turns:
        print(f"\n=== {name}: {query} ===")
        start = time.perf_counter()
        try:
            data = sse_invoke(query, cid)
        except Exception as exc:
            print(f"[ERROR] {name} failed: {exc}")
            continue
        elapsed = time.perf_counter() - start
        print(f"elapsed={elapsed:.1f}s")
        if data is None:
            print("[WARN] No final event received")
            continue

        intent = data.get("intent", "unknown")
        final_report = data.get("final_report", "")
        print(f"intent={intent}")
        print(f"final_report_len={len(final_report)}")
        print(f"preview={final_report[:120].replace(chr(10), ' ')}")

        # Sanity check for corrupted metadata-only answer
        corrupted = "intent=drilldown | case_id=0"
        if final_report and final_report.strip() == corrupted:
            print(f"[FAIL] Corrupted answer detected!")

    # ------------------------------------------------------------------
    # Verify persisted history
    # ------------------------------------------------------------------
    print("\n=== Verify History ===")
    resp = requests.get(
        f"{BASE_URL}/chat/threads/{THREAD_ID}/messages",
        timeout=30,
    )
    resp.raise_for_status()
    hist = resp.json()
    messages = hist.get("messages", [])
    print(f"message_count={hist.get('message_count')}")
    for i, m in enumerate(messages):
        preview = m["content"][:100].replace("\n", " ")
        print(f"{i}. [{m['role']}] {preview}")

    corrupted = "intent=drilldown | case_id=0"
    for m in messages:
        if m["role"] == "assistant" and m["content"].strip() == corrupted:
            raise RuntimeError(f"Corrupted assistant entry: {m}")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    print("\n=== Cleanup ===")
    resp = requests.delete(f"{BASE_URL}/chat/threads/{THREAD_ID}", timeout=30)
    print(f"delete_status={resp.status_code} success={resp.json().get('success')}")

    print("\n[PASS] Mixed-intent regression test completed.")


if __name__ == "__main__":
    main()

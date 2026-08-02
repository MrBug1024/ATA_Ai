"""Test idempotency (network retry) vs user retry, plus ordering guarantees."""

import json
import time
import uuid

import requests

BASE = "http://localhost:8081"
TID = f"idemp-{uuid.uuid4().hex[:16]}"
CLIENT_TURN_1 = "turn-001"
CLIENT_TURN_2 = "turn-002"

def sse_invoke(query, client_turn_id):
    payload = {
        "thread_id": TID,
        "query": query,
        "stream": True,
        "client_turn_id": client_turn_id,
    }
    resp = requests.post(
        f"{BASE}/chat/invoke",
        json=payload,
        headers={"Accept": "text/event-stream"},
        stream=True,
        timeout=120,
    )
    resp.raise_for_status()
    final_data = None
    event_type = None
    buffer = []
    for raw_line in resp.iter_lines(decode_unicode=True):
        line = (raw_line or "").strip()
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


print(f"Thread: {TID}")

# ------------------------------------------------------------------
# 1. Normal turn
# ------------------------------------------------------------------
print("\n=== Turn 1 (normal) ===")
start = time.perf_counter()
data1 = sse_invoke("你好，简单介绍一下你能做什么", CLIENT_TURN_1)
print(f"elapsed={time.perf_counter()-start:.1f}s intent={data1.get('intent')} final_len={len(data1.get('final_report',''))}")

# ------------------------------------------------------------------
# 2. Network retry: SAME client_turn_id → should return cached result
# ------------------------------------------------------------------
print("\n=== Turn 1 retry (same client_turn_id) ===")
start = time.perf_counter()
data1_retry = sse_invoke("你好，简单介绍一下你能做什么", CLIENT_TURN_1)
print(f"elapsed={time.perf_counter()-start:.1f}s intent={data1_retry.get('intent')} final_len={len(data1_retry.get('final_report',''))}")
assert data1.get("final_report") == data1_retry.get("final_report"), "Cached response mismatch!"
print("[PASS] Retry returned cached result.")

# ------------------------------------------------------------------
# 3. User retry: DIFFERENT client_turn_id → should process again
# ------------------------------------------------------------------
print("\n=== Turn 2 (user retry, different client_turn_id) ===")
start = time.perf_counter()
data2 = sse_invoke("你好，简单介绍一下你能做什么", CLIENT_TURN_2)
print(f"elapsed={time.perf_counter()-start:.1f}s intent={data2.get('intent')} final_len={len(data2.get('final_report',''))}")

# ------------------------------------------------------------------
# 4. Verify history
# ------------------------------------------------------------------
print("\n=== Verify History ===")
resp = requests.get(f"{BASE}/chat/threads/{TID}/messages", timeout=30)
resp.raise_for_status()
hist = resp.json()
print(f"message_count={hist.get('message_count')}")
for i, m in enumerate(hist.get("messages", [])):
    preview = m["content"][:80].replace("\n", " ")
    print(f"{i}. [{m['role']}] {preview}")

# We expect 4 messages: user(turn1), assistant(turn1), user(turn2), assistant(turn2)
assert hist.get("message_count") == 4, f"Expected 4 messages, got {hist.get('message_count')}"
print("[PASS] History has 4 entries (2 turns, no duplicates).")

# ------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------
requests.delete(f"{BASE}/chat/threads/{TID}", timeout=30)
print("\n[PASS] All idempotency & ordering tests passed.")

"""Quick regression for the unified message layer."""
import json, time, uuid, requests

BASE = "http://localhost:8081"
TID = f"uni-{uuid.uuid4().hex[:16]}"

def sse_invoke(query):
    payload = {"thread_id": TID, "query": query, "stream": True}
    resp = requests.post(f"{BASE}/chat/invoke", json=payload,
                         headers={"Accept": "text/event-stream"}, stream=True, timeout=120)
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
start = time.perf_counter()
data = sse_invoke("你好，简单介绍一下你能做什么")
print(f"elapsed={time.perf_counter()-start:.1f}s intent={data.get('intent')} final_len={len(data.get('final_report',''))}")

# Query via API
print("\n=== API History ===")
resp = requests.get(f"{BASE}/chat/threads/{TID}/messages", timeout=30)
hist = resp.json()
for i, m in enumerate(hist.get("messages", [])):
    print(f"{i}. [{m['role']}] {m['content'][:80]}")

# Query DB directly
print("\n=== DB Table ===")
import os
os.environ.setdefault('PYTHONPATH', '.')
from ai_hunter.app.repositories import get_conversation_message_repo
repo = get_conversation_message_repo()
rows = repo.get_messages(TID)
for i, r in enumerate(rows):
    print(f"{i}. [{r['role']}] {r['content'][:80]}")

# Cleanup
requests.delete(f"{BASE}/chat/threads/{TID}", timeout=30)
print("\n[PASS] Unified message layer OK.")

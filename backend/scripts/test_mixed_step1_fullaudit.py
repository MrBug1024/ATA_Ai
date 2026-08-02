"""Step 1: full_audit for case 116 via SSE."""
import json, time, uuid, requests

BASE = "http://localhost:8081"
TID = f"mixed-{uuid.uuid4().hex[:16]}"

def sse_invoke(query, case_id):
    payload = {"thread_id": TID, "query": query, "stream": True, "current_case_id": case_id}
    resp = requests.post(f"{BASE}/chat/invoke", json=payload,
                         headers={"Accept": "text/event-stream"}, stream=True, timeout=300)
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

print(f"Thread ID: {TID}")
start = time.perf_counter()
data = sse_invoke("请对案件116进行全面审计", 116)
print(f"elapsed={time.perf_counter()-start:.1f}s")
print(f"intent={data.get('intent')}")
print(f"final_report_len={len(data.get('final_report',''))}")
print(f"preview={data.get('final_report','')[:200].replace(chr(10),' ')}")
print(f"\nTID={TID}")

"""Step 2: drilldown on the same thread."""
import json, time, requests

BASE = "http://localhost:8081"
TID = "mixed-3de4e4fd4db94aae"

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

print(f"=== Turn 2: drilldown ===")
start = time.perf_counter()
data = sse_invoke("报告里提到的资金流向有什么异常？", 116)
print(f"elapsed={time.perf_counter()-start:.1f}s")
print(f"intent={data.get('intent')}")
print(f"final_report_len={len(data.get('final_report',''))}")
print(f"preview={data.get('final_report','')[:200].replace(chr(10),' ')}")

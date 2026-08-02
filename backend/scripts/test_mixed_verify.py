"""Verify history and cleanup."""
import requests

BASE = "http://localhost:8081"
TID = "mixed-3de4e4fd4db94aae"

# Verify history
print("=== GET /messages ===")
resp = requests.get(f"{BASE}/chat/threads/{TID}/messages", timeout=30)
resp.raise_for_status()
hist = resp.json()
print(f"message_count={hist.get('message_count')}")
for i, m in enumerate(hist.get("messages", [])):
    preview = m["content"][:120].replace("\n", " ")
    print(f"{i}. [{m['role']}] {preview}")

# Check for corrupted entries
corrupted = "intent=drilldown | case_id=0"
has_corrupted = False
for m in hist.get("messages", []):
    if m["role"] == "assistant" and m["content"].strip() == corrupted:
        has_corrupted = True
        print(f"[FAIL] Corrupted: {m['content']}")

if not has_corrupted:
    print("[OK] No corrupted metadata-only entries")

# Check access log thread_id
print("\n=== Access log ===")
with open("logs/access.log", "r") as f:
    lines = f.readlines()
matched = [ln for ln in lines if TID in ln]
for ln in matched[-6:]:
    print(ln.strip())

# Cleanup
print("\n=== DELETE ===")
resp = requests.delete(f"{BASE}/chat/threads/{TID}", timeout=30)
print(f"status={resp.status_code} success={resp.json().get('success')}")

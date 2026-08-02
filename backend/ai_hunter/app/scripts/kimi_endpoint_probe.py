"""Minimal Kimi endpoint probe for comparing /v1 and /anthropic behavior.

Usage:
    python -m ai_hunter.app.scripts.kimi_endpoint_probe
    python ai_hunter/app/scripts/kimi_endpoint_probe.py --key sk-xxx --model kimi-k2.6
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import ssl
import urllib.error
import urllib.request
from typing import Any

if __package__ in (None, ""):
    sys.path.append(str(pathlib.Path(__file__).resolve().parents[3]))
    from ai_hunter.app.settings import get_settings
else:
    from ..settings import get_settings


DEFAULT_OPENAI_MODEL = "kimi-k2.6"
DEFAULT_ANTHROPIC_MODEL = "kimi-k2.5"
DEFAULT_TIMEOUT_SECONDS = 30
BODY_PREVIEW_CHARS = 1200


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Kimi /v1 and /anthropic endpoints.")
    parser.add_argument("--key", default="", help="Override API key; defaults to KIMI_API_KEY from settings/env.")
    parser.add_argument(
        "--openai-model",
        default=DEFAULT_OPENAI_MODEL,
        help=f"Model for /v1/chat/completions. Default: {DEFAULT_OPENAI_MODEL}",
    )
    parser.add_argument(
        "--anthropic-model",
        default=DEFAULT_ANTHROPIC_MODEL,
        help=f"Model for /anthropic/v1/messages. Default: {DEFAULT_ANTHROPIC_MODEL}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"HTTP timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}",
    )
    parser.add_argument(
        "--openai-base-url",
        default="",
        help="Override OpenAI-compatible base URL, e.g. https://host/v1",
    )
    parser.add_argument(
        "--anthropic-base-url",
        default="",
        help="Override Anthropic-compatible base URL, e.g. https://host/anthropic",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification for debugging only.",
    )
    return parser.parse_args()


def _load_key(override: str) -> str:
    if override.strip():
        return override.strip()
    get_settings.cache_clear()
    return get_settings().kimi_api_key.strip()


def _post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
    insecure: bool,
) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url=url, data=data, headers=headers, method="POST")
    context = ssl._create_unverified_context() if insecure else None
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "ok": True,
                "status": response.status,
                "reason": getattr(response, "reason", ""),
                "headers": dict(response.headers.items()),
                "body": body,
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status": exc.code,
            "reason": getattr(exc, "reason", ""),
            "headers": dict(exc.headers.items()),
            "body": body,
        }
    except Exception as exc:  # pragma: no cover - network/tooling failure path
        return {
            "ok": False,
            "status": None,
            "reason": type(exc).__name__,
            "headers": {},
            "body": str(exc),
        }


def _mask_key(value: str) -> str:
    normalized = value.strip()
    if len(normalized) <= 10:
        return normalized[:2] + "***" if normalized else ""
    return f"{normalized[:6]}***{normalized[-4:]}"


def _preview(value: str) -> str:
    text = value.strip()
    if len(text) <= BODY_PREVIEW_CHARS:
        return text
    return f"{text[:BODY_PREVIEW_CHARS]}..."


def _join_endpoint(base_url: str, suffix: str) -> str:
    normalized = base_url.strip().rstrip("/")
    return f"{normalized}/{suffix.lstrip('/')}"


def _print_probe_result(name: str, url: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    print(f"=== {name} ===")
    print(f"URL: {url}")
    print(f"Request model: {payload.get('model')}")
    print(f"HTTP status: {result.get('status')}")
    if result.get("reason"):
        print(f"Reason: {result['reason']}")
    print("Body preview:")
    print(_preview(str(result.get("body", ""))) or "<empty>")
    print()


def main() -> int:
    args = _parse_args()
    key = _load_key(args.key)
    if not key:
        print("Missing KIMI API key. Pass --key or set KIMI_API_KEY.", file=sys.stderr)
        return 2

    print(f"Using KIMI key: {_mask_key(key)}")
    print()

    settings = get_settings()
    openai_base_url = (args.openai_base_url or settings.kimi_base_url or "https://api.moonshot.cn/v1").strip()
    anthropic_base_url = (args.anthropic_base_url or "https://api.moonshot.cn/anthropic").strip()

    v1_url = _join_endpoint(openai_base_url, "/chat/completions")
    v1_payload = {
        "model": args.openai_model,
        "messages": [
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": "Reply with exactly: ok"},
        ],
        "temperature": 0,
    }
    v1_result = _post_json(
        v1_url,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        payload=v1_payload,
        timeout=args.timeout,
        insecure=args.insecure,
    )
    _print_probe_result("OpenAI-compatible /v1", v1_url, v1_payload, v1_result)

    anthropic_url = _join_endpoint(anthropic_base_url, "/v1/messages")
    anthropic_payload = {
        "model": args.anthropic_model,
        "max_tokens": 64,
        "messages": [
            {"role": "user", "content": "Reply with exactly: ok"},
        ],
    }
    anthropic_result = _post_json(
        anthropic_url,
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        payload=anthropic_payload,
        timeout=args.timeout,
        insecure=args.insecure,
    )
    _print_probe_result("Anthropic-compatible /anthropic", anthropic_url, anthropic_payload, anthropic_result)

    print("=== Suggested curl ===")
    print(
        f"curl -i -sS {v1_url} "
        "-H 'Content-Type: application/json' "
        "-H 'Authorization: Bearer $KIMI_API_KEY' "
        f"-d '{json.dumps(v1_payload, ensure_ascii=False)}'"
    )
    print()
    print(
        f"curl -i -sS {anthropic_url} "
        "-H 'Content-Type: application/json' "
        "-H 'x-api-key: $KIMI_API_KEY' "
        "-H 'anthropic-version: 2023-06-01' "
        f"-d '{json.dumps(anthropic_payload, ensure_ascii=False)}'"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

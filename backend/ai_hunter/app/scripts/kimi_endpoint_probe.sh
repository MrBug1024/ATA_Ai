#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${KIMI_API_KEY:-}" ]]; then
  echo "Missing KIMI_API_KEY" >&2
  exit 2
fi

OPENAI_MODEL="${OPENAI_MODEL:-kimi-k2.6}"
ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-kimi-k2.5}"

echo "=== OpenAI-compatible /v1 ==="
curl -i -sS https://api.moonshot.cn/v1/chat/completions \
  -k \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${KIMI_API_KEY}" \
  -d "{
    \"model\": \"${OPENAI_MODEL}\",
    \"messages\": [
      {\"role\": \"system\", \"content\": \"You are a concise assistant.\"},
      {\"role\": \"user\", \"content\": \"Reply with exactly: ok\"}
    ],
    \"temperature\": 0
  }"

echo
echo
echo "=== Anthropic-compatible /anthropic ==="
curl -i -sS https://api.moonshot.cn/anthropic/v1/messages \
  -k \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${KIMI_API_KEY}" \
  -H "anthropic-version: 2023-06-01" \
  -d "{
    \"model\": \"${ANTHROPIC_MODEL}\",
    \"max_tokens\": 64,
    \"messages\": [
      {\"role\": \"user\", \"content\": \"Reply with exactly: ok\"}
    ]
  }"
echo

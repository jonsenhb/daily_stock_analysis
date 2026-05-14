#!/usr/bin/env bash
# Shared Ollama checks for scripts_local/*.sh — no project imports (avoids loading .env).
set -euo pipefail

OLLAMA_BASE="${OLLAMA_BASE:-http://127.0.0.1:11434}"
OLLAMA_BASE="${OLLAMA_BASE%/}"
export OLLAMA_BASE

echo "[ollama] GET /api/tags ..."
curl --noproxy '*' -sS "${OLLAMA_BASE}/api/tags" -o /tmp/dsa_ollama_tags.json
cat /tmp/dsa_ollama_tags.json
printf '\n'

echo "[ollama] POST /api/generate (stdlib Python only; prefers qwen3:8b if present) ..."
python - <<'PY'
import json
import os
import urllib.error
import urllib.request

base = os.environ.get("OLLAMA_BASE", "http://127.0.0.1:11434").rstrip("/")
with open("/tmp/dsa_ollama_tags.json", "r", encoding="utf-8") as f:
    payload = json.load(f)

models = [m.get("name", "") for m in payload.get("models", []) if m.get("name")]
if not models:
    raise SystemExit("Ollama returned no models in /api/tags; install or pull a model first.")

preferred = "qwen3:8b"
model = preferred if preferred in models else models[0]
print(f"  using model: {model}")

body = json.dumps({"model": model, "prompt": "ping", "stream": False}).encode("utf-8")
req = urllib.request.Request(
    f"{base}/api/generate",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
except urllib.error.HTTPError as e:
    raise SystemExit(f"Ollama /api/generate HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:500]}") from e

snippet = raw[:200].replace("\n", " ")
print(f"  generate response (first 200 chars): {snippet}")
PY

echo "[ollama] Probe OK."

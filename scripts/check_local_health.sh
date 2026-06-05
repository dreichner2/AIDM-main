#!/usr/bin/env bash
set -euo pipefail

BACKEND_URL="${AIDM_BACKEND_URL:-http://127.0.0.1:5050}"
FRONTEND_URL="${AIDM_FRONTEND_URL:-http://127.0.0.1:5173}"

echo "Backend health: $BACKEND_URL/api/health"
curl --fail --silent --show-error "$BACKEND_URL/api/health" >/dev/null

echo "LLM config: $BACKEND_URL/api/llm/config"
curl --fail --silent --show-error "$BACKEND_URL/api/llm/config" >/dev/null

echo "TTS config: $BACKEND_URL/api/tts/config"
curl --fail --silent --show-error "$BACKEND_URL/api/tts/config" >/dev/null

echo "Frontend: $FRONTEND_URL"
curl --fail --silent --show-error "$FRONTEND_URL" >/dev/null

echo "Configured local database URI:"
.venv/bin/python - <<'PY'
from aidm_server.env_loader import load_runtime_env

load_runtime_env()

from aidm_server.config import load_config

print(load_config().database_uri)
PY

echo "Local health checks passed."

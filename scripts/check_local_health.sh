#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${AIDM_PYTHON:-${REPO_ROOT}/.venv/bin/python}"
BACKEND_URL="${AIDM_BACKEND_URL:-http://127.0.0.1:5050}"
FRONTEND_URL="${AIDM_FRONTEND_URL:-http://127.0.0.1:5173}"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "[check_local_health] Missing python executable at ${VENV_PYTHON}" >&2
  echo "[check_local_health] Set AIDM_PYTHON or run make install from ${REPO_ROOT}" >&2
  exit 1
fi

cd "${REPO_ROOT}"

AUTH_TOKEN="${AIDM_AUTH_TOKEN:-}"
if [[ -z "${AUTH_TOKEN}" ]]; then
  AUTH_TOKEN="$("${VENV_PYTHON}" - <<'PY'
from aidm_server.env_loader import load_runtime_env

load_runtime_env()

from aidm_server.config import load_config

tokens = load_config().api_auth_tokens or []
print(tokens[0] if tokens else '')
PY
)"
fi

curl_with_auth() {
  if [[ -n "${AUTH_TOKEN}" ]]; then
    curl --fail --silent --show-error -H "Authorization: Bearer ${AUTH_TOKEN}" "$@"
    return
  fi
  curl --fail --silent --show-error "$@"
}

echo "Backend health: $BACKEND_URL/api/health"
curl_with_auth "$BACKEND_URL/api/health" >/dev/null

echo "LLM config: $BACKEND_URL/api/llm/config"
curl_with_auth "$BACKEND_URL/api/llm/config" >/dev/null

echo "TTS config: $BACKEND_URL/api/tts/config"
curl_with_auth "$BACKEND_URL/api/tts/config" >/dev/null

echo "Frontend: $FRONTEND_URL"
if ! curl_with_auth "$FRONTEND_URL" >/dev/null; then
  echo "Frontend fallback: $BACKEND_URL/"
  curl_with_auth "$BACKEND_URL/" >/dev/null
fi

echo "Configured local database URI:"
"${VENV_PYTHON}" - <<'PY'
from aidm_server.env_loader import load_runtime_env

load_runtime_env()

from aidm_server.config import load_config

print(load_config().database_uri)
PY

echo "Local health checks passed."

#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${REPO_ROOT}/aidm_frontend"
BACKEND_PORT="${AIDM_BACKEND_PORT:-5050}"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

if ! command -v npm >/dev/null 2>&1; then
  export NVM_DIR="${NVM_DIR:-${HOME}/.nvm}"
  if [[ -s "${NVM_DIR}/nvm.sh" ]]; then
    # shellcheck disable=SC1091
    . "${NVM_DIR}/nvm.sh"
    nvm use --silent default >/dev/null 2>&1 || nvm use --silent node >/dev/null 2>&1 || true
  fi
fi

command -v npm >/dev/null 2>&1

if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
  echo "[unified-local] Installing frontend dependencies"
  cd "${FRONTEND_DIR}"
  npm ci
fi

echo "[unified-local] Building frontend for same-origin backend"
cd "${FRONTEND_DIR}"
env VITE_AIDM_API_BASE_URL= npm run build

cd "${REPO_ROOT}"
echo "[unified-local] Starting unified AIDM on http://127.0.0.1:${BACKEND_PORT}/"
exec env \
  AIDM_SERVE_FRONTEND=true \
  AIDM_FRONTEND_DIST_DIR="${FRONTEND_DIR}/dist" \
  PORT="${BACKEND_PORT}" \
  ./scripts/run_local_backend.sh

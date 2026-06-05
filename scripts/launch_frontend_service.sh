#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${REPO_ROOT}/aidm_frontend"
FRONTEND_PORT="${AIDM_FRONTEND_PORT:-5173}"

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
  echo "[frontend-service] Installing frontend dependencies"
  cd "${FRONTEND_DIR}"
  npm install
fi

cd "${FRONTEND_DIR}"
exec npm run dev -- --host 127.0.0.1 --port "${FRONTEND_PORT}" --strictPort

#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${REPO_ROOT}/.venv/bin/python"
BACKEND_PORT="${AIDM_BACKEND_PORT:-5050}"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "[backend-service] Creating backend virtualenv"
  command -v python3 >/dev/null 2>&1
  python3 -m venv "${REPO_ROOT}/.venv"
  "${VENV_PYTHON}" -m pip install --upgrade pip
  "${VENV_PYTHON}" -m pip install -r "${REPO_ROOT}/requirements.txt"
fi

cd "${REPO_ROOT}"
exec env AIDM_BACKEND_PORT="${BACKEND_PORT}" ./scripts/run_unified_local.sh

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-5050}"
BIND="${AIDM_BIND:-0.0.0.0:${PORT}}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"
GUNICORN_BIN="${GUNICORN_BIN:-gunicorn}"
GUNICORN_TIMEOUT="${AIDM_GUNICORN_TIMEOUT:-180}"

export AIDM_SOCKETIO_WORKER_MODEL="${AIDM_SOCKETIO_WORKER_MODEL:-single}"
export AIDM_SOCKETIO_ASYNC_MODE="${AIDM_SOCKETIO_ASYNC_MODE:-eventlet}"

if [[ "${AIDM_SOCKETIO_ASYNC_MODE}" != "eventlet" ]]; then
  echo "AIDM_SOCKETIO_ASYNC_MODE must be eventlet for scripts/run_production_server.sh." >&2
  exit 2
fi

if [[ "${AIDM_SOCKETIO_WORKER_MODEL}" == "single" && "${WEB_CONCURRENCY}" != "1" ]]; then
  echo "AIDM_SOCKETIO_WORKER_MODEL=single requires WEB_CONCURRENCY=1." >&2
  exit 2
fi

cmd=(
  "${GUNICORN_BIN}"
  --worker-class eventlet
  --workers "${WEB_CONCURRENCY}"
  --bind "${BIND}"
  --timeout "${GUNICORN_TIMEOUT}"
  --access-logfile -
  --error-logfile -
  aidm_server.wsgi:app
)

if [[ "${1:-}" == "--print" ]]; then
  printf '%q ' "${cmd[@]}"
  printf '\n'
  exit 0
fi

cd "${ROOT_DIR}"
exec "${cmd[@]}"

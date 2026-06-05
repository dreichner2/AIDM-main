#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${REPO_ROOT}/aidm_frontend"
LOG_DIR="${REPO_ROOT}/tmp/launcher_logs"
BACKEND_PORT="${AIDM_BACKEND_PORT:-5050}"
FRONTEND_PORT="${AIDM_FRONTEND_PORT:-5173}"
BACKEND_HEALTH_URL="http://127.0.0.1:${BACKEND_PORT}/api/health"
FRONTEND_URL="${AIDM_FRONTEND_URL:-http://127.0.0.1:${FRONTEND_PORT}/}"
LAUNCH_DOMAIN="gui/$(id -u)"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

mkdir -p "${LOG_DIR}"
bash "${REPO_ROOT}/scripts/prune_launcher_logs.sh" "${LOG_DIR}" >/dev/null 2>&1 || true

log() {
  printf '[launcher] %s\n' "$*"
}

fail() {
  local message="$1"
  log "ERROR: ${message}"
  /usr/bin/open "${LOG_DIR}" >/dev/null 2>&1 || true
  /usr/bin/osascript - "${message}" "${LOG_DIR}" <<'APPLESCRIPT' >/dev/null 2>&1 || true
on run argv
  set dialogMessage to item 1 of argv & return & return & "Logs: " & item 2 of argv
  display dialog dialogMessage buttons {"OK"} default button "OK" with title "AI-DM Launcher"
end run
APPLESCRIPT
  exit 1
}

port_open() {
  /usr/sbin/lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

wait_for_http() {
  local url="$1"
  local label="$2"
  local max_seconds="${3:-90}"
  local start
  local now

  start="$(date +%s)"
  while true; do
    if /usr/bin/curl -fsS --connect-timeout 2 --max-time 4 "${url}" >/dev/null 2>&1; then
      log "${label} ready at ${url}"
      return 0
    fi

    now="$(date +%s)"
    if (( now - start >= max_seconds )); then
      return 1
    fi
    sleep 1
  done
}

install_launch_agent() {
  local label="$1"
  local source_plist="${REPO_ROOT}/scripts/launchd/${label}.plist"
  local target_plist="${HOME}/Library/LaunchAgents/${label}.plist"

  [[ -f "${source_plist}" ]] || fail "Missing LaunchAgent template at ${source_plist}."
  mkdir -p "${HOME}/Library/LaunchAgents"

  if [[ ! -f "${target_plist}" ]] || ! /usr/bin/cmp -s "${source_plist}" "${target_plist}"; then
    /bin/cp "${source_plist}" "${target_plist}"
    /bin/launchctl bootout "${LAUNCH_DOMAIN}/${label}" >/dev/null 2>&1 || true
  fi

  /bin/launchctl bootstrap "${LAUNCH_DOMAIN}" "${target_plist}" >/dev/null 2>&1 || true
  /bin/launchctl enable "${LAUNCH_DOMAIN}/${label}" >/dev/null 2>&1 || true
}

kickstart_launch_agent() {
  local label="$1"
  /bin/launchctl kickstart "${LAUNCH_DOMAIN}/${label}" >/dev/null 2>&1 || fail "Could not start ${label} LaunchAgent."
}

start_backend() {
  install_launch_agent "local.aidm.backend"

  if wait_for_http "${BACKEND_HEALTH_URL}" "Backend" 2; then
    return 0
  fi

  if port_open "${BACKEND_PORT}"; then
    fail "Port ${BACKEND_PORT} is in use, but ${BACKEND_HEALTH_URL} is not healthy."
  fi

  log "Starting backend LaunchAgent on ${BACKEND_PORT}"
  kickstart_launch_agent "local.aidm.backend"
}

start_frontend() {
  install_launch_agent "local.aidm.frontend"

  if wait_for_http "${FRONTEND_URL}" "Frontend" 2; then
    return 0
  fi

  if port_open "${FRONTEND_PORT}"; then
    fail "Port ${FRONTEND_PORT} is in use, but ${FRONTEND_URL} is not responding."
  fi

  log "Starting frontend LaunchAgent on ${FRONTEND_PORT}"
  kickstart_launch_agent "local.aidm.frontend"
}

{
  log "Launch requested at $(date)"
  start_backend
  wait_for_http "${BACKEND_HEALTH_URL}" "Backend" 120 || fail "Backend did not become ready at ${BACKEND_HEALTH_URL}."

  start_frontend
  wait_for_http "${FRONTEND_URL}" "Frontend" 90 || fail "Frontend did not become ready at ${FRONTEND_URL}."

  /usr/bin/open "${FRONTEND_URL}"
  /usr/bin/osascript -e 'display notification "Backend and frontend are running." with title "AI-DM Launcher"' >/dev/null 2>&1 || true
  log "Opened ${FRONTEND_URL}"
} >>"${LOG_DIR}/launcher.log" 2>&1

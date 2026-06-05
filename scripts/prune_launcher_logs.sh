#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${1:-${AIDM_LAUNCHER_LOG_DIR:-${REPO_ROOT}/tmp/launcher_logs}}"
MAX_BYTES="${AIDM_LAUNCHER_LOG_MAX_BYTES:-1048576}"
KEEP="${AIDM_LAUNCHER_LOG_KEEP:-5}"

is_positive_int() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

if ! is_positive_int "${MAX_BYTES}"; then
  echo "AIDM_LAUNCHER_LOG_MAX_BYTES must be a positive integer." >&2
  exit 2
fi

if ! is_positive_int "${KEEP}"; then
  echo "AIDM_LAUNCHER_LOG_KEEP must be a positive integer." >&2
  exit 2
fi

log_size() {
  /usr/bin/stat -f%z "$1" 2>/dev/null || /usr/bin/stat -c%s "$1"
}

rotate_log() {
  local file="$1"
  local size

  [[ -f "${file}" ]] || return 0
  size="$(log_size "${file}")"
  if (( size < MAX_BYTES )); then
    return 0
  fi

  local index
  for (( index = KEEP; index >= 1; index-- )); do
    if [[ -f "${file}.${index}" ]]; then
      if (( index == KEEP )); then
        rm -f "${file}.${index}"
      else
        mv "${file}.${index}" "${file}.$((index + 1))"
      fi
    fi
  done

  mv "${file}" "${file}.1"
  : >"${file}"
}

mkdir -p "${LOG_DIR}"
shopt -s nullglob
for log_file in "${LOG_DIR}"/*.log; do
  rotate_log "${log_file}"
done

echo "Pruned launcher logs in ${LOG_DIR}."

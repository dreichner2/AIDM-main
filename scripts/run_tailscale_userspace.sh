#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${HOME}/.local/share/tailscale"
SOCKET_PATH="${STATE_DIR}/tailscaled.sock"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

mkdir -p "${STATE_DIR}"
rm -f "${SOCKET_PATH}"

exec /opt/homebrew/bin/tailscaled \
  --tun=userspace-networking \
  --socket="${SOCKET_PATH}" \
  --state="${STATE_DIR}/tailscaled.state" \
  --statedir="${STATE_DIR}"

#!/usr/bin/env bash
set -euo pipefail

TAILSCALE_BIN="${TAILSCALE_BIN:-/opt/homebrew/bin/tailscale}"
TAILSCALE_SOCKET_PATH="${TAILSCALE_SOCKET_PATH:-${HOME}/.local/share/tailscale/tailscaled.sock}"
AIDM_PORT="${AIDM_BACKEND_PORT:-5050}"

tailscale_cmd() {
  "${TAILSCALE_BIN}" --socket="${TAILSCALE_SOCKET_PATH}" "$@"
}

case "${1:-status}" in
  status)
    tailscale_cmd status
    tailscale_cmd funnel status
    ;;
  url)
    dns_name="$(
      tailscale_cmd status --json \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"].get("DNSName", "").rstrip("."))'
    )"
    if [[ -z "${dns_name}" ]]; then
      echo "Tailscale DNS name is not available. Run: scripts/aidm_tailscale.sh login"
      exit 1
    fi
    echo "https://${dns_name}/"
    ;;
  login)
    tailscale_cmd up --hostname=aidm-mac-mini --accept-dns=false
    ;;
  funnel-on)
    tailscale_cmd funnel --bg --yes "${AIDM_PORT}"
    ;;
  funnel-off)
    tailscale_cmd funnel --https=443 off
    ;;
  *)
    echo "Usage: $0 [status|url|login|funnel-on|funnel-off]"
    exit 2
    ;;
esac

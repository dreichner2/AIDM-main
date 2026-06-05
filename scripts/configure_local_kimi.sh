#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env.local"

read -rsp "Enter your NVIDIA/Kimi API key: " KIMI_API_KEY
echo

cat > "${ENV_FILE}" <<EOF
AIDM_LLM_PROVIDER=nvidia
AIDM_NVIDIA_API_KEY=${KIMI_API_KEY}
AIDM_LLM_MODEL=moonshotai/kimi-k2.5
AIDM_LLM_FALLBACK_MODELS=
AIDM_NVIDIA_INVOKE_URL=https://integrate.api.nvidia.com/v1
AIDM_NVIDIA_THINKING=true
AIDM_NVIDIA_MAX_TOKENS=16384
AIDM_NVIDIA_TEMPERATURE=1.0
AIDM_NVIDIA_TOP_P=0.95
AIDM_NVIDIA_TIMEOUT_SECONDS=180
EOF

echo "[configure_local_kimi] Wrote ${ENV_FILE}"
echo "[configure_local_kimi] Local backend will now use Kimi 2.5 as the only model."

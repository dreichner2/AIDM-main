#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

rm -rf \
  "$ROOT_DIR/.pytest_cache" \
  "$ROOT_DIR/tmp" \
  "$ROOT_DIR/aidm_server/:memory:"

find "$ROOT_DIR" \
  -path "$ROOT_DIR/.venv" -prune -o \
  -path "$ROOT_DIR/aidm_frontend/node_modules" -prune -o \
  -path "$ROOT_DIR/aidm_frontend/dist" -prune -o \
  -type d -name "__pycache__" -prune -exec rm -rf {} +

echo "Cleaned local cache and runtime artifacts."

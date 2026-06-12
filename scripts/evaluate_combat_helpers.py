#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aidm_server.combat.evaluation import run_combat_helper_evaluation  # noqa: E402


def _load_snapshots(path: Path) -> list[dict]:
    payload = json.loads(path.read_text())
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get('snapshots'), list):
        return [item for item in payload['snapshots'] if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    raise SystemExit(f'Unsupported snapshot payload in {path}')


def main() -> int:
    parser = argparse.ArgumentParser(description='Evaluate combat helper candidate decisions from fixed snapshots.')
    parser.add_argument('snapshot_file', type=Path, help='JSON combat snapshot, list of snapshots, or {"snapshots": [...]}.')
    parser.add_argument('--indent', type=int, default=2, help='JSON indentation for output.')
    args = parser.parse_args()
    result = run_combat_helper_evaluation(_load_snapshots(args.snapshot_file))
    print(json.dumps(result, indent=args.indent, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

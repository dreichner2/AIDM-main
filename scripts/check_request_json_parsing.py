#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import re
import sys
from dataclasses import dataclass


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SCAN_ROOT = REPO_ROOT / 'aidm_server'
DEFAULT_ALLOWED_PATHS = (REPO_ROOT / 'aidm_server' / 'validation.py',)
REQUEST_GET_JSON_SILENT_RE = re.compile(r'\brequest\s*\.\s*get_json\s*\([^)]*silent\s*=\s*True')


@dataclass(frozen=True)
class JsonParsingViolation:
    path: pathlib.Path
    line_number: int
    line: str


def _resolve_repo_path(path: pathlib.Path) -> pathlib.Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _relative_or_absolute(path: pathlib.Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def find_violations(
    scan_root: pathlib.Path,
    *,
    allowed_paths: tuple[pathlib.Path, ...] = DEFAULT_ALLOWED_PATHS,
) -> list[JsonParsingViolation]:
    root = _resolve_repo_path(scan_root)
    allowed = {_resolve_repo_path(path).resolve() for path in allowed_paths}
    violations: list[JsonParsingViolation] = []
    for path in sorted(root.rglob('*.py')):
        resolved_path = path.resolve()
        if resolved_path in allowed:
            continue
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except UnicodeDecodeError:
            lines = path.read_text(errors='replace').splitlines()
        for line_number, line in enumerate(lines, start=1):
            if REQUEST_GET_JSON_SILENT_RE.search(line):
                violations.append(JsonParsingViolation(path=path, line_number=line_number, line=line.strip()))
    return violations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Fail when backend routes bypass shared JSON request parsing helpers with get_json(silent=True).'
    )
    parser.add_argument('--scan-root', type=pathlib.Path, default=DEFAULT_SCAN_ROOT)
    parser.add_argument(
        '--allow-path',
        type=pathlib.Path,
        action='append',
        default=[],
        help='Additional path allowed to call get_json(silent=True). aidm_server/validation.py is always allowed.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    allowed_paths = DEFAULT_ALLOWED_PATHS + tuple(args.allow_path or ())
    violations = find_violations(args.scan_root, allowed_paths=allowed_paths)
    if violations:
        print('[request-json-parsing][error] Direct get_json(silent=True) usage found outside shared helpers:')
        for violation in violations:
            print(
                f"- {_relative_or_absolute(violation.path)}:{violation.line_number}: "
                f"{violation.line}"
            )
        print('Use aidm_server.validation.parse_json_body or parse_optional_json_body instead.')
        return 1
    print('[request-json-parsing] No direct get_json(silent=True) usage outside shared helpers.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

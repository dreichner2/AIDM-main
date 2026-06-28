#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import pathlib
import sys
from dataclasses import dataclass


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SCAN_ROOT = REPO_ROOT / 'aidm_server'
DEFAULT_ALLOWED_PATHS = (REPO_ROOT / 'aidm_server' / 'validation.py',)


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


def _is_request_get_json_silent_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute) or node.func.attr != 'get_json':
        return False
    if not isinstance(node.func.value, ast.Name) or node.func.value.id != 'request':
        return False
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value is True:
        return True
    return any(
        keyword.arg == 'silent' and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        for keyword in node.keywords
    )


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
            source = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            source = path.read_text(errors='replace')
        lines = source.splitlines()
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            line_number = exc.lineno or 0
            source_line = lines[line_number - 1].strip() if 0 < line_number <= len(lines) else '<source unavailable>'
            violations.append(
                JsonParsingViolation(
                    path=path,
                    line_number=line_number,
                    line=f'<syntax error: {exc.msg}> {source_line}',
                )
            )
            continue
        for node in ast.walk(tree):
            if _is_request_get_json_silent_call(node):
                line = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else '<unknown call>'
                violations.append(JsonParsingViolation(path=path, line_number=node.lineno, line=line))
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
        print(
            '[request-json-parsing][error] Direct get_json(silent=True) usage found '
            'outside shared helpers, or unparseable Python found:'
        )
        for violation in violations:
            print(
                f"- {_relative_or_absolute(violation.path)}:{violation.line_number}: "
                f"{violation.line}"
            )
        print(
            'Use aidm_server.validation.parse_json_body or parse_optional_json_body instead, '
            'and fix syntax errors before this guard can inspect calls.'
        )
        return 1
    print('[request-json-parsing] No direct get_json(silent=True) usage outside shared helpers.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

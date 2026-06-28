#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    '.git',
    '.pytest_cache',
    '.venv',
    '__pycache__',
    'aidm_frontend/dist',
    'aidm_frontend/node_modules',
    'aidm_server/instance',
    'tmp',
}
SKIP_DIR_NAMES = {'.git', '.pytest_cache', '.venv', '__pycache__', 'node_modules', 'dist'}
SKIP_FILES = {'.env.local', '.DS_Store'}
TEXT_EXTENSIONS = {
    '',
    '.cfg',
    '.css',
    '.env',
    '.example',
    '.html',
    '.ini',
    '.js',
    '.json',
    '.lock',
    '.md',
    '.mjs',
    '.key',
    '.pem',
    '.py',
    '.sh',
    '.toml',
    '.ts',
    '.tsx',
    '.txt',
    '.yaml',
    '.yml',
}
ALLOWLIST_MARKERS = {
    'bootstrap-token',
    'dummy',
    'example',
    'fake',
    'placeholder',
    'test-key',
    'your-',
}

SECRET_PATTERNS = [
    (
        'OpenAI-style API key',
        re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
    ),
    (
        'GitHub token',
        re.compile(r'\bgh[pousr]_[A-Za-z0-9_]{30,}\b'),
    ),
    (
        'GitHub fine-grained token',
        re.compile(r'\bgithub_pat_[A-Za-z0-9_]{30,}\b'),
    ),
    (
        'AWS access key',
        re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    ),
    (
        'Google API key',
        re.compile(r'\bAIza[A-Za-z0-9_-]{35}\b'),
    ),
    (
        'Private key block',
        re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----'),
    ),
    (
        'Deepgram-looking API key',
        re.compile(r'\b(?:DEEPGRAM|AIDM_DEEPGRAM)[A-Z0-9_]*\s*[:=]\s*[\'"]?([0-9a-fA-F]{32})[\'"]?\b'),
    ),
    (
        'sensitive assignment',
        re.compile(
            r'\b(?:api[_-]?key|secret|token|password)\b[\'"]?\s*[:=]\s*[\'"]?([A-Za-z0-9_./+=-]{24,})[\'"]?',
            re.IGNORECASE,
        ),
    ),
]


@dataclass(frozen=True)
class Finding:
    path: Path
    line_number: int
    kind: str
    snippet: str


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _should_skip(path: Path) -> bool:
    rel = _relative(path)
    parts = set(Path(rel).parts)
    if path.name in SKIP_FILES:
        return True
    if parts & SKIP_DIR_NAMES:
        return True
    return any(rel == skip or rel.startswith(f'{skip}/') for skip in SKIP_DIRS)


def _iter_files(paths: list[Path]):
    for path in paths:
        if _should_skip(path):
            continue
        if path.is_dir():
            for child in path.rglob('*'):
                if child.is_file() and not _should_skip(child):
                    yield child
        elif path.is_file():
            yield path


def _is_text_candidate(path: Path) -> bool:
    if path.suffix not in TEXT_EXTENSIONS and not path.name.startswith('.env'):
        return False
    try:
        return b'\0' not in path.read_bytes()[:4096]
    except OSError:
        return False


def _allowed(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in ALLOWLIST_MARKERS)


def _redacted_snippet(line: str, secret_value: str) -> str:
    redacted_line = line.replace(secret_value, '<redacted>') if secret_value else line
    return redacted_line.strip()[:160]


def scan_paths(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in _iter_files(paths):
        if not _is_text_candidate(path):
            continue
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except UnicodeDecodeError:
            continue

        for line_number, line in enumerate(lines, start=1):
            for kind, pattern in SECRET_PATTERNS:
                for match in pattern.finditer(line):
                    secret_value = match.group(1) if match.groups() else match.group(0)
                    if _allowed(secret_value):
                        continue
                    findings.append(
                        Finding(
                            path=path,
                            line_number=line_number,
                            kind=kind,
                            snippet=_redacted_snippet(line, secret_value),
                        )
                    )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Scan source files for likely committed secrets.')
    parser.add_argument('paths', nargs='*', type=Path, default=[REPO_ROOT])
    args = parser.parse_args(argv)

    findings = scan_paths(args.paths)
    if findings:
        print('Potential secrets found:', file=sys.stderr)
        for finding in findings:
            print(
                f'- {_relative(finding.path)}:{finding.line_number}: {finding.kind}: {finding.snippet}',
                file=sys.stderr,
            )
        return 1

    print('No likely committed secrets found.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

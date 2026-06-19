#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import UTC, datetime
from typing import Any


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_EXISTING_VALUES = REPO_ROOT / 'tmp' / 'release' / 'external-proof-values.json'
DEFAULT_OUTPUT = DEFAULT_EXISTING_VALUES
DEFAULT_FRAGMENT = REPO_ROOT / 'tmp' / 'release' / 'external-proof-values.hosted-rc.json'
SENSITIVE_VALUE_KEYS = {'operator_auth_token', 'non_admin_token'}
MISSING_VALUES = {'', 'missing', 'none', 'not checked', 'placeholder', 'tbd', 'todo', 'unknown'}
EXPECTED_FRAGMENT_SCHEMA_VERSION = 1
EXPECTED_FRAGMENT_SOURCE = 'hosted_rc_evidence_check'


def _resolve_repo_path(path: pathlib.Path) -> pathlib.Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _relative_or_absolute(path: pathlib.Path | str) -> str:
    candidate = pathlib.Path(path)
    try:
        return str(candidate.relative_to(REPO_ROOT))
    except ValueError:
        return str(candidate)


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _text(value: Any) -> str:
    if value is None:
        return ''
    return str(value).strip()


def _real_text(value: Any) -> str:
    text = _text(value)
    if not text or '<' in text or '>' in text:
        return ''
    return '' if text.lower() in MISSING_VALUES else text


def _load_json_object(path: pathlib.Path, *, missing_ok: bool = False) -> dict[str, Any]:
    resolved = _resolve_repo_path(path)
    if not resolved.exists():
        if missing_ok:
            return {}
        raise SystemExit(f'[external-proof-values-merge] Missing JSON file: {_relative_or_absolute(resolved)}')
    try:
        parsed = json.loads(resolved.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise SystemExit(f'[external-proof-values-merge] Invalid JSON in {_relative_or_absolute(resolved)}: {exc}') from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f'[external-proof-values-merge] JSON root must be an object: {_relative_or_absolute(resolved)}')
    return parsed


def _write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    resolved = _resolve_repo_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _raw_values(payload: dict[str, Any]) -> dict[str, Any]:
    values = payload.get('values')
    return values if isinstance(values, dict) else payload


def _values_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    return {
        str(key): text
        for key, value in _raw_values(payload).items()
        if (text := _real_text(value))
    }


def _sensitive_values(payload: dict[str, Any]) -> list[str]:
    raw = _raw_values(payload)
    return sorted(key for key in SENSITIVE_VALUE_KEYS if _real_text(raw.get(key)))


def _fragment_provenance_errors(fragment: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if fragment.get('schema_version') != EXPECTED_FRAGMENT_SCHEMA_VERSION:
        errors.append(f'schema_version must be {EXPECTED_FRAGMENT_SCHEMA_VERSION}')
    if _real_text(fragment.get('source')) != EXPECTED_FRAGMENT_SOURCE:
        errors.append(f'source must be {EXPECTED_FRAGMENT_SOURCE}')
    if not _real_text(fragment.get('source_evidence')):
        errors.append('source_evidence must identify the hosted RC evidence report')
    return errors


def _fragment_values(fragment: dict[str, Any], *, path: pathlib.Path, allow_unusable: bool) -> dict[str, str]:
    provenance_errors = _fragment_provenance_errors(fragment)
    if provenance_errors:
        raise SystemExit(
            '[external-proof-values-merge] Refusing to merge proof fragment without hosted RC provenance '
            f'{_relative_or_absolute(_resolve_repo_path(path))}: {"; ".join(provenance_errors)}'
        )
    status = _real_text(fragment.get('status')).lower()
    usable_for_signoff = fragment.get('usable_for_signoff')
    if not allow_unusable and (status != 'passed' or usable_for_signoff is not True):
        raise SystemExit(
            '[external-proof-values-merge] Refusing to merge unusable proof fragment '
            f'{_relative_or_absolute(_resolve_repo_path(path))}; '
            'run hosted proof until status is passed and usable_for_signoff is true.'
        )
    sensitive = _sensitive_values(fragment)
    if sensitive:
        raise SystemExit(
            '[external-proof-values-merge] Refusing to merge sensitive field(s) from '
            f'{_relative_or_absolute(_resolve_repo_path(path))}: {", ".join(sensitive)}'
        )
    return _values_from_payload(fragment)


def build_merged_payload(
    *,
    existing_payload: dict[str, Any],
    fragments: list[tuple[pathlib.Path, dict[str, Any]]],
    allow_unusable: bool,
    generated_at: str,
) -> dict[str, Any]:
    sensitive = _sensitive_values(existing_payload)
    if sensitive:
        raise SystemExit(
            '[external-proof-values-merge] Existing values contain command-only sensitive field(s): '
            + ', '.join(sensitive)
        )
    values = _values_from_payload(existing_payload)
    sources: list[dict[str, str]] = []
    for path, fragment in fragments:
        fragment_values = _fragment_values(fragment, path=path, allow_unusable=allow_unusable)
        values.update(fragment_values)
        sources.append(
            {
                'path': _relative_or_absolute(_resolve_repo_path(path)),
                'source': _real_text(fragment.get('source')),
                'source_evidence': _real_text(fragment.get('source_evidence')),
                'status': _real_text(fragment.get('status')),
                'usable_for_signoff': str(fragment.get('usable_for_signoff')),
            }
        )

    payload: dict[str, Any] = {
        'release': _real_text(existing_payload.get('release')) or 'RC1',
        'commit': _real_text(existing_payload.get('commit')) or values.get('signed_off_commit_sha', ''),
        'target_url': _real_text(existing_payload.get('target_url')) or values.get('target_url', ''),
        'signed_by': _real_text(existing_payload.get('signed_by')),
        'signed_at': _real_text(existing_payload.get('signed_at')),
        'merged_at': generated_at,
        'sources': sources,
        'values': values,
    }
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Merge non-sensitive external proof values fragments.')
    parser.add_argument('fragments', nargs='*', type=pathlib.Path, help='Fragment JSON files to merge.')
    parser.add_argument('--existing', type=pathlib.Path, default=DEFAULT_EXISTING_VALUES)
    parser.add_argument('--output', type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        '--require-existing',
        action='store_true',
        help='Compatibility no-op; the existing values file is required unless --allow-missing-existing is set.',
    )
    parser.add_argument(
        '--allow-missing-existing',
        action='store_true',
        help='Allow this merge to create the values file when --existing does not exist.',
    )
    parser.add_argument('--allow-unusable', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fragment_paths = args.fragments or [DEFAULT_FRAGMENT]
    existing = _load_json_object(args.existing, missing_ok=args.allow_missing_existing)
    fragments = [(path, _load_json_object(path)) for path in fragment_paths]
    payload = build_merged_payload(
        existing_payload=existing,
        fragments=fragments,
        allow_unusable=args.allow_unusable,
        generated_at=_iso_now(),
    )
    if args.dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    _write_json(args.output, payload)
    print(f'[external-proof-values-merge] Wrote {_relative_or_absolute(_resolve_repo_path(args.output))}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

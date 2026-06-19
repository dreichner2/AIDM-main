from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Mapping
from urllib.parse import urlencode

import requests


DEFAULT_TARGET_URL = 'http://127.0.0.1:5050'
DEFAULT_OUTPUT_DIR = Path('tmp/support-bundles')


def _first_csv_value(value: str | None) -> str:
    return next((item.strip() for item in str(value or '').split(',') if item.strip()), '')


def _normalize_base_url(value: str) -> str:
    return value.strip().rstrip('/')


def support_bundle_url(target_url: str, *, session_id: int | None = None, limit: int = 25) -> str:
    base_url = _normalize_base_url(target_url or DEFAULT_TARGET_URL)
    params: dict[str, str] = {'limit': str(limit)}
    if session_id is not None:
        params['session_id'] = str(session_id)
    return f'{base_url}/api/beta/support-bundle?{urlencode(params)}'


def support_bundle_headers(
    *,
    auth_token: str = '',
    workspace_id: str = '',
    workspace_token: str = '',
) -> dict[str, str]:
    headers: dict[str, str] = {'Accept': 'application/json'}
    if auth_token.strip():
        headers['Authorization'] = f'Bearer {auth_token.strip()}'
    if workspace_token.strip():
        headers['X-AIDM-Workspace-Token'] = workspace_token.strip()
    elif workspace_id.strip():
        headers['X-AIDM-Workspace-Id'] = workspace_id.strip()
    return headers


def _filename_timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def default_output_path(
    output_dir: Path,
    *,
    session_id: int | None = None,
    now: datetime | None = None,
) -> Path:
    scope = f'session-{session_id}' if session_id is not None else 'workspace'
    return output_dir / f'aidm-support-bundle-{scope}-{_filename_timestamp(now)}.json'


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        for key in ('error', 'message'):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    text = response.text.strip()
    return text or f'HTTP {response.status_code}'


def fetch_support_bundle(
    target_url: str,
    *,
    auth_token: str = '',
    workspace_id: str = '',
    workspace_token: str = '',
    session_id: int | None = None,
    limit: int = 25,
    timeout_seconds: float = 15.0,
) -> dict:
    url = support_bundle_url(target_url, session_id=session_id, limit=limit)
    response = requests.get(
        url,
        headers=support_bundle_headers(
            auth_token=auth_token,
            workspace_id=workspace_id,
            workspace_token=workspace_token,
        ),
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise RuntimeError(f'GET {url} failed with {response.status_code}: {_error_message(response)}')
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f'GET {url} did not return JSON.') from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f'GET {url} returned JSON {type(payload).__name__}, expected object.')
    return payload


def write_support_bundle(payload: Mapping, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Export an operator beta support bundle as JSON.')
    parser.add_argument(
        '--target-url',
        default=os.getenv('AIDM_API_BASE_URL') or DEFAULT_TARGET_URL,
        help=f'Backend base URL. Defaults to AIDM_API_BASE_URL or {DEFAULT_TARGET_URL}.',
    )
    parser.add_argument(
        '--auth-token',
        default=os.getenv('AIDM_API_AUTH_TOKEN') or _first_csv_value(os.getenv('AIDM_API_AUTH_TOKENS')),
        help='Bearer token for hosted/operator API access. Defaults to AIDM_API_AUTH_TOKEN or first AIDM_API_AUTH_TOKENS value.',
    )
    parser.add_argument(
        '--workspace-id',
        default=os.getenv('AIDM_WORKSPACE_ID') or '',
        help='Workspace id header for account-token or bearer-token requests.',
    )
    parser.add_argument(
        '--workspace-token',
        default=os.getenv('AIDM_WORKSPACE_TOKEN') or '',
        help='Workspace token header. Takes precedence over --workspace-id when both are supplied.',
    )
    parser.add_argument('--session-id', type=int, default=None, help='Optional session id to scope the bundle.')
    parser.add_argument('--limit', type=int, default=25, help='Maximum rows per bundle section. Default: 25.')
    parser.add_argument('--timeout-seconds', type=float, default=15.0, help='HTTP request timeout. Default: 15.')
    parser.add_argument(
        '--output',
        type=Path,
        default=None,
        help='Output JSON file. Defaults to tmp/support-bundles/aidm-support-bundle-<scope>-<timestamp>.json.',
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help='Directory used when --output is omitted. Default: tmp/support-bundles.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit < 1:
        print('--limit must be positive.', file=sys.stderr)
        return 2
    if args.session_id is not None and args.session_id < 1:
        print('--session-id must be positive when provided.', file=sys.stderr)
        return 2

    output_path = args.output or default_output_path(args.output_dir, session_id=args.session_id)
    try:
        payload = fetch_support_bundle(
            args.target_url,
            auth_token=args.auth_token,
            workspace_id=args.workspace_id,
            workspace_token=args.workspace_token,
            session_id=args.session_id,
            limit=args.limit,
            timeout_seconds=args.timeout_seconds,
        )
        written_path = write_support_bundle(payload, output_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f'Exported support bundle: {written_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

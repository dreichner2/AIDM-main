#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

try:
    from scripts.post_rc_issue_evidence import DEFAULT_ISSUE_DIR, IssueEvidenceComment, load_issue_evidence_comments
except ModuleNotFoundError:  # pragma: no cover - exercised when run as a script path
    from post_rc_issue_evidence import DEFAULT_ISSUE_DIR, IssueEvidenceComment, load_issue_evidence_comments  # type: ignore[no-redef]


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / 'tmp' / 'release' / 'rc-issue-closure-evidence.md'
DEFAULT_JSON_OUTPUT = REPO_ROOT / 'tmp' / 'release' / 'rc-issue-closure-evidence.json'
DEFAULT_ISSUES = tuple(range(3, 10))


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


def _parse_issue_filter(value: str) -> set[int]:
    result: set[int] = set()
    for item in value.replace(';', ',').split(','):
        item = item.strip().lstrip('#')
        if item:
            result.add(int(item))
    return result


def _run_gh_issue_view(issue_number: int, *, gh_executable: str) -> tuple[dict[str, Any] | None, str]:
    if shutil.which(gh_executable) is None:
        return None, f'{gh_executable} not found'
    command = [
        gh_executable,
        'issue',
        'view',
        str(issue_number),
        '--json',
        'number,title,state,url,comments',
    ]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip() or f'gh exited {completed.returncode}'
        return None, error
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return None, f'invalid gh JSON: {exc}'
    if not isinstance(payload, dict):
        return None, 'gh JSON root was not an object'
    return payload, ''


def _comment_url(comment: dict[str, Any]) -> str:
    return str(comment.get('url') or comment.get('viewerUrl') or comment.get('htmlUrl') or '')


def _matches_generated_comment(remote_body: str, generated_body: str) -> bool:
    remote = remote_body.strip()
    generated = generated_body.strip()
    if not remote or not generated:
        return False
    if generated in remote or remote in generated:
        return True
    required_markers = (
        'Gate evidence:',
        '- Command run:',
        '- Evidence/log path:',
        '- Source archive:',
        '- Decision:',
    )
    return all(marker in remote for marker in required_markers)


def _matching_comment(comments: list[dict[str, Any]], generated_body: str) -> dict[str, Any] | None:
    for comment in reversed(comments):
        if not isinstance(comment, dict):
            continue
        if _matches_generated_comment(str(comment.get('body') or ''), generated_body):
            return comment
    return None


def _issue_item(
    comment: IssueEvidenceComment,
    *,
    remote: dict[str, Any] | None,
    remote_error: str,
) -> dict[str, Any]:
    remote_comments = remote.get('comments') if isinstance(remote, dict) else []
    if not isinstance(remote_comments, list):
        remote_comments = []
    match = _matching_comment(remote_comments, comment.body)
    remote_state = str(remote.get('state') or 'not checked') if isinstance(remote, dict) else 'not checked'
    remote_url = str(remote.get('url') or '') if isinstance(remote, dict) else ''
    complete = (
        remote_state.upper() == 'CLOSED'
        and match is not None
        and not comment.has_remaining_exceptions
        and not remote_error
    )
    if complete:
        remaining_action = ''
    elif comment.has_remaining_exceptions:
        remaining_action = 'attach remaining external proof, regenerate issue evidence, then close'
    elif remote_state.upper() != 'CLOSED':
        remaining_action = 'post/review generated evidence and close issue after external proof is attached'
    elif match is None:
        remaining_action = 'post matching generated issue evidence comment'
    else:
        remaining_action = remote_error or 'review issue closure evidence'
    return {
        'issue_number': comment.issue_number,
        'slug': comment.slug,
        'path': str(comment.path),
        'has_remaining_exceptions': comment.has_remaining_exceptions,
        'remote_state': remote_state,
        'remote_url': remote_url,
        'remote_error': remote_error,
        'remote_comment_count': len(remote_comments),
        'matching_comment_url': _comment_url(match) if match else '',
        'complete': complete,
        'remaining_action': remaining_action,
    }


def build_report(
    *,
    issue_dir: pathlib.Path,
    issue_numbers: set[int],
    generated_at: str,
    gh_executable: str,
    check_github: bool,
) -> dict[str, Any]:
    comments = load_issue_evidence_comments(issue_dir, issue_numbers=issue_numbers)
    by_number = {comment.issue_number: comment for comment in comments}
    items: list[dict[str, Any]] = []
    missing_local = sorted(issue_number for issue_number in issue_numbers if issue_number not in by_number)
    gh_errors: list[str] = []
    for issue_number in sorted(issue_numbers):
        comment = by_number.get(issue_number)
        if comment is None:
            items.append(
                {
                    'issue_number': issue_number,
                    'slug': '',
                    'path': '',
                    'has_remaining_exceptions': False,
                    'remote_state': 'not checked',
                    'remote_url': '',
                    'remote_error': '',
                    'remote_comment_count': 0,
                    'matching_comment_url': '',
                    'complete': False,
                    'remaining_action': 'generate local issue evidence snippet',
                }
            )
            continue
        remote = None
        remote_error = ''
        if check_github:
            remote, remote_error = _run_gh_issue_view(issue_number, gh_executable=gh_executable)
            if remote_error:
                gh_errors.append(f'#{issue_number}: {remote_error}')
        items.append(_issue_item(comment, remote=remote, remote_error=remote_error))

    complete_count = sum(1 for item in items if item.get('complete'))
    open_count = sum(1 for item in items if str(item.get('remote_state')).upper() == 'OPEN')
    matching_comment_count = sum(1 for item in items if item.get('matching_comment_url'))
    remaining_exception_count = sum(1 for item in items if item.get('has_remaining_exceptions'))
    if missing_local:
        status = 'missing-input'
    elif complete_count == len(items):
        status = 'passed'
    elif gh_errors:
        status = 'external-required'
    else:
        status = 'external-required'
    return {
        'generated_at': generated_at,
        'status': status,
        'issue_dir': str(_resolve_repo_path(issue_dir)),
        'checked_github': check_github,
        'issue_count': len(items),
        'complete_count': complete_count,
        'open_count': open_count,
        'matching_comment_count': matching_comment_count,
        'remaining_exception_count': remaining_exception_count,
        'missing_local_issues': missing_local,
        'gh_errors': gh_errors,
        'items': items,
    }


def render_markdown(report: dict[str, Any]) -> str:
    rows = [
        '| Issue | State | Local snippet | Remaining exceptions | Matching comment | Complete | Remaining action |',
        '| --- | --- | --- | --- | --- | --- | --- |',
    ]
    for item in report.get('items') or []:
        rows.append(
            f"| #{item.get('issue_number')} | {item.get('remote_state')} | "
            f"{_relative_or_absolute(item.get('path') or '')} | {item.get('has_remaining_exceptions')} | "
            f"{item.get('matching_comment_url') or ''} | {item.get('complete')} | "
            f"{item.get('remaining_action') or ''} |"
        )
    error_rows = ['| Error |', '| --- |']
    for error in report.get('gh_errors') or []:
        error_rows.append(f'| {error} |')
    if len(error_rows) == 2:
        error_rows.append('| None |')
    return '\n'.join(
        [
            '# RC Issue Closure Evidence',
            '',
            f"- Generated: {report.get('generated_at')}",
            f"- Status: {report.get('status')}",
            f"- Issue dir: `{_relative_or_absolute(report.get('issue_dir') or '')}`",
            f"- Checked GitHub: {report.get('checked_github')}",
            f"- Issues complete: {report.get('complete_count')}/{report.get('issue_count')}",
            f"- Open issues: {report.get('open_count')}",
            f"- Matching evidence comments: {report.get('matching_comment_count')}",
            f"- Local snippets with remaining exceptions: {report.get('remaining_exception_count')}",
            '',
            '## Issues',
            '',
            *rows,
            '',
            '## GitHub Errors',
            '',
            *error_rows,
            '',
        ]
    )


def write_report(report: dict[str, Any], *, output: pathlib.Path, json_output: pathlib.Path | None) -> None:
    output_path = _resolve_repo_path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown(report), encoding='utf-8')
    if json_output is not None:
        json_path = _resolve_repo_path(json_output)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Render read-only RC issue closure evidence from generated snippets and GitHub issue state.')
    parser.add_argument('--issue-dir', type=pathlib.Path, default=DEFAULT_ISSUE_DIR)
    parser.add_argument('--issues', default=','.join(str(issue) for issue in DEFAULT_ISSUES))
    parser.add_argument('--gh', default='gh')
    parser.add_argument('--no-github', action='store_true', help='Only inspect local issue snippets.')
    parser.add_argument('--output', type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--json-output', type=pathlib.Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument('--generated-at', default='', help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    generated_at = args.generated_at or _iso_now()
    report = build_report(
        issue_dir=args.issue_dir,
        issue_numbers=_parse_issue_filter(args.issues),
        generated_at=generated_at,
        gh_executable=args.gh,
        check_github=not args.no_github,
    )
    write_report(report, output=args.output, json_output=args.json_output)
    print(f'[rc-issue-closure-evidence] Wrote {_relative_or_absolute(_resolve_repo_path(args.output))}.')
    if args.json_output is not None:
        print(f'[rc-issue-closure-evidence] Wrote {_relative_or_absolute(_resolve_repo_path(args.json_output))}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

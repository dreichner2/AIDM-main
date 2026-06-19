#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_ISSUE_DIR = REPO_ROOT / 'tmp' / 'release' / 'issue-evidence'
ISSUE_FILE_RE = re.compile(r'^issue-(?P<number>\d+)-(?P<slug>[a-z0-9-]+)\.md$')
ISSUE_COMMENT_RE = re.compile(r'## Issue Comment\s+```markdown\s*(?P<body>.*?)\s*```\s*$', re.S)


@dataclass(frozen=True)
class IssueEvidenceComment:
    issue_number: int
    slug: str
    path: pathlib.Path
    body: str
    has_remaining_exceptions: bool


def _resolve_repo_path(path: pathlib.Path) -> pathlib.Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _parse_issue_filter(value: str) -> set[int]:
    result: set[int] = set()
    for item in value.replace(';', ',').split(','):
        item = item.strip().lstrip('#')
        if not item:
            continue
        result.add(int(item))
    return result


def _extract_issue_comment(markdown: str) -> str:
    match = ISSUE_COMMENT_RE.search(markdown)
    if not match:
        return markdown.strip()
    return match.group('body').strip() + '\n'


def _has_remaining_exceptions(body: str) -> bool:
    for line in body.splitlines():
        if not line.startswith('- Remaining exceptions:'):
            continue
        value = line.removeprefix('- Remaining exceptions:').strip()
        return bool(value and value.lower() not in {'none', 'none.'})
    return False


def load_issue_evidence_comments(
    issue_dir: pathlib.Path,
    *,
    issue_numbers: set[int] | None = None,
) -> list[IssueEvidenceComment]:
    resolved_dir = _resolve_repo_path(issue_dir)
    comments: list[IssueEvidenceComment] = []
    for path in sorted(resolved_dir.glob('issue-*.md')):
        match = ISSUE_FILE_RE.match(path.name)
        if not match:
            continue
        issue_number = int(match.group('number'))
        if issue_numbers is not None and issue_number not in issue_numbers:
            continue
        body = _extract_issue_comment(path.read_text(encoding='utf-8'))
        comments.append(
            IssueEvidenceComment(
                issue_number=issue_number,
                slug=match.group('slug'),
                path=path,
                body=body,
                has_remaining_exceptions=_has_remaining_exceptions(body),
            )
        )
    return comments


def _command_preview(comment: IssueEvidenceComment, *, close: bool, gh_executable: str) -> list[str]:
    commands = [f'{gh_executable} issue comment {comment.issue_number} --body-file <rendered-comment>']
    if close:
        commands.append(f'{gh_executable} issue close {comment.issue_number} --comment <rendered-comment>')
    return commands


def print_dry_run(comments: list[IssueEvidenceComment], *, close: bool, gh_executable: str) -> None:
    if not comments:
        print('[rc-issue-post] No issue evidence files matched.')
        return
    for comment in comments:
        print(f'[rc-issue-post][dry-run] Issue #{comment.issue_number} ({comment.slug}) from {comment.path}')
        for command in _command_preview(comment, close=close, gh_executable=gh_executable):
            print(f'  {command}')
        print('')
        print(comment.body.rstrip())
        print('')


def _run_gh(args: list[str], *, cwd: pathlib.Path) -> None:
    result = subprocess.run(args, cwd=str(cwd), text=True)
    if result.returncode != 0:
        raise RuntimeError(f'Command failed with exit {result.returncode}: {subprocess.list2cmdline(args)}')


def post_issue_comments(
    comments: list[IssueEvidenceComment],
    *,
    close: bool,
    gh_executable: str,
    allow_external_exceptions: bool,
) -> None:
    if close and not allow_external_exceptions:
        blocked = [comment.issue_number for comment in comments if comment.has_remaining_exceptions]
        if blocked:
            blocked_text = ', '.join(f'#{issue_number}' for issue_number in blocked)
            raise ValueError(
                f'Refusing to close issues with remaining exceptions: {blocked_text}. '
                'Pass --allow-external-exceptions only after those exceptions are intentionally accepted.'
            )
    with tempfile.TemporaryDirectory(prefix='aidm-rc-issue-comments-') as tmp:
        tmp_dir = pathlib.Path(tmp)
        for comment in comments:
            body_path = tmp_dir / f'issue-{comment.issue_number:02d}-{comment.slug}.md'
            body_path.write_text(comment.body, encoding='utf-8')
            _run_gh([gh_executable, 'issue', 'comment', str(comment.issue_number), '--body-file', str(body_path)], cwd=REPO_ROOT)
            if close:
                _run_gh([gh_executable, 'issue', 'close', str(comment.issue_number), '--comment', str(body_path)], cwd=REPO_ROOT)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Preview or post generated RC issue evidence comments with gh.')
    parser.add_argument(
        '--issue-dir',
        type=pathlib.Path,
        default=DEFAULT_ISSUE_DIR,
        help='Directory containing tmp/release/issue-evidence/issue-*.md files.',
    )
    parser.add_argument(
        '--issues',
        default='',
        help='Comma-separated issue numbers to include, for example "3,5,9". Defaults to all generated RC issues.',
    )
    parser.add_argument('--gh', default='gh', help='GitHub CLI executable.')
    parser.add_argument('--post', action='store_true', help='Post comments to GitHub. Without this, only preview.')
    parser.add_argument('--close', action='store_true', help='Close issues after posting comments. Requires --post.')
    parser.add_argument(
        '--allow-external-exceptions',
        action='store_true',
        help='Allow --close even when generated evidence still lists remaining external exceptions.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.close and not args.post:
        print('[rc-issue-post][error] --close requires --post.', file=sys.stderr)
        return 2
    try:
        issue_filter = _parse_issue_filter(args.issues) if args.issues.strip() else None
        comments = load_issue_evidence_comments(args.issue_dir, issue_numbers=issue_filter)
        if not comments:
            print('[rc-issue-post][error] No issue evidence files matched.', file=sys.stderr)
            return 1
        if not args.post:
            print_dry_run(comments, close=args.close, gh_executable=args.gh)
            return 0
        post_issue_comments(
            comments,
            close=args.close,
            gh_executable=args.gh,
            allow_external_exceptions=args.allow_external_exceptions,
        )
        print(f'[rc-issue-post] Posted {len(comments)} issue evidence comments.')
        return 0
    except Exception as exc:
        print(f'[rc-issue-post][error] {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

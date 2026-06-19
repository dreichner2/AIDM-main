from __future__ import annotations

import subprocess

import pytest

from scripts.post_rc_issue_evidence import (
    load_issue_evidence_comments,
    post_issue_comments,
    print_dry_run,
)


def _write_issue_file(issue_dir, number: int, slug: str, body: str) -> None:
    issue_dir.mkdir(parents=True, exist_ok=True)
    (issue_dir / f'issue-{number:02d}-{slug}.md').write_text(
        '\n'.join(
            [
                f'# Issue {number}',
                '',
                '## Issue Comment',
                '',
                '```markdown',
                body,
                '```',
                '',
            ]
        ),
        encoding='utf-8',
    )


def test_load_issue_evidence_comments_extracts_fenced_comment(tmp_path):
    issue_dir = tmp_path / 'issue-evidence'
    _write_issue_file(
        issue_dir,
        3,
        'preflight',
        'Gate evidence:\n\n- Remaining exceptions: Attach GitHub Actions run URLs.\n',
    )
    _write_issue_file(issue_dir, 9, 'packaging', 'Gate evidence:\n\n- Remaining exceptions: None.\n')

    comments = load_issue_evidence_comments(issue_dir, issue_numbers={3})

    assert len(comments) == 1
    assert comments[0].issue_number == 3
    assert comments[0].slug == 'preflight'
    assert comments[0].body == 'Gate evidence:\n\n- Remaining exceptions: Attach GitHub Actions run URLs.\n'
    assert comments[0].has_remaining_exceptions is True


def test_print_dry_run_shows_commands_without_calling_gh(tmp_path, capsys):
    issue_dir = tmp_path / 'issue-evidence'
    _write_issue_file(issue_dir, 9, 'packaging', 'Gate evidence:\n\n- Remaining exceptions: None.\n')
    comments = load_issue_evidence_comments(issue_dir)

    print_dry_run(comments, close=False, gh_executable='gh-test')

    output = capsys.readouterr().out
    assert '[rc-issue-post][dry-run] Issue #9 (packaging)' in output
    assert 'gh-test issue comment 9 --body-file <rendered-comment>' in output
    assert 'Gate evidence:' in output


def test_post_issue_comments_refuses_to_close_with_remaining_exceptions(tmp_path):
    issue_dir = tmp_path / 'issue-evidence'
    _write_issue_file(
        issue_dir,
        3,
        'preflight',
        'Gate evidence:\n\n- Remaining exceptions: Attach GitHub Actions run URLs.\n',
    )
    comments = load_issue_evidence_comments(issue_dir)

    with pytest.raises(ValueError, match='Refusing to close issues with remaining exceptions'):
        post_issue_comments(comments, close=True, gh_executable='gh', allow_external_exceptions=False)


def test_post_issue_comments_invokes_gh_for_post_and_close(tmp_path, monkeypatch):
    issue_dir = tmp_path / 'issue-evidence'
    calls: list[list[str]] = []
    _write_issue_file(issue_dir, 9, 'packaging', 'Gate evidence:\n\n- Remaining exceptions: None.\n')
    comments = load_issue_evidence_comments(issue_dir)

    def fake_run(args, cwd, text):
        calls.append(args)
        assert cwd
        assert text is True
        return subprocess.CompletedProcess(args=args, returncode=0)

    monkeypatch.setattr(subprocess, 'run', fake_run)

    post_issue_comments(comments, close=True, gh_executable='gh-test', allow_external_exceptions=False)

    assert calls[0][:4] == ['gh-test', 'issue', 'comment', '9']
    assert calls[1][:4] == ['gh-test', 'issue', 'close', '9']

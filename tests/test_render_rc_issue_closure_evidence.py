from __future__ import annotations

import json

from scripts.render_rc_issue_closure_evidence import build_report, main, render_markdown


def _write_issue_snippet(path, issue_number: int, *, exceptions: str = 'None.') -> None:
    path.write_text(
        '\n'.join(
            [
                f'# Issue {issue_number}',
                '',
                '## Issue Comment',
                '```markdown',
                'Gate evidence:',
                '',
                '- Command run: `scripts/closed_beta_rc_check.py --evidence-report tmp/release/rc-evidence.md`',
                '- Evidence/log path: `tmp/release/rc-evidence.md`',
                '- Source archive: `tmp/release/aidm-source.tar.gz` (passed)',
                f'- Remaining exceptions: {exceptions}',
                '- Decision: Local RC evidence is ready.',
                '```',
                '',
            ]
        ),
        encoding='utf-8',
    )


def test_build_report_marks_local_only_external_required_when_github_not_checked(tmp_path):
    issue_dir = tmp_path / 'issue-evidence'
    issue_dir.mkdir()
    _write_issue_snippet(issue_dir / 'issue-03-preflight.md', 3, exceptions='Attach hosted proof.')

    report = build_report(
        issue_dir=issue_dir,
        issue_numbers={3},
        generated_at='2026-06-19T00:00:00+00:00',
        gh_executable='gh',
        check_github=False,
    )
    markdown = render_markdown(report)

    assert report['status'] == 'external-required'
    assert report['remaining_exception_count'] == 1
    assert report['items'][0]['remote_state'] == 'not checked'
    assert '# RC Issue Closure Evidence' in markdown


def test_build_report_detects_missing_local_snippet(tmp_path):
    issue_dir = tmp_path / 'issue-evidence'
    issue_dir.mkdir()

    report = build_report(
        issue_dir=issue_dir,
        issue_numbers={3},
        generated_at='2026-06-19T00:00:00+00:00',
        gh_executable='gh',
        check_github=False,
    )

    assert report['status'] == 'missing-input'
    assert report['missing_local_issues'] == [3]
    assert report['items'][0]['remaining_action'] == 'generate local issue evidence snippet'


def test_main_writes_markdown_and_json(tmp_path):
    issue_dir = tmp_path / 'issue-evidence'
    issue_dir.mkdir()
    _write_issue_snippet(issue_dir / 'issue-03-preflight.md', 3)
    output = tmp_path / 'rc-issue-closure-evidence.md'
    json_output = tmp_path / 'rc-issue-closure-evidence.json'

    exit_code = main(
        [
            '--issue-dir',
            str(issue_dir),
            '--issues',
            '3',
            '--no-github',
            '--output',
            str(output),
            '--json-output',
            str(json_output),
            '--generated-at',
            '2026-06-19T00:00:00+00:00',
        ]
    )

    assert exit_code == 0
    assert '# RC Issue Closure Evidence' in output.read_text(encoding='utf-8')
    payload = json.loads(json_output.read_text(encoding='utf-8'))
    assert payload['issue_count'] == 1

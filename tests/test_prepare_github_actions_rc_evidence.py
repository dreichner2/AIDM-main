from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

from scripts import prepare_github_actions_rc_evidence as rc_plan


def _fake_run_factory(*, dirty: bool, ci_success: bool = False, rc_success: bool = False, calls: list[tuple[str, ...]]):
    commit = 'abcdef1234567890abcdef1234567890abcdef12'

    def fake_run(args, **kwargs):
        call = tuple(args)
        calls.append(call)
        if call == ('git', 'status', '--short'):
            return SimpleNamespace(returncode=0, stdout=' M file.py\n' if dirty else '', stderr='')
        if call == ('git', 'rev-parse', 'HEAD'):
            return SimpleNamespace(returncode=0, stdout=f'{commit}\n', stderr='')
        if call == ('git', 'rev-parse', '--short', 'HEAD'):
            return SimpleNamespace(returncode=0, stdout='abcdef1\n', stderr='')
        if call == ('git', 'branch', '--show-current'):
            return SimpleNamespace(returncode=0, stdout='main\n', stderr='')
        if call == ('git', 'remote', 'get-url', 'origin'):
            return SimpleNamespace(returncode=0, stdout='git@github.com:example/AIDM.git\n', stderr='')
        if call[:3] == ('gh-test', 'workflow', 'list'):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    [
                        {'name': 'AIDM CI', 'state': 'active', 'path': '.github/workflows/ci.yml'},
                        {'name': 'Closed Beta RC', 'state': 'active', 'path': '.github/workflows/closed-beta-rc.yml'},
                    ]
                ),
                stderr='',
            )
        if call[:3] == ('gh-test', 'run', 'list'):
            workflow = call[call.index('--workflow') + 1]
            success = ci_success if workflow == 'AIDM CI' else rc_success
            runs = (
                [
                    {
                        'databaseId': 111 if workflow == 'AIDM CI' else 222,
                        'displayTitle': workflow,
                        'status': 'completed',
                        'conclusion': 'success',
                        'event': 'workflow_dispatch',
                        'headSha': commit,
                        'createdAt': '2026-06-19T00:00:00Z',
                        'updatedAt': '2026-06-19T00:05:00Z',
                        'url': f'https://github.com/example/AIDM/actions/runs/{111 if workflow == "AIDM CI" else 222}',
                    }
                ]
                if success
                else []
            )
            return SimpleNamespace(returncode=0, stdout=json.dumps(runs), stderr='')
        if call[:3] == ('gh-test', 'workflow', 'run'):
            return SimpleNamespace(returncode=0, stdout='Dispatched workflow.\n', stderr='')
        return SimpleNamespace(returncode=1, stdout='', stderr=f'unexpected call: {call}')

    return fake_run


def test_build_report_blocks_dispatch_for_dirty_worktree(monkeypatch):
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        subprocess,
        'run',
        _fake_run_factory(dirty=True, calls=calls),
    )

    report = rc_plan.build_report(
        generated_at='2026-06-19T00:00:00+00:00',
        gh_executable='gh-test',
        ci_workflow='AIDM CI',
        closed_beta_rc_workflow='Closed Beta RC',
        dispatch_closed_beta_rc=True,
    )

    assert report['status'] == 'action-required'
    assert report['git']['repository'] == 'example/AIDM'
    assert report['can_dispatch_closed_beta_rc'] is False
    assert report['dispatch_blockers'] == ['worktree must be clean unless --allow-dirty is explicit']
    assert report['dispatch_status'] == 'blocked'
    assert 'clean signed-off worktree' in report['missing']
    assert any('commit/push the signed-off candidate' in command for command in report['next_commands'])
    assert any('make github-actions-rc-plan' in command for command in report['next_commands'])
    assert not any(command.startswith('gh-test workflow run') for command in report['next_commands'])
    assert not any(call[:3] == ('gh-test', 'workflow', 'run') for call in calls)


def test_build_report_detects_successful_runs_for_commit(monkeypatch):
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        subprocess,
        'run',
        _fake_run_factory(dirty=False, ci_success=True, rc_success=True, calls=calls),
    )

    report = rc_plan.build_report(
        generated_at='2026-06-19T00:00:00+00:00',
        gh_executable='gh-test',
        ci_workflow='AIDM CI',
        closed_beta_rc_workflow='Closed Beta RC',
    )
    markdown = rc_plan.render_markdown(report)

    assert report['status'] == 'passed'
    assert report['aidm_ci_run_url'].endswith('/111')
    assert report['closed_beta_rc_run_url'].endswith('/222')
    assert report['missing'] == []
    assert 'AIDM CI success run URL: `https://github.com/example/AIDM/actions/runs/111`' in markdown


def test_build_report_dispatches_closed_beta_rc_when_clean(monkeypatch):
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        subprocess,
        'run',
        _fake_run_factory(dirty=False, ci_success=True, rc_success=False, calls=calls),
    )

    report = rc_plan.build_report(
        generated_at='2026-06-19T00:00:00+00:00',
        gh_executable='gh-test',
        ci_workflow='AIDM CI',
        closed_beta_rc_workflow='Closed Beta RC',
        dispatch_closed_beta_rc=True,
        skip_browser_smoke=False,
        skip_dependency_audits=False,
    )

    assert report['status'] == 'action-required'
    assert report['can_dispatch_closed_beta_rc'] is True
    assert report['dispatch_blockers'] == []
    assert report['dispatch_status'] == 'dispatched'
    assert any(
        command == (
            'make github-actions-rc-plan '
            'GITHUB_ACTIONS_RC_PLAN_ARGS="--dispatch-closed-beta-rc --gh-executable gh-test"'
        )
        for command in report['next_commands']
    )
    assert any(
        call[:4] == ('gh-test', 'workflow', 'run', 'Closed Beta RC')
        and '--ref' in call
        and 'main' in call
        and 'skip_browser_smoke=false' in call
        for call in calls
    )


def test_main_writes_report_and_json(tmp_path, monkeypatch):
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        subprocess,
        'run',
        _fake_run_factory(dirty=False, ci_success=True, rc_success=True, calls=calls),
    )
    output = tmp_path / 'plan.md'
    json_output = tmp_path / 'plan.json'

    exit_code = rc_plan.main(
        [
            '--gh-executable',
            'gh-test',
            '--output',
            str(output),
            '--json-output',
            str(json_output),
            '--generated-at',
            '2026-06-19T00:00:00+00:00',
        ]
    )

    assert exit_code == 0
    assert '- Status: passed' in output.read_text(encoding='utf-8')
    assert json.loads(json_output.read_text(encoding='utf-8'))['status'] == 'passed'

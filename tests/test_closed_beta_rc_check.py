from __future__ import annotations

import pathlib

from scripts.closed_beta_rc_check import build_command_plan


def test_closed_beta_rc_plan_includes_release_gate_commands(tmp_path):
    plan = build_command_plan(
        python_executable='python-test',
        include_browser_smoke=True,
        include_dependency_audits=True,
        tmp_dir=tmp_path,
    )
    labels = [command.label for command in plan]

    assert labels == [
        'Deploy bootstrap check-only',
        'SQLite backup/restore drill',
        'Python correctness lint',
        'Secret scan',
        'Python dependency audit',
        'Backend tests',
        'Isolated beta smoke flow',
        'Scenario quality regressions',
        'Observability bundle check',
        'API type drift check',
        'Frontend tests',
        'Frontend build',
        'Frontend bundle budget',
        'Frontend production dependency audit',
        'Browser smoke',
    ]
    bootstrap = plan[0]
    assert bootstrap.args == ('python-test', 'scripts/deploy_bootstrap.py', '--check-only')
    assert bootstrap.env is not None
    assert bootstrap.env['AIDM_AUTH_REQUIRED'] == 'true'
    assert bootstrap.env['AIDM_AUTO_CREATE_SCHEMA'] == 'false'
    assert bootstrap.env['AIDM_DATABASE_URI'].startswith(f'sqlite:///{tmp_path}')

    backup_drill = plan[1]
    assert backup_drill.args[:2] == ('python-test', 'scripts/backup_restore_drill.py')
    assert backup_drill.env is not None
    assert backup_drill.env['AIDM_DATABASE_URI'] == bootstrap.env['AIDM_DATABASE_URI']


def test_closed_beta_rc_plan_supports_fast_local_iteration(tmp_path):
    plan = build_command_plan(
        python_executable='python-test',
        include_browser_smoke=False,
        include_dependency_audits=False,
        tmp_dir=tmp_path,
    )
    labels = [command.label for command in plan]

    assert 'Browser smoke' not in labels
    assert 'Python dependency audit' not in labels
    assert 'Frontend production dependency audit' not in labels
    assert 'Backend tests' in labels
    assert 'Observability bundle check' in labels
    assert 'SQLite backup/restore drill' in labels
    assert 'Frontend bundle budget' in labels


def test_closed_beta_rc_frontend_commands_run_from_frontend_dir(tmp_path):
    plan = build_command_plan(
        python_executable='python-test',
        include_browser_smoke=True,
        include_dependency_audits=True,
        tmp_dir=tmp_path,
    )

    frontend_commands = {
        command.label: pathlib.Path(command.cwd).name
        for command in plan
        if command.label.startswith('Frontend') or command.label == 'Browser smoke'
    }

    assert set(frontend_commands.values()) == {'aidm_frontend'}

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Iterable


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / 'aidm_frontend'


@dataclass(frozen=True)
class RcCommand:
    label: str
    args: tuple[str, ...]
    cwd: pathlib.Path = REPO_ROOT
    env: dict[str, str] | None = None


def _bootstrap_env(tmp_dir: pathlib.Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            'PYTHON_DOTENV_DISABLED': '1',
            'AIDM_DATABASE_URI': f"sqlite:///{tmp_dir / 'closed-beta-rc-bootstrap.sqlite'}",
            'AIDM_AUTO_CREATE_SCHEMA': 'false',
            'AIDM_ENV': 'test',
            'AIDM_DEBUG': 'false',
            'AIDM_AUTH_REQUIRED': 'true',
            'AIDM_API_AUTH_TOKENS': 'closed-beta-rc-token',
            'AIDM_CORS_ALLOWLIST': 'http://localhost',
            'AIDM_SOCKET_CORS_ALLOWLIST': 'http://localhost',
            'AIDM_SOCKETIO_ASYNC_MODE': 'threading',
            'AIDM_TELEMETRY_ENABLED': 'false',
            'AIDM_RATE_LIMIT_WINDOW_SECONDS': '30',
            'AIDM_RATE_LIMIT_MAX_API_REQUESTS': '120',
            'AIDM_RATE_LIMIT_MAX_SOCKET_MESSAGES': '40',
        }
    )
    return env


def build_command_plan(
    *,
    python_executable: str,
    include_browser_smoke: bool,
    include_dependency_audits: bool,
    tmp_dir: pathlib.Path,
) -> list[RcCommand]:
    commands = [
        RcCommand(
            'Deploy bootstrap check-only',
            (python_executable, 'scripts/deploy_bootstrap.py', '--check-only'),
            env=_bootstrap_env(tmp_dir),
        ),
        RcCommand(
            'SQLite backup/restore drill',
            (
                python_executable,
                'scripts/backup_restore_drill.py',
                '--output-dir',
                str(tmp_dir / 'backup-restore-drill'),
            ),
            env=_bootstrap_env(tmp_dir),
        ),
        RcCommand(
            'Python correctness lint',
            (python_executable, '-m', 'ruff', 'check', '--select', 'E9,F63,F7,F82', 'aidm_server', 'tests', 'scripts'),
        ),
        RcCommand('Secret scan', (python_executable, 'scripts/scan_secrets.py')),
        RcCommand('Backend tests', (python_executable, '-m', 'pytest')),
        RcCommand('Isolated beta smoke flow', (python_executable, 'scripts/smoke_beta_flow.py')),
        RcCommand('Scenario quality regressions', (python_executable, 'scripts/scenario_regression.py')),
        RcCommand('Observability bundle check', (python_executable, 'scripts/check_observability_bundle.py')),
        RcCommand('API type drift check', (python_executable, 'scripts/generate_api_types.py', '--check')),
        RcCommand('Frontend tests', ('npm', 'test'), cwd=FRONTEND_DIR),
        RcCommand('Frontend build', ('npm', 'run', 'build'), cwd=FRONTEND_DIR),
        RcCommand('Frontend bundle budget', ('npm', 'run', 'bundle:budget'), cwd=FRONTEND_DIR),
    ]
    if include_dependency_audits:
        secret_scan_index = next(
            index
            for index, command in enumerate(commands)
            if command.label == 'Secret scan'
        )
        commands.insert(
            secret_scan_index + 1,
            RcCommand('Python dependency audit', (python_executable, '-m', 'pip_audit', '-r', 'requirements.runtime.txt')),
        )
        commands.append(RcCommand('Frontend production dependency audit', ('npm', 'audit', '--omit=dev'), cwd=FRONTEND_DIR))
    if include_browser_smoke:
        commands.append(RcCommand('Browser smoke', ('npm', 'run', 'smoke:browser'), cwd=FRONTEND_DIR))
    return commands


def run_command(command: RcCommand) -> int:
    print(f'[closed-beta-rc] {command.label}...')
    result = subprocess.run(
        command.args,
        cwd=str(command.cwd),
        env=command.env,
        text=True,
    )
    if result.returncode != 0:
        print(f'[closed-beta-rc][failed] {command.label} exited with {result.returncode}.')
    return result.returncode


def run_plan(commands: Iterable[RcCommand]) -> int:
    for command in commands:
        returncode = run_command(command)
        if returncode != 0:
            return returncode
    print('[closed-beta-rc] All checks passed.')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Run the closed-beta release-candidate gate.')
    parser.add_argument(
        '--skip-browser-smoke',
        action='store_true',
        help='Skip the browser smoke flow. Use only when a browser is unavailable.',
    )
    parser.add_argument(
        '--skip-dependency-audits',
        action='store_true',
        help='Skip pip-audit and npm audit. Use only for offline local iteration.',
    )
    parser.add_argument(
        '--python',
        default=sys.executable,
        help='Python executable to use for child Python commands.',
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List planned checks without running them.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with tempfile.TemporaryDirectory(prefix='aidm-closed-beta-rc-') as tmp:
        commands = build_command_plan(
            python_executable=args.python,
            include_browser_smoke=not args.skip_browser_smoke,
            include_dependency_audits=not args.skip_dependency_audits,
            tmp_dir=pathlib.Path(tmp),
        )
        if args.list:
            for command in commands:
                relative_cwd = command.cwd.relative_to(REPO_ROOT) if command.cwd != REPO_ROOT else pathlib.Path('.')
                print(f'{command.label}: (cd {relative_cwd} && {" ".join(command.args)})')
            return 0
        return run_plan(commands)


if __name__ == '__main__':
    raise SystemExit(main())

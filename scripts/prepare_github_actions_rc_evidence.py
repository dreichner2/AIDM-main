#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / 'tmp' / 'release' / 'github-actions-rc-run-plan.md'
DEFAULT_JSON_OUTPUT = REPO_ROOT / 'tmp' / 'release' / 'github-actions-rc-run-plan.json'
DEFAULT_CI_WORKFLOW = 'AIDM CI'
DEFAULT_CLOSED_BETA_RC_WORKFLOW = 'Closed Beta RC'
GITHUB_REMOTE_RE = re.compile(r'(?:github\.com[:/])([^/\s]+)/([^/\s]+?)(?:\.git)?/?$')


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _resolve_repo_path(path: pathlib.Path) -> pathlib.Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _relative_or_absolute(path: pathlib.Path | str) -> str:
    candidate = pathlib.Path(path)
    try:
        return str(candidate.relative_to(REPO_ROOT))
    except ValueError:
        return str(candidate)


def _run(args: tuple[str, ...], *, gh_executable: str = 'gh') -> tuple[str, str, int]:
    command = tuple(gh_executable if arg == 'gh' else arg for arg in args)
    try:
        result = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True)
    except FileNotFoundError:
        return '', f'{command[0]} not found', 127
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def _git_value(args: tuple[str, ...], *, fallback: str = '') -> str:
    stdout, _stderr, returncode = _run(('git', *args))
    return stdout.strip() if returncode == 0 and stdout.strip() else fallback


def _repository_from_remote_url(url: str) -> str:
    match = GITHUB_REMOTE_RE.search(url.strip())
    if not match:
        return ''
    owner, repo = match.groups()
    return f'{owner}/{repo}'


def _git_context() -> dict[str, Any]:
    status_stdout, status_stderr, status_code = _run(('git', 'status', '--short'))
    changed_paths = [line for line in status_stdout.splitlines() if line.strip()] if status_code == 0 else []
    remote_url = _git_value(('remote', 'get-url', 'origin'))
    return {
        'commit': _git_value(('rev-parse', 'HEAD'), fallback='unknown'),
        'short_commit': _git_value(('rev-parse', '--short', 'HEAD'), fallback='unknown'),
        'branch': _git_value(('branch', '--show-current'), fallback=''),
        'repository': _repository_from_remote_url(remote_url),
        'remote_url': remote_url,
        'worktree_state': 'unknown' if status_code != 0 else ('clean' if not changed_paths else 'dirty'),
        'worktree_summary': status_stderr or ('clean' if not changed_paths else f'dirty ({len(changed_paths)} changed/untracked paths)'),
        'changed_paths': len(changed_paths),
    }


def _gh_json(args: tuple[str, ...], *, gh_executable: str) -> tuple[Any, str]:
    stdout, stderr, returncode = _run(('gh', *args), gh_executable=gh_executable)
    if returncode != 0:
        return None, stderr or stdout or f'{gh_executable} exited {returncode}'
    try:
        return json.loads(stdout or 'null'), ''
    except json.JSONDecodeError as exc:
        return None, f'invalid gh JSON: {exc}'


def _workflow_details(workflows: Any, workflow: str) -> dict[str, Any]:
    if not isinstance(workflows, list):
        return {'name': workflow, 'found': False, 'state': '', 'path': ''}
    for row in workflows:
        if isinstance(row, dict) and row.get('name') == workflow:
            return {
                'name': workflow,
                'found': True,
                'state': row.get('state') or '',
                'path': row.get('path') or '',
            }
    return {'name': workflow, 'found': False, 'state': '', 'path': ''}


def _successful_run_url(runs: Any, commit: str) -> str:
    if not isinstance(runs, list):
        return ''
    expected = commit.strip().lower()
    for run in runs:
        if not isinstance(run, dict):
            continue
        head_sha = str(run.get('headSha') or '').strip().lower()
        if expected and head_sha and head_sha != expected:
            continue
        if run.get('status') == 'completed' and run.get('conclusion') == 'success':
            return str(run.get('url') or '')
    return ''


def _run_list_for_commit(workflow: str, commit: str, *, gh_executable: str) -> tuple[list[dict[str, Any]], str]:
    payload, error = _gh_json(
        (
            'run',
            'list',
            '--workflow',
            workflow,
            '--commit',
            commit,
            '--limit',
            '5',
            '--json',
            'databaseId,displayTitle,status,conclusion,event,headSha,createdAt,updatedAt,url',
        ),
        gh_executable=gh_executable,
    )
    if error:
        return [], error
    return payload if isinstance(payload, list) else [], ''


def _dispatch_closed_beta_rc(
    *,
    workflow: str,
    branch: str,
    skip_browser_smoke: bool,
    skip_dependency_audits: bool,
    gh_executable: str,
) -> tuple[str, str]:
    if not branch:
        return 'failed', 'current branch is empty; cannot choose a workflow ref'
    stdout, stderr, returncode = _run(
        (
            'gh',
            'workflow',
            'run',
            workflow,
            '--ref',
            branch,
            '-f',
            f'skip_browser_smoke={str(skip_browser_smoke).lower()}',
            '-f',
            f'skip_dependency_audits={str(skip_dependency_audits).lower()}',
        ),
        gh_executable=gh_executable,
    )
    if returncode != 0:
        return 'failed', stderr or stdout or f'{gh_executable} workflow run exited {returncode}'
    return 'dispatched', stdout or f'Dispatched {workflow} on {branch}.'


def _dispatch_blockers(
    *,
    closed_beta_workflow: dict[str, Any],
    git_context: dict[str, Any],
    allow_dirty: bool,
    errors: list[str],
) -> list[str]:
    blockers: list[str] = []
    if not closed_beta_workflow.get('found'):
        blockers.append('Closed Beta RC workflow was not found')
    elif closed_beta_workflow.get('state') != 'active':
        blockers.append(f"Closed Beta RC workflow state is {closed_beta_workflow.get('state') or 'unknown'}")
    if not git_context.get('branch'):
        blockers.append('current branch is empty')
    if git_context.get('worktree_state') != 'clean' and not allow_dirty:
        blockers.append('worktree must be clean unless --allow-dirty is explicit')
    if errors:
        blockers.append('GitHub CLI lookup errors must be resolved first')
    return blockers


def _next_commands(
    *,
    git_context: dict[str, Any],
    closed_beta_rc_workflow: str,
    gh_executable: str,
    skip_browser_smoke: bool,
    skip_dependency_audits: bool,
) -> list[str]:
    dispatch_arg_parts = ['--dispatch-closed-beta-rc']
    if gh_executable != 'gh':
        dispatch_arg_parts.extend(['--gh-executable', gh_executable])
    if skip_browser_smoke:
        dispatch_arg_parts.append('--skip-browser-smoke')
    if skip_dependency_audits:
        dispatch_arg_parts.append('--skip-dependency-audits')
    dispatch_args = ' '.join(dispatch_arg_parts)
    guarded_dispatch = f'make github-actions-rc-plan GITHUB_ACTIONS_RC_PLAN_ARGS="{dispatch_args}"'
    commands = ['git status --short']
    if git_context.get('worktree_state') != 'clean':
        commands.append('commit/push the signed-off candidate, then rerun make closed-beta-rc && make rc-handoff-artifacts')
    commands.extend(
        [
            guarded_dispatch,
            (
                'make github-actions-evidence GITHUB_ACTIONS_EVIDENCE_ARGS='
                '"--auto-gh --include-gh-details --verify-closed-beta-rc-artifact-contents"'
            ),
        ]
    )
    return commands


def build_report(
    *,
    generated_at: str,
    gh_executable: str,
    ci_workflow: str,
    closed_beta_rc_workflow: str,
    dispatch_closed_beta_rc: bool = False,
    allow_dirty: bool = False,
    skip_browser_smoke: bool = False,
    skip_dependency_audits: bool = False,
) -> dict[str, Any]:
    git_context = _git_context()
    errors: list[str] = []
    workflows, workflow_error = _gh_json(('workflow', 'list', '--json', 'name,state,path'), gh_executable=gh_executable)
    if workflow_error:
        errors.append(f'workflow list: {workflow_error}')
        workflows = []
    workflow_details = {
        ci_workflow: _workflow_details(workflows, ci_workflow),
        closed_beta_rc_workflow: _workflow_details(workflows, closed_beta_rc_workflow),
    }

    latest_runs: dict[str, list[dict[str, Any]]] = {}
    for workflow in (ci_workflow, closed_beta_rc_workflow):
        runs, run_error = _run_list_for_commit(workflow, str(git_context.get('commit') or ''), gh_executable=gh_executable)
        latest_runs[workflow] = runs
        if run_error:
            errors.append(f'{workflow} runs: {run_error}')

    aidm_ci_run_url = _successful_run_url(latest_runs.get(ci_workflow), str(git_context.get('commit') or ''))
    closed_beta_rc_run_url = _successful_run_url(
        latest_runs.get(closed_beta_rc_workflow),
        str(git_context.get('commit') or ''),
    )
    closed_beta_workflow = workflow_details.get(closed_beta_rc_workflow) or {}
    dirty = git_context.get('worktree_state') != 'clean'
    dispatch_blockers = _dispatch_blockers(
        closed_beta_workflow=closed_beta_workflow,
        git_context=git_context,
        allow_dirty=allow_dirty,
        errors=errors,
    )
    can_dispatch = bool(
        closed_beta_workflow.get('found')
        and closed_beta_workflow.get('state') == 'active'
        and git_context.get('branch')
        and (allow_dirty or not dirty)
        and not errors
    )
    dispatch_status = 'not-requested'
    dispatch_message = ''
    if dispatch_closed_beta_rc:
        if not can_dispatch:
            dispatch_status = 'blocked'
            dispatch_message = 'Closed Beta RC dispatch is blocked; see errors and readiness fields.'
        else:
            dispatch_status, dispatch_message = _dispatch_closed_beta_rc(
                workflow=closed_beta_rc_workflow,
                branch=str(git_context.get('branch') or ''),
                skip_browser_smoke=skip_browser_smoke,
                skip_dependency_audits=skip_dependency_audits,
                gh_executable=gh_executable,
            )
            if dispatch_status == 'failed':
                errors.append(f'Closed Beta RC dispatch: {dispatch_message}')

    missing = []
    if not aidm_ci_run_url:
        missing.append('AIDM CI success run URL')
    if not closed_beta_rc_run_url:
        missing.append('Closed Beta RC success run URL')
    if git_context.get('worktree_state') != 'clean':
        missing.append('clean signed-off worktree')

    status = 'invalid' if errors else ('passed' if not missing else 'action-required')
    return {
        'generated_at': generated_at,
        'status': status,
        'git': git_context,
        'gh_executable': gh_executable,
        'ci_workflow': ci_workflow,
        'closed_beta_rc_workflow': closed_beta_rc_workflow,
        'workflow_details': workflow_details,
        'latest_runs': latest_runs,
        'aidm_ci_run_url': aidm_ci_run_url,
        'closed_beta_rc_run_url': closed_beta_rc_run_url,
        'missing': missing,
        'errors': errors,
        'can_dispatch_closed_beta_rc': can_dispatch,
        'dispatch_blockers': dispatch_blockers,
        'dispatch_closed_beta_rc_requested': dispatch_closed_beta_rc,
        'dispatch_status': dispatch_status,
        'dispatch_message': dispatch_message,
        'dispatch_command': (
            f'{gh_executable} workflow run {closed_beta_rc_workflow!r} --ref {git_context.get("branch") or "<branch>"} '
            f'-f skip_browser_smoke={str(skip_browser_smoke).lower()} '
            f'-f skip_dependency_audits={str(skip_dependency_audits).lower()}'
        ),
        'next_commands': _next_commands(
            git_context=git_context,
            closed_beta_rc_workflow=closed_beta_rc_workflow,
            gh_executable=gh_executable,
            skip_browser_smoke=skip_browser_smoke,
            skip_dependency_audits=skip_dependency_audits,
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    git_context = report.get('git') if isinstance(report.get('git'), dict) else {}
    workflow_details = report.get('workflow_details') if isinstance(report.get('workflow_details'), dict) else {}
    latest_runs = report.get('latest_runs') if isinstance(report.get('latest_runs'), dict) else {}
    workflow_rows = ['| Workflow | Found | State | Path |', '| --- | --- | --- | --- |']
    for workflow in (report.get('ci_workflow'), report.get('closed_beta_rc_workflow')):
        detail = workflow_details.get(workflow) if isinstance(workflow_details.get(workflow), dict) else {}
        workflow_rows.append(
            f"| {workflow} | {detail.get('found', False)} | {detail.get('state') or ''} | {detail.get('path') or ''} |"
        )

    run_rows = ['| Workflow | Status | Conclusion | Head SHA | Updated | URL |', '| --- | --- | --- | --- | --- | --- |']
    for workflow, runs in latest_runs.items():
        if not isinstance(runs, list):
            continue
        for run in runs[:5]:
            if not isinstance(run, dict):
                continue
            run_rows.append(
                f"| {workflow} | {run.get('status') or ''} | {run.get('conclusion') or ''} | "
                f"{run.get('headSha') or ''} | {run.get('updatedAt') or run.get('createdAt') or ''} | "
                f"{run.get('url') or ''} |"
            )
    if len(run_rows) == 2:
        run_rows.append('| None |  |  |  |  |  |')

    def bullets(values: list[str]) -> list[str]:
        return [f'- {value}' for value in values] if values else ['- None']

    return '\n'.join(
        [
            '# GitHub Actions RC Run Plan',
            '',
            f"- Generated: {report.get('generated_at')}",
            f"- Status: {report.get('status')}",
            f"- Repository: {git_context.get('repository') or 'missing'}",
            f"- Branch: {git_context.get('branch') or 'missing'}",
            f"- Commit: {git_context.get('commit') or 'missing'}",
            f"- Worktree: {git_context.get('worktree_state')}; {git_context.get('worktree_summary')}",
            f"- AIDM CI success run URL: `{report.get('aidm_ci_run_url') or 'missing'}`",
            f"- Closed Beta RC success run URL: `{report.get('closed_beta_rc_run_url') or 'missing'}`",
            f"- Can dispatch Closed Beta RC: {report.get('can_dispatch_closed_beta_rc')}",
            f"- Dispatch requested: {report.get('dispatch_closed_beta_rc_requested')}",
            f"- Dispatch status: {report.get('dispatch_status')}",
            f"- Dispatch message: {report.get('dispatch_message') or ''}",
            f"- Dispatch command: `{report.get('dispatch_command')}`",
            '',
            '## Missing Proof',
            '',
            *bullets([str(item) for item in report.get('missing') or []]),
            '',
            '## Errors',
            '',
            *bullets([str(error) for error in report.get('errors') or []]),
            '',
            '## Dispatch Blockers',
            '',
            *bullets([str(blocker) for blocker in report.get('dispatch_blockers') or []]),
            '',
            '## Next Commands',
            '',
            *bullets([str(command) for command in report.get('next_commands') or []]),
            '',
            '## Workflow Details',
            '',
            *workflow_rows,
            '',
            '## Latest Runs For Commit',
            '',
            *run_rows,
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
    parser = argparse.ArgumentParser(description='Prepare or dispatch GitHub Actions proof for the closed-beta RC.')
    parser.add_argument('--output', type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--json-output', type=pathlib.Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument('--gh-executable', default='gh')
    parser.add_argument('--ci-workflow', default=DEFAULT_CI_WORKFLOW)
    parser.add_argument('--closed-beta-rc-workflow', default=DEFAULT_CLOSED_BETA_RC_WORKFLOW)
    parser.add_argument('--dispatch-closed-beta-rc', action='store_true')
    parser.add_argument('--allow-dirty', action='store_true')
    parser.add_argument('--skip-browser-smoke', action='store_true')
    parser.add_argument('--skip-dependency-audits', action='store_true')
    parser.add_argument('--generated-at', default='', help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report(
        generated_at=args.generated_at or _iso_now(),
        gh_executable=args.gh_executable,
        ci_workflow=args.ci_workflow,
        closed_beta_rc_workflow=args.closed_beta_rc_workflow,
        dispatch_closed_beta_rc=args.dispatch_closed_beta_rc,
        allow_dirty=args.allow_dirty,
        skip_browser_smoke=args.skip_browser_smoke,
        skip_dependency_audits=args.skip_dependency_audits,
    )
    write_report(report, output=args.output, json_output=args.json_output)
    print(f'[github-actions-rc-plan] {report["status"]}; wrote {_relative_or_absolute(_resolve_repo_path(args.output))}.')
    if args.json_output is not None:
        print(f'[github-actions-rc-plan] JSON written to {_relative_or_absolute(_resolve_repo_path(args.json_output))}.')
    if args.dispatch_closed_beta_rc and report.get('dispatch_status') in {'blocked', 'failed'}:
        return 2
    return 1 if args.dispatch_closed_beta_rc and report.get('dispatch_status') != 'dispatched' else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

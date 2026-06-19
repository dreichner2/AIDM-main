#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CHECKLIST_STATUS_JSON = REPO_ROOT / 'tmp' / 'release' / 'release-checklist-status.json'
DEFAULT_EXTERNAL_PROOF_INPUTS_JSON = REPO_ROOT / 'tmp' / 'release' / 'external-proof-inputs.json'
DEFAULT_OUTPUT = REPO_ROOT / 'tmp' / 'release' / 'external-proof-execution-plan.md'
DEFAULT_JSON_OUTPUT = REPO_ROOT / 'tmp' / 'release' / 'external-proof-execution-plan.json'


@dataclass(frozen=True)
class Phase:
    key: str
    title: str
    goal: str


PHASES: tuple[Phase, ...] = (
    Phase(
        key='candidate_freeze',
        title='1. Freeze Signed Candidate',
        goal='Commit the release candidate, regenerate RC evidence from a clean worktree, and keep artifact hashes stable.',
    ),
    Phase(
        key='github_actions',
        title='2. Prove GitHub Actions And Artifacts',
        goal='Run/record the CI and Closed Beta RC workflow evidence, including downloadable handoff artifacts.',
    ),
    Phase(
        key='hosted_readiness',
        title='3. Prove Hosted Environment Readiness',
        goal='Validate target env, auth, CORS, cookies, health, metrics, security headers, and provider settings.',
    ),
    Phase(
        key='hosted_smokes',
        title='4. Run Hosted Smoke And Metrics Proof',
        goal='Run hosted cookie-auth, non-admin, export/import, and beta SLO evidence against the target.',
    ),
    Phase(
        key='manual_provider_proof',
        title='5. Attach Manual Hosted Provider Proof',
        goal='Attach provider/platform proof for backup/restore, worker process shape, and telemetry receipt.',
    ),
    Phase(
        key='final_signoff',
        title='6. Complete Release Signoff And Issue Closure',
        goal='Fill final operator signoff, attach the source archive, and close RC issues with reviewed evidence.',
    ),
)
PHASE_BY_KEY = {phase.key: phase for phase in PHASES}


ACTION_PHASES = {
    'github_actions_aidm_ci': 'github_actions',
    'github_actions_closed_beta_rc': 'github_actions',
    'github_actions_rc_artifact': 'github_actions',
    'hosted_env_config': 'hosted_readiness',
    'hosted_deployment_readiness': 'hosted_readiness',
    'hosted_cookie_auth': 'hosted_smokes',
    'hosted_non_admin_forbidden': 'hosted_smokes',
    'hosted_export_import': 'hosted_smokes',
    'hosted_beta_slo_baseline': 'hosted_smokes',
    'hosted_backup_restore': 'manual_provider_proof',
    'hosted_socketio_worker_process': 'manual_provider_proof',
    'multi_worker_socketio_staging': 'manual_provider_proof',
    'hosted_external_telemetry': 'manual_provider_proof',
    'source_archive_attachment': 'final_signoff',
    'rc_issue_closure_review': 'final_signoff',
    'final_operator_signoff': 'final_signoff',
    'operator_signoff': 'final_signoff',
    'make_clean': 'candidate_freeze',
    'make_clean_deps': 'candidate_freeze',
    'clean_signed_off_worktree': 'candidate_freeze',
}


COMMAND_PHASES = {
    'clean_signed_off_handoff': 'candidate_freeze',
    'github_actions_rc_plan': 'github_actions',
    'github_actions_evidence': 'github_actions',
    'deployment_readiness': 'hosted_readiness',
    'hosted_cookie_auth_smoke': 'hosted_smokes',
    'security_forbidden_smoke': 'hosted_smokes',
    'session_export_import_smoke': 'hosted_smokes',
    'beta_slo_baseline': 'hosted_smokes',
    'hosted_rc_evidence': 'manual_provider_proof',
    'external_proof_values_merge': 'final_signoff',
    'source_archive_attachment': 'final_signoff',
    'operator_signoff': 'final_signoff',
}


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


def _load_json_object(path: pathlib.Path) -> dict[str, Any]:
    resolved = _resolve_repo_path(path)
    if not resolved.exists():
        return {}
    try:
        parsed = json.loads(resolved.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise SystemExit(f'[external-proof-execution-plan] Invalid JSON in {_relative_or_absolute(resolved)}: {exc}') from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f'[external-proof-execution-plan] JSON root must be an object: {_relative_or_absolute(resolved)}')
    return parsed


def _phase_key_for_action(action: dict[str, Any]) -> str:
    key = str(action.get('key') or '')
    if key in ACTION_PHASES:
        return ACTION_PHASES[key]
    category = str(action.get('category') or '').lower()
    if 'github' in category:
        return 'github_actions'
    if 'hosted target' in category:
        return 'hosted_readiness'
    if 'manual hosted' in category:
        return 'manual_provider_proof'
    if 'release proof' in category or 'signoff' in category:
        return 'final_signoff'
    if 'packaging' in category:
        return 'candidate_freeze'
    return 'final_signoff'


def _phase_key_for_field(field: dict[str, Any]) -> str:
    for required_for in field.get('required_for') or []:
        phase = ACTION_PHASES.get(str(required_for))
        if phase:
            return phase
    return 'final_signoff'


def _phase_key_for_command(command: dict[str, Any]) -> str:
    return COMMAND_PHASES.get(str(command.get('key') or ''), 'final_signoff')


def _phase_key_for_checklist_item(item: dict[str, Any]) -> str:
    text = f"{item.get('section') or ''} {item.get('item') or ''} {item.get('remaining_action') or ''}".lower()
    if 'external-proof-execution-plan' in text:
        return ''
    if 'clean signed-off' in text or 'clean worktree' in text or 'commit/push' in text:
        return 'candidate_freeze'
    if 'operator-signoff' in text or 'operator signoff' in text or 'operator sign-off' in text:
        return 'final_signoff'
    if 'rc gate issues are closed' in text or 'issue closure' in text:
        return 'final_signoff'
    if any(marker in text for marker in ('hosted-cookie-auth', 'security-forbidden', 'forbidden smoke', 'export/import', 'beta-slo-baseline')):
        return 'hosted_smokes'
    if 'github actions' in text or 'closed beta rc' in text or 'workflow artifact' in text:
        return 'github_actions'
    if any(marker in text for marker in ('deployment-readiness', '/api/health', '/api/metrics', 'security headers')):
        return 'hosted_readiness'
    if any(marker in text for marker in ('aidm_auth_required', 'aidm_api_auth_tokens', 'cors', 'cookie', 'observability_provider', 'alert_owner')):
        return 'hosted_readiness'
    if any(marker in text for marker in ('backup', 'telemetry endpoint', 'worker process')):
        return 'manual_provider_proof'
    return 'final_signoff'


def _external_rows(checklist_status: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in checklist_status.get('items') or []:
        if not isinstance(item, dict) or item.get('status') != 'external-required':
            continue
        if 'external-proof-execution-plan' in str(item.get('item') or '').lower():
            continue
        rows.append(item)
    return rows


def _empty_phase(phase: Phase) -> dict[str, Any]:
    return {
        'key': phase.key,
        'title': phase.title,
        'goal': phase.goal,
        'pending_actions': [],
        'required_fields': [],
        'conditional_fields': [],
        'checklist_rows': [],
        'command_templates': [],
    }


def build_plan(
    *,
    checklist_status: dict[str, Any],
    external_inputs: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    phases = {phase.key: _empty_phase(phase) for phase in PHASES}
    for action in external_inputs.get('pending_actions') or []:
        if isinstance(action, dict):
            phases[_phase_key_for_action(action)]['pending_actions'].append(action)
    for field in external_inputs.get('fields') or []:
        if not isinstance(field, dict):
            continue
        status = field.get('status')
        if status == 'required':
            phases[_phase_key_for_field(field)]['required_fields'].append(field)
        elif status == 'conditional':
            phases[_phase_key_for_field(field)]['conditional_fields'].append(field)
    external_rows = _external_rows(checklist_status)
    for row in external_rows:
        phase_key = _phase_key_for_checklist_item(row)
        if phase_key:
            phases[phase_key]['checklist_rows'].append(row)
    for command in external_inputs.get('command_templates') or []:
        if isinstance(command, dict):
            phases[_phase_key_for_command(command)]['command_templates'].append(command)

    phase_list = list(phases.values())
    for phase in phase_list:
        phase['counts'] = {
            'pending_actions': len(phase['pending_actions']),
            'required_fields': len(phase['required_fields']),
            'conditional_fields': len(phase['conditional_fields']),
            'checklist_rows': len(phase['checklist_rows']),
            'command_templates': len(phase['command_templates']),
        }

    required_field_count = sum(len(phase['required_fields']) for phase in phase_list)
    pending_action_count = sum(len(phase['pending_actions']) for phase in phase_list)
    external_row_count = len(external_rows)
    status = 'ready' if required_field_count == 0 and pending_action_count == 0 and external_row_count == 0 else 'action-required'
    return {
        'generated_at': generated_at,
        'status': status,
        'checklist_counts': checklist_status.get('counts') or {},
        'external_input_status': external_inputs.get('status') or 'missing',
        'field_counts': external_inputs.get('field_counts') or {},
        'source_archive': external_inputs.get('source_archive') or {},
        'github_actions': external_inputs.get('github_actions') or {},
        'hosted_rc_evidence': external_inputs.get('hosted_rc_evidence') or {},
        'operator_signoff': external_inputs.get('operator_signoff') or {},
        'signed_off_worktree': external_inputs.get('signed_off_worktree') or {},
        'counts': {
            'phases': len(phase_list),
            'pending_actions': pending_action_count,
            'required_fields': required_field_count,
            'conditional_fields': sum(len(phase['conditional_fields']) for phase in phase_list),
            'external_checklist_rows': external_row_count,
        },
        'phases': phase_list,
    }


def _format_inputs(values: list[str]) -> str:
    return ', '.join(values) if values else ''


def _contextual_github_next_actions(actions: list[Any], worktree: dict[str, Any]) -> list[str]:
    clean_actions = [str(action) for action in actions if str(action).strip()]
    status = str(worktree.get('status') or '').strip().lower()
    if status not in {'dirty', 'unknown'}:
        return clean_actions

    prefix = (
        'Freeze and push a clean signed-off candidate first'
        if status == 'dirty'
        else 'Confirm the signed-off candidate is clean first'
    )
    contextualized: list[str] = []
    for action in clean_actions:
        if action.startswith(('Freeze and push a clean signed-off candidate first;', 'Confirm the signed-off candidate is clean first;')):
            contextualized.append(action)
            continue
        action_text = re.sub(r'commit [^,.;]+', 'the signed-off commit', action)
        if action_text:
            action_text = action_text[:1].lower() + action_text[1:]
        contextualized.append(f'{prefix}; then {action_text}')
    return contextualized


def render_markdown(plan: dict[str, Any]) -> str:
    counts = plan.get('counts') or {}
    source = plan.get('source_archive') or {}
    github = plan.get('github_actions') or {}
    github_missing_details = github.get('missing_details') if isinstance(github.get('missing_details'), dict) else {}
    github_next_actions = github.get('next_actions') if isinstance(github.get('next_actions'), list) else []
    hosted = plan.get('hosted_rc_evidence') or {}
    signoff = plan.get('operator_signoff') or {}
    worktree = plan.get('signed_off_worktree') or {}
    contextual_github_next_actions = _contextual_github_next_actions(github_next_actions, worktree)

    summary_rows = [
        '| Phase | Pending actions | Required fields | Checklist rows | First command |',
        '| --- | ---: | ---: | ---: | --- |',
    ]
    for phase in plan.get('phases') or []:
        phase_counts = phase.get('counts') or {}
        first_command = ''
        commands = phase.get('command_templates') or []
        if commands:
            first_command = str(commands[0].get('key') or '')
        summary_rows.append(
            f"| {phase.get('title')} | {phase_counts.get('pending_actions', 0)} | "
            f"{phase_counts.get('required_fields', 0)} | {phase_counts.get('checklist_rows', 0)} | "
            f"{first_command} |"
        )

    lines = [
        '# External Proof Execution Plan',
        '',
        f"- Generated: {plan.get('generated_at')}",
        f"- Status: {plan.get('status')}",
        f"- Pending actions: {counts.get('pending_actions', 0)}",
        f"- Required fields: {counts.get('required_fields', 0)}",
        f"- Conditional fields: {counts.get('conditional_fields', 0)}",
        f"- External checklist rows: {counts.get('external_checklist_rows', 0)}",
        (
            f"- Source archive: `{source.get('path') or 'missing'}` "
            f"sha256:{source.get('sha256') or 'missing'}"
        ),
        (
            f"- GitHub Actions: {github.get('status') or 'missing'}; "
            f"AIDM CI: {github.get('aidm_ci_run_url') or 'missing'}; "
            f"Closed Beta RC: {github.get('closed_beta_rc_run_url') or 'missing'}"
        ),
        *[f'- GitHub Actions missing {label}: {reason}' for label, reason in github_missing_details.items()],
        *[f'- GitHub Actions next action: {action}' for action in contextual_github_next_actions],
        (
            f"- Hosted RC: {hosted.get('status') or 'missing'}; "
            f"target: {hosted.get('target_url') or 'missing'}; "
            f"manual required: {hosted.get('manual_required_count') or 0}"
        ),
        f"- Operator signoff: {signoff.get('status') or 'missing'}; required complete: {signoff.get('required_complete') or 'missing'}",
        f"- Worktree: {worktree.get('status') or 'missing'}; {worktree.get('worktree') or 'missing'}",
        '',
        '## Phase Summary',
        '',
        *summary_rows,
        '',
    ]

    for phase in plan.get('phases') or []:
        lines.extend(
            [
                f"## {phase.get('title')}",
                '',
                phase.get('goal') or '',
                '',
            ]
        )
        actions = phase.get('pending_actions') or []
        action_rows = [
            '| Key | Issues | Current context | Prerequisite | Next action | Evidence | Inputs |',
            '| --- | --- | --- | --- | --- | --- | --- |',
        ]
        for action in actions:
            action_rows.append(
                f"| `{action.get('key')}` | {action.get('issues') or ''} | "
                f"{action.get('context_evidence') or ''} | {action.get('prerequisite') or ''} | "
                f"{action.get('next_action') or ''} | {action.get('evidence_to_record') or ''} | "
                f"{_format_inputs(action.get('required_inputs') or [])} |"
            )
        if len(action_rows) == 2:
            action_rows.append('| None |  |  |  |  |  |  |')
        lines.extend(['### Actions', '', *action_rows, ''])

        field_rows = ['| Field | Status | Handling | Placeholder/current value | Notes |', '| --- | --- | --- | --- | --- |']
        for field in [*(phase.get('required_fields') or []), *(phase.get('conditional_fields') or [])]:
            handling = 'command-only sensitive value' if field.get('sensitive') else 'persistable proof value'
            field_rows.append(
                f"| `{field.get('key')}` | {field.get('status')} | {handling} | "
                f"{field.get('current_value') or field.get('placeholder') or ''} | {field.get('notes') or ''} |"
            )
        if len(field_rows) == 2:
            field_rows.append('| None |  |  |  |  |')
        lines.extend(['### Inputs', '', *field_rows, ''])

        command_rows = ['| Key | Command |', '| --- | --- |']
        for command in phase.get('command_templates') or []:
            command_rows.append(f"| `{command.get('key')}` | `{command.get('command')}` |")
        if len(command_rows) == 2:
            command_rows.append('| None |  |')
        lines.extend(['### Command Templates', '', *command_rows, ''])

        checklist_rows = ['| Checklist line | Item | Remaining action |', '| ---: | --- | --- |']
        for row in phase.get('checklist_rows') or []:
            checklist_rows.append(
                f"| {row.get('line_number') or ''} | {row.get('item') or ''} | {row.get('remaining_action') or ''} |"
            )
        if len(checklist_rows) == 2:
            checklist_rows.append('|  | None |  |')
        lines.extend(['### Checklist Rows', '', *checklist_rows, ''])

    return '\n'.join(lines)


def write_plan(plan: dict[str, Any], *, output: pathlib.Path, json_output: pathlib.Path | None) -> None:
    output_path = _resolve_repo_path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown(plan), encoding='utf-8')
    if json_output is not None:
        json_path = _resolve_repo_path(json_output)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Render a phased execution plan for external RC proof collection.')
    parser.add_argument('--checklist-status-json', type=pathlib.Path, default=DEFAULT_CHECKLIST_STATUS_JSON)
    parser.add_argument('--external-proof-inputs-json', type=pathlib.Path, default=DEFAULT_EXTERNAL_PROOF_INPUTS_JSON)
    parser.add_argument('--output', type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--json-output', type=pathlib.Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument('--generated-at', default='', help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    generated_at = args.generated_at or _iso_now()
    checklist_status = _load_json_object(args.checklist_status_json)
    external_inputs = _load_json_object(args.external_proof_inputs_json)
    plan = build_plan(checklist_status=checklist_status, external_inputs=external_inputs, generated_at=generated_at)
    write_plan(plan, output=args.output, json_output=args.json_output)
    print(f'[external-proof-execution-plan] Wrote {_relative_or_absolute(_resolve_repo_path(args.output))}.')
    if args.json_output is not None:
        print(f'[external-proof-execution-plan] Wrote {_relative_or_absolute(_resolve_repo_path(args.json_output))}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

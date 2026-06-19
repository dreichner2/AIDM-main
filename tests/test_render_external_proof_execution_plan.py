from __future__ import annotations

import json

from scripts.render_external_proof_execution_plan import build_plan, main, render_markdown


def _checklist_status() -> dict:
    return {
        'counts': {'passed': 74, 'external-required': 26},
        'items': [
            {
                'section': 'Preflight',
                'line_number': 5,
                'item': 'RC evidence is generated from a clean signed-off commit/worktree before final issue closure.',
                'status': 'external-required',
                'evidence': 'dirty worktree',
                'remaining_action': 'commit/push the release candidate and regenerate RC evidence',
            },
            {
                'section': 'Preflight',
                'line_number': 14,
                'item': 'GitHub Actions `AIDM CI` passes backend tests, frontend checks, bundle budget, and browser smoke.',
                'status': 'external-required',
                'evidence': 'GitHub Actions evidence is incomplete',
                'remaining_action': 'attach AIDM CI and Closed Beta RC run URLs',
            },
            {
                'section': 'Security',
                'line_number': 57,
                'item': '`make hosted-cookie-auth-smoke` passes against the hosted/staging URL.',
                'status': 'external-required',
                'evidence': 'local only',
                'remaining_action': 'run hosted cookie-auth smoke against hosted/staging',
            },
            {
                'section': 'Preflight',
                'line_number': 31,
                'item': '`make operator-signoff-status` passes after GitHub Actions URLs and hosted proof links are filled.',
                'status': 'external-required',
                'evidence': 'missing',
                'remaining_action': 'fill tmp/release/operator-signoff.json',
            },
            {
                'section': 'Preflight',
                'line_number': 22,
                'item': '`make external-proof-execution-plan` renders a phased external proof plan.',
                'status': 'external-required',
                'evidence': 'missing',
                'remaining_action': 'run make external-proof-execution-plan',
            },
        ],
    }


def _external_inputs() -> dict:
    return {
        'status': 'action-required',
        'field_counts': {'required': 4, 'conditional': 0, 'provided_context': 1, 'total': 5},
        'source_archive': {'path': 'tmp/release/aidm-source.tar.gz', 'sha256': 'abc'},
        'github_actions': {
            'status': 'incomplete',
            'aidm_ci_run_url': 'url',
            'closed_beta_rc_run_url': 'missing',
            'missing_details': {
                'Closed Beta RC run URL': 'No recent Closed Beta RC runs were returned by gh run list.'
            },
            'next_actions': ['Run the manual Closed Beta RC workflow for commit abc123.'],
        },
        'hosted_rc_evidence': {'status': 'planned', 'target_url': 'https://closed-beta.example.test', 'manual_required_count': 3},
        'operator_signoff': {'status': 'missing', 'required_complete': '0/18'},
        'signed_off_worktree': {'status': 'dirty', 'worktree': 'dirty'},
        'fields': [
            {
                'key': 'signed_off_commit_sha',
                'status': 'required',
                'placeholder': '<sha>',
                'required_for': ['clean_signed_off_worktree'],
            },
            {
                'key': 'aidm_ci_run_url',
                'status': 'required',
                'placeholder': '<run-url>',
                'required_for': ['github_actions_aidm_ci'],
            },
            {
                'key': 'closed_beta_rc_run_url',
                'status': 'required',
                'placeholder': '<run-url>',
                'required_for': ['github_actions_closed_beta_rc'],
            },
            {
                'key': 'hosted_cookie_auth_evidence',
                'status': 'required',
                'placeholder': 'tmp/release/hosted-cookie-auth-evidence.md',
                'required_for': ['hosted_cookie_auth'],
            },
            {
                'key': 'operator_auth_token',
                'status': 'required',
                'placeholder': '<operator-token>',
                'required_for': ['hosted_deployment_readiness'],
                'notes': 'Pass to commands only.',
                'sensitive': True,
            },
        ],
        'pending_actions': [
            {
                'key': 'github_actions_closed_beta_rc',
                'issues': '#3',
                'category': 'GitHub Actions',
                'next_action': 'Run the manual Closed Beta RC workflow.',
                'evidence_to_record': 'Closed Beta RC run URL.',
                'required_inputs': [],
                'context_evidence': 'https://github.com/example/AIDM/actions/runs/111',
                'prerequisite': 'clean_signed_off_worktree',
            },
            {
                'key': 'hosted_cookie_auth',
                'issues': '#5 #7',
                'category': 'Hosted target',
                'next_action': 'Run hosted cookie auth.',
                'evidence_to_record': 'Hosted cookie auth report.',
                'required_inputs': ['<target-url>'],
            },
        ],
        'command_templates': [
            {
                'key': 'github_actions_evidence',
                'description': 'Refresh Actions evidence.',
                'command': (
                    'make github-actions-evidence GITHUB_ACTIONS_EVIDENCE_ARGS='
                    '"--auto-gh --include-gh-details --verify-closed-beta-rc-artifact-contents"'
                ),
            },
            {
                'key': 'hosted_cookie_auth_smoke',
                'description': 'Run hosted cookie auth.',
                'command': 'make hosted-cookie-auth-smoke',
            },
        ],
    }


def test_build_plan_groups_external_work_and_ignores_self_row():
    plan = build_plan(
        checklist_status=_checklist_status(),
        external_inputs=_external_inputs(),
        generated_at='2026-06-19T00:00:00+00:00',
    )
    phases = {phase['key']: phase for phase in plan['phases']}

    assert plan['status'] == 'action-required'
    assert plan['counts']['external_checklist_rows'] == 4
    assert phases['candidate_freeze']['counts']['required_fields'] == 1
    assert phases['candidate_freeze']['counts']['checklist_rows'] == 1
    assert phases['github_actions']['counts']['required_fields'] == 2
    assert phases['github_actions']['counts']['pending_actions'] == 1
    assert phases['hosted_smokes']['counts']['pending_actions'] == 1
    assert phases['hosted_smokes']['counts']['checklist_rows'] == 1
    assert phases['final_signoff']['counts']['required_fields'] == 0
    assert phases['final_signoff']['counts']['checklist_rows'] == 1

    markdown = render_markdown(plan)
    assert '# External Proof Execution Plan' in markdown
    assert '1. Freeze Signed Candidate' in markdown
    assert 'hosted_cookie_auth' in markdown
    assert '| Key | Issues | Current context | Prerequisite | Next action | Evidence | Inputs |' in markdown
    assert 'https://github.com/example/AIDM/actions/runs/111' in markdown
    assert 'clean_signed_off_worktree' in markdown
    assert 'GitHub Actions missing Closed Beta RC run URL' in markdown
    assert (
        'Freeze and push a clean signed-off candidate first; then run the manual Closed Beta RC workflow '
        'for the signed-off commit.'
    ) in markdown
    assert 'command-only sensitive value' in markdown


def test_render_markdown_keeps_commit_specific_github_action_for_clean_worktree():
    external_inputs = _external_inputs()
    external_inputs['signed_off_worktree'] = {'status': 'passed', 'worktree': 'clean'}
    plan = build_plan(
        checklist_status=_checklist_status(),
        external_inputs=external_inputs,
        generated_at='2026-06-19T00:00:00+00:00',
    )

    markdown = render_markdown(plan)

    assert 'GitHub Actions next action: Run the manual Closed Beta RC workflow for commit abc123.' in markdown


def test_render_markdown_does_not_double_contextualize_dirty_github_action():
    external_inputs = _external_inputs()
    external_inputs['github_actions']['next_actions'] = [
        'Freeze and push a clean signed-off candidate first; then run the manual Closed Beta RC workflow '
        'for the signed-off commit, then rerun make github-actions-evidence.'
    ]
    plan = build_plan(
        checklist_status=_checklist_status(),
        external_inputs=external_inputs,
        generated_at='2026-06-19T00:00:00+00:00',
    )

    markdown = render_markdown(plan)

    assert markdown.count('Freeze and push a clean signed-off candidate first;') == 1
    assert 'then freeze and push' not in markdown


def test_main_writes_markdown_and_json(tmp_path):
    checklist = tmp_path / 'release-checklist-status.json'
    external_inputs = tmp_path / 'external-proof-inputs.json'
    output = tmp_path / 'external-proof-execution-plan.md'
    json_output = tmp_path / 'external-proof-execution-plan.json'
    checklist.write_text(json.dumps(_checklist_status()), encoding='utf-8')
    external_inputs.write_text(json.dumps(_external_inputs()), encoding='utf-8')

    exit_code = main(
        [
            '--checklist-status-json',
            str(checklist),
            '--external-proof-inputs-json',
            str(external_inputs),
            '--output',
            str(output),
            '--json-output',
            str(json_output),
            '--generated-at',
            '2026-06-19T00:00:00+00:00',
        ]
    )

    assert exit_code == 0
    assert '# External Proof Execution Plan' in output.read_text(encoding='utf-8')
    payload = json.loads(json_output.read_text(encoding='utf-8'))
    assert payload['counts']['pending_actions'] == 2

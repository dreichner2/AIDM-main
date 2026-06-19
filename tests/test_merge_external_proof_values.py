from __future__ import annotations

import json

import pytest

from scripts.merge_external_proof_values import main


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding='utf-8')


def _hosted_fragment(**overrides):
    payload = {
        'schema_version': 1,
        'source': 'hosted_rc_evidence_check',
        'source_evidence': 'tmp/release/hosted-rc-evidence.md',
        'status': 'passed',
        'usable_for_signoff': True,
        'values': {'target_url': 'https://aidm.closedbeta.dev'},
    }
    payload.update(overrides)
    return payload


def test_main_merges_passed_hosted_values_fragment(tmp_path):
    existing = tmp_path / 'external-proof-values.json'
    fragment = tmp_path / 'external-proof-values.hosted-rc.json'
    output = tmp_path / 'merged.json'
    _write_json(
        existing,
        {
            'release': 'RC1',
            'signed_by': 'AIDM Operator',
            'values': {
                'aidm_ci_run_url': 'https://github.com/dreichner2/AIDM-main/actions/runs/111',
            },
        },
    )
    _write_json(
        fragment,
        _hosted_fragment(
            values={
                'target_url': 'https://aidm.closedbeta.dev',
                'workspace_id': 'workspace-1',
                'deployment_readiness_evidence': 'tmp/release/deployment-readiness-evidence.md',
                'external_telemetry_receipt': 'https://telemetry.closedbeta.dev/events/123',
            },
        ),
    )

    exit_code = main([str(fragment), '--existing', str(existing), '--output', str(output)])

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding='utf-8'))
    assert payload['release'] == 'RC1'
    assert payload['signed_by'] == 'AIDM Operator'
    assert payload['target_url'] == 'https://aidm.closedbeta.dev'
    assert payload['sources'][0]['path'] == str(fragment)
    assert payload['sources'][0]['source'] == 'hosted_rc_evidence_check'
    assert payload['sources'][0]['source_evidence'] == 'tmp/release/hosted-rc-evidence.md'
    assert payload['values'] == {
        'aidm_ci_run_url': 'https://github.com/dreichner2/AIDM-main/actions/runs/111',
        'deployment_readiness_evidence': 'tmp/release/deployment-readiness-evidence.md',
        'external_telemetry_receipt': 'https://telemetry.closedbeta.dev/events/123',
        'target_url': 'https://aidm.closedbeta.dev',
        'workspace_id': 'workspace-1',
    }


def test_main_refuses_unusable_fragment_by_default(tmp_path):
    existing = tmp_path / 'external-proof-values.json'
    fragment = tmp_path / 'external-proof-values.hosted-rc.json'
    output = tmp_path / 'merged.json'
    _write_json(existing, {'values': {'aidm_ci_run_url': 'https://github.com/dreichner2/AIDM-main/actions/runs/111'}})
    _write_json(
        fragment,
        _hosted_fragment(
            status='planned',
            usable_for_signoff=False,
            values={'target_url': 'https://closed-beta.example.test'},
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        main([str(fragment), '--existing', str(existing), '--output', str(output)])

    assert 'Refusing to merge unusable proof fragment' in str(exc_info.value)
    assert 'status is passed and usable_for_signoff is true' in str(exc_info.value)
    assert not output.exists()


def test_main_refuses_passed_fragment_without_explicit_usable_flag(tmp_path):
    existing = tmp_path / 'external-proof-values.json'
    fragment = tmp_path / 'external-proof-values.hosted-rc.json'
    output = tmp_path / 'merged.json'
    _write_json(existing, {'values': {'aidm_ci_run_url': 'https://github.com/dreichner2/AIDM-main/actions/runs/111'}})
    fragment_payload = _hosted_fragment(status='passed', values={'target_url': 'https://aidm.closedbeta.dev'})
    fragment_payload.pop('usable_for_signoff')
    _write_json(fragment, fragment_payload)

    with pytest.raises(SystemExit) as exc_info:
        main([str(fragment), '--existing', str(existing), '--output', str(output)])

    assert 'Refusing to merge unusable proof fragment' in str(exc_info.value)
    assert 'usable_for_signoff is true' in str(exc_info.value)
    assert not output.exists()


def test_main_refuses_usable_fragment_without_passed_status(tmp_path):
    existing = tmp_path / 'external-proof-values.json'
    fragment = tmp_path / 'external-proof-values.hosted-rc.json'
    output = tmp_path / 'merged.json'
    _write_json(existing, {'values': {'aidm_ci_run_url': 'https://github.com/dreichner2/AIDM-main/actions/runs/111'}})
    _write_json(
        fragment,
        _hosted_fragment(
            status='manual-evidence-required',
            usable_for_signoff=True,
            values={'target_url': 'https://aidm.closedbeta.dev'},
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        main([str(fragment), '--existing', str(existing), '--output', str(output)])

    assert 'Refusing to merge unusable proof fragment' in str(exc_info.value)
    assert 'status is passed' in str(exc_info.value)
    assert not output.exists()


def test_main_refuses_fragment_without_hosted_source_provenance(tmp_path):
    existing = tmp_path / 'external-proof-values.json'
    fragment = tmp_path / 'external-proof-values.hosted-rc.json'
    output = tmp_path / 'merged.json'
    _write_json(existing, {'values': {'aidm_ci_run_url': 'https://github.com/dreichner2/AIDM-main/actions/runs/111'}})
    _write_json(
        fragment,
        {
            'status': 'passed',
            'usable_for_signoff': True,
            'values': {'target_url': 'https://aidm.closedbeta.dev'},
        },
    )

    with pytest.raises(SystemExit) as exc_info:
        main([str(fragment), '--existing', str(existing), '--output', str(output)])

    assert 'without hosted RC provenance' in str(exc_info.value)
    assert 'schema_version must be 1' in str(exc_info.value)
    assert 'source must be hosted_rc_evidence_check' in str(exc_info.value)
    assert 'source_evidence must identify the hosted RC evidence report' in str(exc_info.value)
    assert not output.exists()


def test_main_refuses_fragment_with_wrong_hosted_source(tmp_path):
    existing = tmp_path / 'external-proof-values.json'
    fragment = tmp_path / 'external-proof-values.hosted-rc.json'
    output = tmp_path / 'merged.json'
    _write_json(existing, {'values': {'aidm_ci_run_url': 'https://github.com/dreichner2/AIDM-main/actions/runs/111'}})
    _write_json(fragment, _hosted_fragment(source='manual-edit'))

    with pytest.raises(SystemExit) as exc_info:
        main([str(fragment), '--existing', str(existing), '--output', str(output)])

    assert 'without hosted RC provenance' in str(exc_info.value)
    assert 'source must be hosted_rc_evidence_check' in str(exc_info.value)
    assert not output.exists()


def test_main_refuses_sensitive_fragment_values(tmp_path):
    existing = tmp_path / 'external-proof-values.json'
    fragment = tmp_path / 'external-proof-values.hosted-rc.json'
    output = tmp_path / 'merged.json'
    _write_json(existing, {'values': {'aidm_ci_run_url': 'https://github.com/dreichner2/AIDM-main/actions/runs/111'}})
    _write_json(
        fragment,
        _hosted_fragment(
            status='passed',
            usable_for_signoff=True,
            values={'operator_auth_token': 'secret-token'},
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        main([str(fragment), '--existing', str(existing), '--output', str(output)])

    assert 'Refusing to merge sensitive field(s)' in str(exc_info.value)
    assert 'operator_auth_token' in str(exc_info.value)
    assert not output.exists()


def test_main_requires_existing_values_file_by_default(tmp_path):
    fragment = tmp_path / 'external-proof-values.hosted-rc.json'
    missing_existing = tmp_path / 'missing-values.json'
    output = tmp_path / 'merged.json'
    _write_json(
        fragment,
        _hosted_fragment(
            status='passed',
            usable_for_signoff=True,
            values={'target_url': 'https://aidm.closedbeta.dev'},
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        main([str(fragment), '--existing', str(missing_existing), '--output', str(output)])

    assert 'Missing JSON file' in str(exc_info.value)
    assert str(missing_existing) in str(exc_info.value)
    assert not output.exists()


def test_main_can_explicitly_allow_missing_existing_values_file(tmp_path):
    fragment = tmp_path / 'external-proof-values.hosted-rc.json'
    missing_existing = tmp_path / 'missing-values.json'
    output = tmp_path / 'merged.json'
    _write_json(
        fragment,
        _hosted_fragment(
            status='passed',
            usable_for_signoff=True,
            values={'target_url': 'https://aidm.closedbeta.dev'},
        ),
    )

    exit_code = main(
        [
            str(fragment),
            '--existing',
            str(missing_existing),
            '--output',
            str(output),
            '--allow-missing-existing',
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding='utf-8'))
    assert payload['target_url'] == 'https://aidm.closedbeta.dev'
    assert payload['values']['target_url'] == 'https://aidm.closedbeta.dev'

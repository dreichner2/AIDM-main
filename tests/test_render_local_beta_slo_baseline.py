from __future__ import annotations

import json

from scripts.render_local_beta_slo_baseline import main


def test_main_renders_isolated_local_baseline(tmp_path, monkeypatch):
    monkeypatch.setenv('AIDM_DATABASE_URI', 'sqlite:////tmp/should-not-be-used.db')
    output_path = tmp_path / 'beta-slo-baseline.md'
    slo_json_path = tmp_path / 'beta-slo.json'
    incidents_json_path = tmp_path / 'beta-incidents.json'

    exit_code = main(
        [
            '--output',
            str(output_path),
            '--slo-json-output',
            str(slo_json_path),
            '--incidents-json-output',
            str(incidents_json_path),
            '--release',
            'RC1 test',
            '--environment',
            'isolated-test',
        ]
    )

    assert exit_code == 0
    markdown = output_path.read_text(encoding='utf-8')
    assert '# Beta SLO Baseline' in markdown
    assert '- RC or release: RC1 test' in markdown
    assert '- Environment: isolated-test' in markdown
    assert '- Target URL: isolated local runtime' in markdown
    assert '| DM response p95 latency | 640 ms | `/api/beta/slo` |  |' in markdown
    assert '| AI provider failure rate | 50.00% | `/api/beta/slo` |  |' in markdown
    assert '| Bad-turn reports by provider/model | gemini/gemini-2.5-pro: 1 | `/api/beta/incidents` |  |' in markdown

    slo_payload = json.loads(slo_json_path.read_text(encoding='utf-8'))
    incidents_payload = json.loads(incidents_json_path.read_text(encoding='utf-8'))
    assert slo_payload['dm_response_latency_ms_p95'] == 640.0
    assert slo_payload['dm_response_latency_sample_count'] == 2
    assert slo_payload['socket_unauthorized_event_count'] == 1
    assert slo_payload['socket_rate_limited_event_count'] == 1
    assert incidents_payload['summary']['bad_turn_report_count'] == 1
    assert incidents_payload['summary']['failed_turn_count'] == 1
    assert incidents_payload['summary']['failed_canon_job_count'] == 1

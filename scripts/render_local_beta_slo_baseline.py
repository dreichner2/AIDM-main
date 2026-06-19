#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.render_beta_slo_baseline import render_baseline, write_baseline
except ModuleNotFoundError:  # pragma: no cover - exercised when run as a script path
    from render_beta_slo_baseline import render_baseline, write_baseline  # type: ignore[no-redef]


DEFAULT_OUTPUT = Path('tmp/release/beta-slo-baseline.md')
DEFAULT_SLO_JSON_OUTPUT = Path('tmp/release/beta-slo.json')
DEFAULT_INCIDENTS_JSON_OUTPUT = Path('tmp/release/beta-incidents.json')
LOCAL_TARGET_URL = 'isolated local runtime'


def _repo_root() -> Path:
    return REPO_ROOT


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _git_commit() -> str:
    result = subprocess.run(
        ('git', 'rev-parse', '--short', 'HEAD'),
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else 'unknown'


def configure_isolated_runtime(db_path: Path) -> None:
    env_defaults = {
        'PYTHON_DOTENV_DISABLED': '1',
        'AIDM_DATABASE_URI': f'sqlite:///{db_path}',
        'AIDM_AUTO_CREATE_SCHEMA': 'true',
        'AIDM_ENV': 'test',
        'AIDM_DEBUG': 'false',
        'AIDM_AUTH_REQUIRED': 'false',
        'AIDM_CORS_ALLOWLIST': 'http://localhost',
        'AIDM_SOCKET_CORS_ALLOWLIST': 'http://localhost',
        'AIDM_SOCKETIO_ASYNC_MODE': 'threading',
        'AIDM_SOCKETIO_WORKER_MODEL': 'single',
        'AIDM_TELEMETRY_ENABLED': 'false',
        'AIDM_OBSERVABILITY_PROVIDER': 'local telemetry fixture',
        'AIDM_ALERT_OWNER': 'local evidence only',
        'AIDM_RATE_LIMIT_MAX_API_REQUESTS': '1000',
        'AIDM_RATE_LIMIT_MAX_SOCKET_MESSAGES': '1000',
        'AIDM_LLM_PROVIDER': 'fallback',
        'AIDM_LLM_MODEL': 'fallback-local-baseline',
        'GOOGLE_GENAI_API_KEY': '',
        'AIDM_NVIDIA_API_KEY': '',
        'NVIDIA_API_KEY': '',
    }
    for key, value in env_defaults.items():
        os.environ[key] = value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _seed_world_campaign_player_session(db, models) -> dict[str, int]:
    world = models.World(name='Local RC SLO World', description='Isolated beta SLO fixture')
    db.session.add(world)
    db.session.flush()

    campaign = models.Campaign(
        title='Local RC SLO Campaign',
        description='Representative observability fixture for local RC evidence.',
        world_id=world.world_id,
        current_quest='Prove beta observability surfaces',
        location='Observability Hall',
    )
    db.session.add(campaign)
    db.session.flush()

    player = models.Player(
        campaign_id=campaign.campaign_id,
        name='Beta Tester',
        character_name='Seraphina',
        race='Elf',
        class_='Ranger',
        level=3,
    )
    db.session.add(player)
    db.session.flush()

    session = models.Session(campaign_id=campaign.campaign_id)
    db.session.add(session)
    db.session.commit()

    return {
        'world_id': world.world_id,
        'campaign_id': campaign.campaign_id,
        'player_id': player.player_id,
        'session_id': session.session_id,
    }


def seed_baseline_data(app) -> dict[str, int]:
    from aidm_server.database import db
    from aidm_server import models
    from aidm_server.telemetry import telemetry_event

    with app.app_context():
        ids = _seed_world_campaign_player_session(db, models)
        completed_turn = models.DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I examine the glowing door.',
            dm_output='The runes pulse in a steady rhythm.',
            requires_roll=False,
            rule_type='exploration',
            confidence=0.9,
            outcome_status='resolved',
            status='completed',
            latency_ms=180,
            llm_provider='gemini',
            llm_model='gemini-2.5-pro',
            completed_at=datetime.now(UTC),
        )
        failed_turn = models.DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I force the sealed vault.',
            dm_output='',
            requires_roll=True,
            rule_type='athletics',
            confidence=0.65,
            outcome_status='resolved',
            status='failed',
            latency_ms=640,
            llm_provider='gemini',
            llm_model='gemini-2.5-pro',
        )
        db.session.add_all([completed_turn, failed_turn])
        db.session.flush()
        db.session.add_all(
            [
                models.CanonJob(
                    turn_id=completed_turn.turn_id,
                    session_id=ids['session_id'],
                    campaign_id=ids['campaign_id'],
                    status='applied',
                ),
                models.CanonJob(
                    turn_id=failed_turn.turn_id,
                    session_id=ids['session_id'],
                    campaign_id=ids['campaign_id'],
                    status='failed',
                    error_text='local baseline extractor timeout',
                ),
            ]
        )
        session_obj = db.session.get(models.Session, ids['session_id'])
        session_obj.state_snapshot = models.safe_json_dumps(
            {'revision': 2, 'scene': {'location': 'Observability Hall'}},
            {},
        )
        db.session.add(
            models.SessionLogEntry(
                session_id=ids['session_id'],
                entry_type='system',
                message='Local beta SLO baseline fixture recorded a failed turn for operator review.',
                metadata_json=models.safe_json_dumps({'turn_id': failed_turn.turn_id}, {}),
            )
        )
        db.session.add(
            models.TurnEvent(
                session_id=ids['session_id'],
                campaign_id=ids['campaign_id'],
                turn_id=failed_turn.turn_id,
                player_id=ids['player_id'],
                event_type='turn.failed',
                payload_json=models.safe_json_dumps({'reason': 'local baseline fixture'}, {}),
            )
        )
        db.session.commit()

        ids['completed_turn_id'] = completed_turn.turn_id
        ids['failed_turn_id'] = failed_turn.turn_id

        telemetry_event('socket.join.unauthorized')
        telemetry_event('socket.send_message.rate_limited')
        telemetry_event('socket.dm_persist_failed')

    return ids


def capture_baseline_payloads(app, ids: dict[str, int]) -> tuple[dict[str, Any], dict[str, Any]]:
    client = app.test_client()
    coherence_response = client.post(
        '/api/feedback/coherence',
        json={
            'session_id': ids['session_id'],
            'turn_id': ids['completed_turn_id'],
            'coherence_score': 4,
            'category': 'local_rc_baseline',
            'fun_score': 4,
            'rules_score': 3,
            'notes': 'Representative local RC baseline feedback.',
        },
    )
    if coherence_response.status_code != 201:
        raise RuntimeError(f'coherence feedback seed failed: {coherence_response.status_code} {coherence_response.get_data(as_text=True)}')

    bad_turn_response = client.post(
        '/api/feedback/bad-turn',
        json={
            'session_id': ids['session_id'],
            'turn_id': ids['failed_turn_id'],
            'category': 'rules',
            'notes': 'Representative bad-turn report for local RC baseline.',
        },
    )
    if bad_turn_response.status_code != 201:
        raise RuntimeError(f'bad-turn feedback seed failed: {bad_turn_response.status_code} {bad_turn_response.get_data(as_text=True)}')

    slo_response = client.get('/api/beta/slo')
    if slo_response.status_code != 200:
        raise RuntimeError(f'/api/beta/slo failed: {slo_response.status_code} {slo_response.get_data(as_text=True)}')
    incidents_response = client.get('/api/beta/incidents?limit=25')
    if incidents_response.status_code != 200:
        raise RuntimeError(
            f'/api/beta/incidents failed: {incidents_response.status_code} {incidents_response.get_data(as_text=True)}'
        )

    slo_payload = slo_response.get_json()
    incidents_payload = incidents_response.get_json()
    if not isinstance(slo_payload, dict) or not isinstance(incidents_payload, dict):
        raise RuntimeError('local beta SLO endpoints did not return JSON objects.')
    return slo_payload, incidents_payload


def build_isolated_baseline(
    *,
    output: Path,
    slo_json_output: Path,
    incidents_json_output: Path,
    release: str,
    environment: str,
    evidence_report: str,
) -> Path:
    with tempfile.TemporaryDirectory(prefix='aidm-local-beta-slo-') as tmp:
        db_path = Path(tmp) / 'local-beta-slo.sqlite'
        configure_isolated_runtime(db_path)

        from aidm_server.database import ensure_schema
        from aidm_server.main import create_app

        app = create_app()
        ensure_schema(app)
        ids = seed_baseline_data(app)
        slo_payload, incidents_payload = capture_baseline_payloads(app, ids)

    _write_json(slo_json_output, slo_payload)
    _write_json(incidents_json_output, incidents_payload)

    markdown = render_baseline(
        slo=slo_payload,
        incidents=incidents_payload,
        generated_at=_iso_now(),
        release=release,
        commit_sha=_git_commit(),
        environment=environment,
        target_url=LOCAL_TARGET_URL,
        socketio_worker_model='single',
        database='isolated sqlite',
        llm_provider_model='fallback/fallback-local-baseline',
        observability_provider='local telemetry fixture',
        alert_owner='local evidence only',
        evidence_report=evidence_report,
    )
    return write_baseline(markdown, output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Render a local-only beta SLO baseline from an isolated Flask runtime fixture.'
    )
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT, help=f'Markdown output path. Default: {DEFAULT_OUTPUT}.')
    parser.add_argument(
        '--slo-json-output',
        type=Path,
        default=DEFAULT_SLO_JSON_OUTPUT,
        help=f'Raw /api/beta/slo JSON output path. Default: {DEFAULT_SLO_JSON_OUTPUT}.',
    )
    parser.add_argument(
        '--incidents-json-output',
        type=Path,
        default=DEFAULT_INCIDENTS_JSON_OUTPUT,
        help=f'Raw /api/beta/incidents JSON output path. Default: {DEFAULT_INCIDENTS_JSON_OUTPUT}.',
    )
    parser.add_argument('--release', default='RC1 local evidence', help='RC or release label to render.')
    parser.add_argument('--environment', default='isolated-local-rc', help='Environment label to render.')
    parser.add_argument('--evidence-report', default='tmp/release/rc-evidence.md', help='Related evidence report path to render.')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output_path = build_isolated_baseline(
            output=args.output,
            slo_json_output=args.slo_json_output,
            incidents_json_output=args.incidents_json_output,
            release=args.release,
            environment=args.environment,
            evidence_report=args.evidence_report,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f'Wrote local beta SLO baseline: {output_path}')
    print(f'Wrote local beta SLO JSON: {args.slo_json_output}')
    print(f'Wrote local beta incidents JSON: {args.incidents_json_output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

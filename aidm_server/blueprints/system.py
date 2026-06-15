from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from math import ceil
import os
import time

import requests
from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from sqlalchemy import func

from aidm_server.capabilities import CAPABILITY_DESCRIPTIONS, capability_forbidden_response, current_actor_capabilities
from aidm_server.database import db
from aidm_server.errors import error_response
from aidm_server.http_client import post as http_post
from aidm_server.http_client import timeout_from_config
from aidm_server.models import (
    Campaign,
    CanonJob,
    DmCoherenceFeedback,
    DmTurn,
    OperatorActionAudit,
    Session,
    SessionStateMutationAudit,
    safe_json_dumps,
    safe_json_loads,
)
from aidm_server.services.runtime_config import current_llm_payload
from aidm_server.telemetry import get_telemetry, prometheus_text_from_snapshot, telemetry_event, telemetry_metric, telemetry_timing
from aidm_server.text_sanitization import normalize_tts_text
from aidm_server.validation import coerce_int, missing_fields, optional_text, parse_json_body
from aidm_server.workspace_access import current_account_id, current_account_is_workspace_admin, current_workspace_id, get_session as workspace_session

system_bp = Blueprint('system', __name__)

DEEPGRAM_SPEAK_URL = 'https://api.deepgram.com/v1/speak'
DEEPGRAM_CHUNK_LIMIT = 2000
DEEPGRAM_FIRST_CHUNK_LIMIT = 360
TTS_MAX_CHARS = 6000
BAD_TURN_CATEGORIES = {'continuity', 'rules', 'latency', 'safety', 'state', 'other'}
TELEMETRY_INCIDENT_EVENT_NAMES = (
    'socket.dm_generation_failed',
    'socket.dm_persist_failed',
    'socket.turn_failed',
    'socket.state_pipeline.post_dm_failed',
    'socket.state_pipeline.pre_dm_failed',
)


def _deepgram_api_key() -> str:
    return str(
        current_app.config.get('AIDM_DEEPGRAM_API_KEY')
        or os.getenv('AIDM_DEEPGRAM_API_KEY')
        or os.getenv('DEEPGRAM_API_KEY')
        or ''
    ).strip()


def _tts_model() -> str:
    return str(
        current_app.config.get('AIDM_DEEPGRAM_TTS_MODEL')
        or os.getenv('AIDM_DEEPGRAM_TTS_MODEL')
        or 'aura-2-draco-en'
    ).strip()


def _tts_config_payload() -> dict:
    connect_timeout, read_timeout = _tts_timeout()
    return {
        'provider': 'deepgram',
        'configured': bool(_deepgram_api_key()),
        'model': _tts_model(),
        'connect_timeout_seconds': connect_timeout,
        'read_timeout_seconds': read_timeout,
    }


def _isoformat(value) -> str | None:
    return value.isoformat() if value else None


def _turn_feedback_payload(feedback: DmCoherenceFeedback, turn: DmTurn | None = None) -> dict:
    turn_obj = turn if turn is not None else feedback.turn
    return {
        'feedback_id': feedback.feedback_id,
        'session_id': feedback.session_id,
        'turn_id': feedback.turn_id,
        'feedback_type': feedback.feedback_type or 'coherence',
        'category': feedback.category,
        'coherence_score': feedback.coherence_score,
        'notes': feedback.notes,
        'provider': feedback.provider or (turn_obj.llm_provider if turn_obj else None),
        'model': feedback.model or (turn_obj.llm_model if turn_obj else None),
        'turn_status': turn_obj.status if turn_obj else None,
        'turn_latency_ms': turn_obj.latency_ms if turn_obj else None,
        'created_at': _isoformat(feedback.created_at),
    }


def _bad_turn_category(value) -> str:
    if not isinstance(value, str):
        return 'other'
    normalized = value.strip().lower().replace('-', '_')
    return normalized if normalized in BAD_TURN_CATEGORIES else 'other'


def _validate_score(value, *, default: int | None = None) -> tuple[int | None, str | None]:
    if value in (None, '') and default is not None:
        return default, None
    try:
        score = int(value)
    except (TypeError, ValueError):
        return None, 'coherence_score must be an integer between 1 and 5.'
    if score < 1 or score > 5:
        return None, 'coherence_score must be an integer between 1 and 5.'
    return score, None


def _telemetry_incident_counts() -> list[dict]:
    telemetry_client = get_telemetry()
    snapshot = telemetry_client.snapshot() if telemetry_client else {'counters': {}}
    counters = snapshot.get('counters') if isinstance(snapshot.get('counters'), dict) else {}
    incidents = []
    for event_name in TELEMETRY_INCIDENT_EVENT_NAMES:
        count = _telemetry_counter_total({'counters': counters}, prefix=f'event.{event_name}')
        if not count:
            continue
        incidents.append(
            {
                'type': 'telemetry_event',
                'event_name': event_name,
                'count': count,
                'severity': 'high' if event_name in {'socket.dm_persist_failed', 'socket.turn_failed'} else 'medium',
                'message': f'{event_name} recorded {count} time{"s" if count != 1 else ""}.',
            }
        )
    return incidents


def _tts_timeout() -> tuple[float, float]:
    return timeout_from_config(
        'AIDM_DEEPGRAM_TTS',
        default_connect=3.0,
        default_read=60.0,
    )


@system_bp.route('/health', methods=['GET'])
def health_check():
    telemetry_metric('system.health.requests_total', 1)
    return jsonify(
        {
            'status': 'ok',
            'service': 'ai-dm',
            'env': current_app.config.get('AIDM_ENV', 'unknown'),
            'auth_required': bool(current_app.config.get('AIDM_AUTH_REQUIRED', False)),
            'rules_engine_enabled': bool(current_app.config.get('AIDM_RULES_ENGINE_ENABLED', True)),
            'segment_evaluator_enabled': bool(current_app.config.get('AIDM_SEGMENT_EVALUATOR_ENABLED', True)),
            'llm': current_llm_payload(),
        }
    )


@system_bp.route('/metrics', methods=['GET'])
def metrics_snapshot():
    telemetry_metric('system.metrics.requests_total', 1)
    client = get_telemetry()
    snapshot = client.snapshot() if client else {'enabled': False, 'counters': {}, 'timings': {}}
    snapshot['beta'] = _beta_summary()
    return jsonify(snapshot)


@system_bp.route('/metrics/prometheus', methods=['GET'])
def metrics_prometheus():
    telemetry_metric('system.metrics_prometheus.requests_total', 1)
    client = get_telemetry()
    snapshot = client.snapshot() if client else {'enabled': False, 'counters': {}, 'timings': {}}
    beta_summary = _beta_summary()
    beta_gauges = {f'beta.{key}': value for key, value in beta_summary.items() if value is not None}
    return Response(
        prometheus_text_from_snapshot(snapshot, extra_gauges=beta_gauges),
        content_type='text/plain; version=0.0.4; charset=utf-8',
    )


@system_bp.route('/tts/config', methods=['GET'])
def tts_config():
    telemetry_metric('system.tts_config.requests_total', 1)
    return jsonify(_tts_config_payload())


@system_bp.route('/capabilities', methods=['GET'])
def actor_capabilities():
    telemetry_metric('system.capabilities.requests_total', 1)
    capabilities = sorted(current_actor_capabilities())
    return jsonify(
        {
            'workspace_id': current_workspace_id(),
            'account_id': current_account_id(),
            'is_workspace_admin': current_account_is_workspace_admin(),
            'capabilities': capabilities,
            'descriptions': {
                capability: CAPABILITY_DESCRIPTIONS[capability]
                for capability in capabilities
                if capability in CAPABILITY_DESCRIPTIONS
            },
        }
    )


def _chunk_text_for_tts(
    text: str,
    max_chars: int = DEEPGRAM_CHUNK_LIMIT,
    first_chunk_chars: int = DEEPGRAM_FIRST_CHUNK_LIMIT,
) -> list[str]:
    """Split *text* into chunks of at most *max_chars* characters.

    Tries to split on sentence boundaries (`.`, `!`, `?`) first, then falls
    back to the nearest space so words are not cut in the middle.
    """
    chunks: list[str] = []
    chunk_index = 0
    while text:
        chunk_limit = min(max_chars, first_chunk_chars) if chunk_index == 0 else max_chars
        if len(text) <= chunk_limit:
            chunks.append(text)
            break
        # Try to find a sentence-ending punctuation near the limit.
        split_at = -1
        for sep in ('.', '!', '?'):
            idx = text.rfind(sep, 0, chunk_limit)
            if idx > split_at:
                split_at = idx
        if split_at > 0:
            split_at += 1  # include the punctuation
        else:
            # Fall back to the last space before the limit.
            split_at = text.rfind(' ', 0, chunk_limit)
        if split_at <= 0:
            split_at = chunk_limit  # hard cut as last resort
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
        chunk_index += 1
    return [c for c in chunks if c]


def _deepgram_tts_request(api_key: str, model: str, text: str, *, stream: bool = False) -> requests.Response:
    """Make a single Deepgram TTS request."""
    return http_post(
        'deepgram_tts',
        DEEPGRAM_SPEAK_URL,
        params={'model': model, 'encoding': 'mp3'},
        headers={
            'Authorization': f'Token {api_key}',
            'Content-Type': 'application/json',
        },
        json={'text': text},
        stream=stream,
        timeout=_tts_timeout(),
    )


def _record_tts_phase_timing(phase: str, started_at: float, *, model: str) -> None:
    telemetry_timing(
        'system.tts_phase_latency_ms',
        float((time.perf_counter() - started_at) * 1000),
        tags={'model': model, 'phase': phase},
    )


def _iter_tts_response_content(
    upstream: requests.Response,
    *,
    first_audio_started_at: float | None = None,
    model: str | None = None,
):
    first_audio_recorded = False
    for audio_chunk in upstream.iter_content(chunk_size=1024):
        if audio_chunk:
            if not first_audio_recorded and first_audio_started_at is not None and model:
                _record_tts_phase_timing('first_audio_byte', first_audio_started_at, model=model)
                first_audio_recorded = True
            yield audio_chunk


def _deepgram_tts_request_in_app(app, api_key: str, model: str, text: str) -> requests.Response:
    with app.app_context():
        return _deepgram_tts_request(api_key, model, text, stream=True)


def _log_tts_chunk_failure(
    *,
    model: str,
    error: str | None = None,
    upstream: requests.Response | None = None,
) -> None:
    telemetry_metric('system.tts_speak.chunk_failures_total', 1)
    if upstream is not None:
        detail = upstream.text[:500] if upstream.text else ''
        telemetry_event(
            'system.tts_speak.chunk_failed_after_stream_start',
            payload={
                'model': model,
                'status_code': upstream.status_code,
                'detail': detail,
            },
            severity='error',
        )
        current_app.logger.warning(
            'Deepgram TTS chunk failed while streaming: status=%s detail=%s',
            upstream.status_code,
            detail,
        )
        return

    telemetry_event(
        'system.tts_speak.chunk_failed_after_stream_start',
        payload={'model': model, 'error': error or 'Unknown error'},
        severity='error',
    )
    current_app.logger.warning('Deepgram TTS chunk request failed while streaming: %s', error or 'Unknown error')


def _resolve_prefetched_tts_chunk(future: Future, *, model: str) -> requests.Response | None:
    try:
        upstream = future.result()
    except requests.RequestException as exc:
        _log_tts_chunk_failure(model=model, error=str(exc))
        return None
    except Exception as exc:  # pragma: no cover - defensive boundary for worker failures
        _log_tts_chunk_failure(model=model, error=str(exc))
        return None
    if not upstream.ok:
        _log_tts_chunk_failure(model=model, upstream=upstream)
        upstream.close()
        return None
    return upstream


def _stream_tts_chunks(
    first_upstream: requests.Response,
    remaining_chunks: list[str],
    *,
    api_key: str,
    model: str,
    first_audio_started_at: float | None = None,
):
    app = current_app._get_current_object()
    executor: ThreadPoolExecutor | None = None
    pending_future: Future | None = None
    upstream: requests.Response | None = first_upstream

    def schedule_next_chunk() -> None:
        nonlocal executor, pending_future
        if pending_future is not None or not remaining_chunks:
            return
        if executor is None:
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='aidm-tts-prefetch')
        next_chunk = remaining_chunks.pop(0)
        telemetry_metric('system.tts_speak.prefetch_requests_total', 1)
        pending_future = executor.submit(_deepgram_tts_request_in_app, app, api_key, model, next_chunk)

    try:
        while upstream is not None:
            schedule_next_chunk()
            yield from _iter_tts_response_content(
                upstream,
                first_audio_started_at=first_audio_started_at,
                model=model,
            )
            first_audio_started_at = None
            upstream.close()
            upstream = None

            if pending_future is None:
                break
            prefetched_future = pending_future
            pending_future = None
            upstream = _resolve_prefetched_tts_chunk(prefetched_future, model=model)
            if upstream is None:
                break
    finally:
        if upstream is not None:
            upstream.close()
        if pending_future is not None:
            if pending_future.done():
                prefetched_upstream = _resolve_prefetched_tts_chunk(pending_future, model=model)
                if prefetched_upstream is not None:
                    prefetched_upstream.close()
            else:
                pending_future.cancel()
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


@system_bp.route('/tts/speak', methods=['POST'])
@system_bp.route('/tts/stream', methods=['POST'])
def speak_text():
    telemetry_metric('system.tts_speak.requests_total', 1)
    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    text = normalize_tts_text(str(payload.get('text') or ''))
    if not text:
        return error_response('validation_error', 'Text is required.', 400)
    if len(text) > TTS_MAX_CHARS:
        return error_response(
            'validation_error',
            f'Text must be {TTS_MAX_CHARS} characters or fewer.',
            400,
            {'max_chars': TTS_MAX_CHARS},
        )

    api_key = _deepgram_api_key()
    if not api_key:
        return error_response('tts_not_configured', 'Deepgram TTS is missing its API key.', 503)

    model = _tts_model()
    chunks = _chunk_text_for_tts(text)
    telemetry_metric('system.tts_speak.chunks_total', len(chunks))

    tts_request_started = time.perf_counter()
    try:
        first_upstream = _deepgram_tts_request(api_key, model, chunks[0], stream=True)
    except requests.RequestException as exc:
        _record_tts_phase_timing('request', tts_request_started, model=model)
        return error_response('tts_request_failed', f'Deepgram TTS request failed: {exc}', 502)
    _record_tts_phase_timing('request', tts_request_started, model=model)

    if not first_upstream.ok:
        detail = first_upstream.text[:500] if first_upstream.text else f'HTTP {first_upstream.status_code}'
        first_upstream.close()
        return error_response(
            'tts_request_failed',
            f'Deepgram TTS request failed (HTTP {first_upstream.status_code}): {detail}',
            502,
            {'status_code': first_upstream.status_code, 'detail': detail},
        )

    content_type = first_upstream.headers.get('Content-Type') or 'audio/mpeg'
    response = Response(
        stream_with_context(
            _stream_tts_chunks(
                first_upstream,
                chunks[1:],
                api_key=api_key,
                model=model,
                first_audio_started_at=tts_request_started,
            ),
        ),
        mimetype=content_type,
        direct_passthrough=True,
    )
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['X-AIDM-TTS-Provider'] = 'deepgram'
    response.headers['X-AIDM-TTS-Model'] = model
    response.headers['X-AIDM-TTS-Chunk-Count'] = str(len(chunks))
    response.headers['X-AIDM-TTS-First-Chunk-Chars'] = str(len(chunks[0]) if chunks else 0)
    response.headers['X-AIDM-TTS-Prefetch'] = 'enabled' if len(chunks) > 1 else 'not-needed'
    return response


def _beta_summary() -> dict:
    workspace_id = current_workspace_id()
    turns_query = db.session.query(DmTurn).join(Campaign, DmTurn.campaign_id == Campaign.campaign_id).filter(
        Campaign.workspace_id == workspace_id,
    )
    total_turns = turns_query.with_entities(func.count(DmTurn.turn_id)).scalar() or 0
    failed_turns = turns_query.filter(DmTurn.status == 'failed').with_entities(func.count(DmTurn.turn_id)).scalar() or 0
    avg_turn_latency = turns_query.with_entities(func.avg(DmTurn.latency_ms)).scalar()

    sessions_query = db.session.query(Session).join(Campaign, Session.campaign_id == Campaign.campaign_id).filter(
        Campaign.workspace_id == workspace_id,
    )
    total_sessions = sessions_query.with_entities(func.count(Session.session_id)).scalar() or 0
    completed_sessions = (
        sessions_query.filter(Session.state_snapshot.isnot(None)).with_entities(func.count(Session.session_id)).scalar() or 0
    )

    feedback_query = (
        db.session.query(DmCoherenceFeedback)
        .join(Session, DmCoherenceFeedback.session_id == Session.session_id)
        .join(Campaign, Session.campaign_id == Campaign.campaign_id)
        .filter(Campaign.workspace_id == workspace_id)
    )
    feedback_count = feedback_query.with_entities(func.count(DmCoherenceFeedback.feedback_id)).scalar() or 0
    avg_feedback = feedback_query.with_entities(func.avg(DmCoherenceFeedback.coherence_score)).scalar()

    return {
        'turn_latency_ms_avg': float(avg_turn_latency) if avg_turn_latency is not None else None,
        'ai_failure_rate': (failed_turns / total_turns) if total_turns else 0.0,
        'session_completion_rate': (completed_sessions / total_sessions) if total_sessions else 0.0,
        'coherence_feedback_avg': float(avg_feedback) if avg_feedback is not None else None,
        'coherence_feedback_count': feedback_count,
        'total_turns': total_turns,
        'total_sessions': total_sessions,
    }


def _percentile(values: list[int], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(int(value) for value in values)
    index = max(0, min(len(ordered) - 1, ceil((percentile / 100) * len(ordered)) - 1))
    return float(ordered[index])


def _telemetry_counter_total(snapshot: dict, *, prefix: str, suffix: str | None = None) -> int:
    counters = snapshot.get('counters') if isinstance(snapshot.get('counters'), dict) else {}
    total = 0
    for key, value in counters.items():
        metric_name = str(key).partition('|')[0]
        if not metric_name.startswith(prefix):
            continue
        if suffix and not metric_name.endswith(suffix):
            continue
        try:
            total += int(value)
        except (TypeError, ValueError):
            continue
    return total


def _beta_slo_summary() -> dict:
    workspace_id = current_workspace_id()
    turns_query = db.session.query(DmTurn).join(Campaign, DmTurn.campaign_id == Campaign.campaign_id).filter(
        Campaign.workspace_id == workspace_id,
    )
    total_turns = turns_query.with_entities(func.count(DmTurn.turn_id)).scalar() or 0
    failed_turns = turns_query.filter(DmTurn.status == 'failed').with_entities(func.count(DmTurn.turn_id)).scalar() or 0
    latency_values = [
        int(row[0])
        for row in turns_query.filter(DmTurn.latency_ms.isnot(None)).with_entities(DmTurn.latency_ms).all()
        if row[0] is not None
    ]

    canon_jobs_query = db.session.query(CanonJob).join(Campaign, CanonJob.campaign_id == Campaign.campaign_id).filter(
        Campaign.workspace_id == workspace_id,
    )
    canon_job_count = canon_jobs_query.with_entities(func.count(CanonJob.job_id)).scalar() or 0
    canon_job_failed_count = (
        canon_jobs_query.filter(CanonJob.status == 'failed').with_entities(func.count(CanonJob.job_id)).scalar() or 0
    )

    feedback_query = (
        db.session.query(DmCoherenceFeedback)
        .join(Session, DmCoherenceFeedback.session_id == Session.session_id)
        .join(Campaign, Session.campaign_id == Campaign.campaign_id)
        .filter(Campaign.workspace_id == workspace_id)
    )
    feedback_count = feedback_query.with_entities(func.count(DmCoherenceFeedback.feedback_id)).scalar() or 0
    avg_feedback = feedback_query.with_entities(func.avg(DmCoherenceFeedback.coherence_score)).scalar()

    provider_model_rows = (
        turns_query.with_entities(DmTurn.llm_provider, DmTurn.llm_model, func.count(DmTurn.turn_id))
        .group_by(DmTurn.llm_provider, DmTurn.llm_model)
        .order_by(func.count(DmTurn.turn_id).desc())
        .all()
    )
    provider_model_counts = [
        {
            'provider': provider or 'unknown',
            'model': model or 'unknown',
            'turn_count': count,
        }
        for provider, model, count in provider_model_rows
    ]

    telemetry_client = get_telemetry()
    telemetry_snapshot = telemetry_client.snapshot() if telemetry_client else {'counters': {}}
    socket_unauthorized_count = _telemetry_counter_total(telemetry_snapshot, prefix='event.socket.', suffix='.unauthorized')
    socket_unauthorized_count += _telemetry_counter_total(
        telemetry_snapshot,
        prefix='event.socket.',
        suffix='.admin_unauthorized',
    )
    socket_rate_limited_count = _telemetry_counter_total(telemetry_snapshot, prefix='event.socket.', suffix='.rate_limited')

    return {
        'dm_response_latency_ms_p95': _percentile(latency_values, 95),
        'dm_response_latency_sample_count': len(latency_values),
        'ai_provider_failure_rate': (failed_turns / total_turns) if total_turns else 0.0,
        'turn_persistence_failure_rate': (failed_turns / total_turns) if total_turns else 0.0,
        'failed_turn_count': failed_turns,
        'total_turn_count': total_turns,
        'canon_job_failure_rate': (canon_job_failed_count / canon_job_count) if canon_job_count else 0.0,
        'canon_job_failed_count': canon_job_failed_count,
        'canon_job_count': canon_job_count,
        'socket_unauthorized_event_count': socket_unauthorized_count,
        'socket_rate_limited_event_count': socket_rate_limited_count,
        'coherence_feedback_avg': float(avg_feedback) if avg_feedback is not None else None,
        'coherence_feedback_count': feedback_count,
        'provider_model_turn_counts': provider_model_counts,
    }


@system_bp.route('/feedback/coherence', methods=['POST'])
def submit_coherence_feedback():
    telemetry_metric('system.feedback.requests_total', 1)
    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    required = missing_fields(payload, ['session_id', 'coherence_score'])
    if required:
        return error_response('validation_error', 'Missing required fields.', 400, {'missing_fields': required})

    session_id = coerce_int(payload.get('session_id'))
    turn_id = coerce_int(payload.get('turn_id'))
    score, score_error = _validate_score(payload.get('coherence_score'))
    if score_error:
        return error_response('validation_error', score_error, 400)
    notes, notes_error = optional_text(payload.get('notes'), max_length=2000, field='notes', default=None)
    if notes_error:
        return error_response('validation_error', notes_error, 400)

    session_obj = workspace_session(session_id)
    if not session_obj:
        return error_response('session_not_found', 'Session not found.', 404)

    turn_obj = None
    if turn_id is not None:
        turn_obj = db.session.get(DmTurn, turn_id)
        if not turn_obj or turn_obj.session_id != session_obj.session_id:
            return error_response('turn_not_found', 'Turn not found for this session.', 404)

    feedback = DmCoherenceFeedback(
        session_id=session_obj.session_id,
        turn_id=turn_id,
        feedback_type='coherence',
        category='coherence',
        coherence_score=score,
        provider=turn_obj.llm_provider if turn_obj else None,
        model=turn_obj.llm_model if turn_obj else None,
        notes=notes,
    )
    db.session.add(feedback)
    db.session.commit()
    telemetry_metric('system.feedback.submitted_total', 1)

    return jsonify({'feedback_id': feedback.feedback_id}), 201


@system_bp.route('/feedback/bad-turn', methods=['POST'])
def submit_bad_turn_feedback():
    telemetry_metric('system.feedback.bad_turn.requests_total', 1)
    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    required = missing_fields(payload, ['session_id', 'turn_id'])
    if required:
        return error_response('validation_error', 'Missing required fields.', 400, {'missing_fields': required})

    session_id = coerce_int(payload.get('session_id'))
    turn_id = coerce_int(payload.get('turn_id'))
    if not session_id or not turn_id:
        return error_response('validation_error', 'session_id and turn_id must be positive integers.', 400)

    notes, notes_error = optional_text(payload.get('notes'), max_length=2000, field='notes', default='')
    if notes_error:
        return error_response('validation_error', notes_error, 400)
    score, score_error = _validate_score(payload.get('coherence_score'), default=1)
    if score_error:
        return error_response('validation_error', score_error, 400)
    category = _bad_turn_category(payload.get('category'))

    session_obj = workspace_session(session_id)
    if not session_obj:
        return error_response('session_not_found', 'Session not found.', 404)

    turn_obj = db.session.get(DmTurn, turn_id)
    if not turn_obj or turn_obj.session_id != session_obj.session_id:
        return error_response('turn_not_found', 'Turn not found for this session.', 404)

    feedback = DmCoherenceFeedback(
        session_id=session_obj.session_id,
        turn_id=turn_obj.turn_id,
        feedback_type='bad_turn',
        category=category,
        coherence_score=score,
        provider=turn_obj.llm_provider,
        model=turn_obj.llm_model,
        notes=notes,
        metadata_json=safe_json_dumps(
            {
                'turn_status': turn_obj.status,
                'turn_latency_ms': turn_obj.latency_ms,
                'reported_by_account_id': current_account_id(),
                'reported_by_workspace_admin': current_account_is_workspace_admin(),
            },
            {},
        ),
    )
    db.session.add(feedback)
    db.session.commit()
    telemetry_metric('system.feedback.bad_turn.submitted_total', 1)
    telemetry_event(
        'system.feedback.bad_turn.submitted',
        payload={
            'session_id': session_obj.session_id,
            'turn_id': turn_obj.turn_id,
            'category': category,
            'provider': turn_obj.llm_provider,
            'model': turn_obj.llm_model,
        },
    )

    return jsonify({'feedback': _turn_feedback_payload(feedback, turn_obj)}), 201


@system_bp.route('/beta/summary', methods=['GET'])
def beta_summary():
    telemetry_metric('system.beta_summary.requests_total', 1)
    return jsonify(_beta_summary())


@system_bp.route('/beta/slo', methods=['GET'])
def beta_slo_summary():
    telemetry_metric('system.beta_slo.requests_total', 1)
    return jsonify(_beta_slo_summary())


@system_bp.route('/beta/incidents', methods=['GET'])
def beta_incidents():
    forbidden = capability_forbidden_response('debug_read', 'Only workspace admins can inspect beta incidents.')
    if forbidden:
        return forbidden

    telemetry_metric('system.beta_incidents.requests_total', 1)
    limit = coerce_int(request.args.get('limit'), 25)
    limit = max(1, min(limit or 25, 100))
    workspace_id = current_workspace_id()

    turns_query = db.session.query(DmTurn).join(Campaign, DmTurn.campaign_id == Campaign.campaign_id).filter(
        Campaign.workspace_id == workspace_id,
    )
    failed_turns = (
        turns_query.filter(DmTurn.status == 'failed')
        .order_by(DmTurn.created_at.desc(), DmTurn.turn_id.desc())
        .limit(limit)
        .all()
    )

    canon_jobs_query = db.session.query(CanonJob).join(Campaign, CanonJob.campaign_id == Campaign.campaign_id).filter(
        Campaign.workspace_id == workspace_id,
    )
    failed_canon_jobs = (
        canon_jobs_query.filter(CanonJob.status == 'failed')
        .order_by(CanonJob.updated_at.desc(), CanonJob.job_id.desc())
        .limit(limit)
        .all()
    )

    feedback_query = (
        db.session.query(DmCoherenceFeedback)
        .join(Session, DmCoherenceFeedback.session_id == Session.session_id)
        .join(Campaign, Session.campaign_id == Campaign.campaign_id)
        .filter(Campaign.workspace_id == workspace_id)
    )
    bad_turn_reports = (
        feedback_query.filter(DmCoherenceFeedback.feedback_type == 'bad_turn')
        .order_by(DmCoherenceFeedback.created_at.desc(), DmCoherenceFeedback.feedback_id.desc())
        .limit(limit)
        .all()
    )

    incidents = []
    for turn in failed_turns:
        incidents.append(
            {
                'type': 'failed_turn',
                'severity': 'high',
                'campaign_id': turn.campaign_id,
                'session_id': turn.session_id,
                'turn_id': turn.turn_id,
                'provider': turn.llm_provider,
                'model': turn.llm_model,
                'status': turn.status,
                'latency_ms': turn.latency_ms,
                'message': 'DM turn failed before completion.',
                'created_at': _isoformat(turn.created_at),
            }
        )
    for job in failed_canon_jobs:
        incidents.append(
            {
                'type': 'failed_canon_job',
                'severity': 'medium',
                'campaign_id': job.campaign_id,
                'session_id': job.session_id,
                'turn_id': job.turn_id,
                'job_id': job.job_id,
                'status': job.status,
                'attempts': job.attempts,
                'message': job.error_text or 'Canon extraction job failed.',
                'created_at': _isoformat(job.updated_at or job.created_at),
            }
        )
    for report in bad_turn_reports:
        incidents.append(
            {
                'type': 'bad_turn_report',
                'severity': 'medium',
                'campaign_id': report.session.campaign_id if report.session else None,
                'session_id': report.session_id,
                'turn_id': report.turn_id,
                'feedback_id': report.feedback_id,
                'category': report.category,
                'provider': report.provider,
                'model': report.model,
                'coherence_score': report.coherence_score,
                'message': report.notes or 'Turn was reported by a tester.',
                'created_at': _isoformat(report.created_at),
            }
        )

    telemetry_incidents = _telemetry_incident_counts()
    incidents.extend(telemetry_incidents)
    incidents.sort(key=lambda item: str(item.get('created_at') or ''), reverse=True)

    return jsonify(
        {
            'incidents': incidents[:limit],
            'summary': {
                'failed_turn_count': turns_query.filter(DmTurn.status == 'failed').count(),
                'failed_canon_job_count': canon_jobs_query.filter(CanonJob.status == 'failed').count(),
                'bad_turn_report_count': feedback_query.filter(DmCoherenceFeedback.feedback_type == 'bad_turn').count(),
                'telemetry_incident_count': len(telemetry_incidents),
            },
            'limit': limit,
        }
    )


def _state_mutation_audit_payload(row: SessionStateMutationAudit) -> dict:
    return {
        'mutation_audit_id': row.mutation_audit_id,
        'session_id': row.session_id,
        'campaign_id': row.campaign_id,
        'source': row.source,
        'actor': row.actor,
        'actor_account_id': row.actor_account_id,
        'actor_role': row.actor_role,
        'previous_revision': row.previous_revision,
        'state_revision': row.state_revision,
        'applied_change_count': row.applied_change_count,
        'rejected_change_count': row.rejected_change_count,
        'applied_change_ids': safe_json_loads(row.applied_change_ids_json, []),
        'diff': safe_json_loads(row.diff_json, []),
        'metadata': safe_json_loads(row.metadata_json, {}),
        'created_at': _isoformat(row.created_at),
    }


def _operator_action_audit_payload(row: OperatorActionAudit) -> dict:
    return {
        'operator_audit_id': row.operator_audit_id,
        'workspace_id': row.workspace_id,
        'campaign_id': row.campaign_id,
        'session_id': row.session_id,
        'action': row.action,
        'resource_type': row.resource_type,
        'resource_id': row.resource_id,
        'actor': row.actor,
        'actor_account_id': row.actor_account_id,
        'actor_role': row.actor_role,
        'status': row.status,
        'details': safe_json_loads(row.details_json, {}),
        'created_at': _isoformat(row.created_at),
    }


@system_bp.route('/beta/audits', methods=['GET'])
def beta_audits():
    forbidden = capability_forbidden_response('debug_read', 'Only workspace admins can inspect beta audit logs.')
    if forbidden:
        return forbidden

    telemetry_metric('system.beta_audits.requests_total', 1)
    limit = coerce_int(request.args.get('limit'), 25)
    limit = max(1, min(limit or 25, 100))
    workspace_id = current_workspace_id()

    state_mutation_query = (
        db.session.query(SessionStateMutationAudit)
        .join(Campaign, SessionStateMutationAudit.campaign_id == Campaign.campaign_id)
        .filter(Campaign.workspace_id == workspace_id)
    )
    operator_action_query = OperatorActionAudit.query.filter_by(workspace_id=workspace_id)

    state_mutations = (
        state_mutation_query.order_by(
            SessionStateMutationAudit.created_at.desc(),
            SessionStateMutationAudit.mutation_audit_id.desc(),
        )
        .limit(limit)
        .all()
    )
    operator_actions = (
        operator_action_query.order_by(
            OperatorActionAudit.created_at.desc(),
            OperatorActionAudit.operator_audit_id.desc(),
        )
        .limit(limit)
        .all()
    )

    return jsonify(
        {
            'state_mutations': [_state_mutation_audit_payload(row) for row in state_mutations],
            'operator_actions': [_operator_action_audit_payload(row) for row in operator_actions],
            'summary': {
                'state_mutation_count': state_mutation_query.count(),
                'operator_action_count': operator_action_query.count(),
            },
            'limit': limit,
        }
    )

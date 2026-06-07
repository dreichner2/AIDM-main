from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import os
import time

import requests
from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from sqlalchemy import func

from aidm_server.database import db
from aidm_server.errors import error_response
from aidm_server.http_client import post as http_post
from aidm_server.http_client import timeout_from_config
from aidm_server.models import Campaign, DmCoherenceFeedback, DmTurn, Session
from aidm_server.services.runtime_config import current_llm_payload
from aidm_server.telemetry import get_telemetry, prometheus_text_from_snapshot, telemetry_event, telemetry_metric, telemetry_timing
from aidm_server.text_sanitization import normalize_tts_text
from aidm_server.validation import coerce_int, missing_fields, parse_json_body
from aidm_server.workspace_access import current_workspace_id, get_session as workspace_session

system_bp = Blueprint('system', __name__)

DEEPGRAM_SPEAK_URL = 'https://api.deepgram.com/v1/speak'
DEEPGRAM_CHUNK_LIMIT = 2000
DEEPGRAM_FIRST_CHUNK_LIMIT = 360
TTS_MAX_CHARS = 6000


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
    score = payload.get('coherence_score')
    notes = payload.get('notes')

    try:
        score = int(score)
    except (TypeError, ValueError):
        return error_response('validation_error', 'coherence_score must be an integer between 1 and 5.', 400)

    if score < 1 or score > 5:
        return error_response('validation_error', 'coherence_score must be an integer between 1 and 5.', 400)

    session_obj = workspace_session(session_id)
    if not session_obj:
        return error_response('session_not_found', 'Session not found.', 404)

    if turn_id is not None:
        turn_obj = db.session.get(DmTurn, turn_id)
        if not turn_obj or turn_obj.session_id != session_obj.session_id:
            return error_response('turn_not_found', 'Turn not found for this session.', 404)

    feedback = DmCoherenceFeedback(
        session_id=session_obj.session_id,
        turn_id=turn_id,
        coherence_score=score,
        notes=notes,
    )
    db.session.add(feedback)
    db.session.commit()
    telemetry_metric('system.feedback.submitted_total', 1)

    return jsonify({'feedback_id': feedback.feedback_id}), 201


@system_bp.route('/beta/summary', methods=['GET'])
def beta_summary():
    telemetry_metric('system.beta_summary.requests_total', 1)
    return jsonify(_beta_summary())

from __future__ import annotations

import os
from pathlib import Path

import requests
from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from sqlalchemy import func

from aidm_server.config import SUPPORTED_LLM_PROVIDERS
from aidm_server.database import db
from aidm_server.errors import error_response
from aidm_server.models import DmCoherenceFeedback, DmTurn, Session
from aidm_server.telemetry import get_telemetry, telemetry_metric
from aidm_server.text_sanitization import normalize_tts_text
from aidm_server.validation import coerce_bool, coerce_int, missing_fields, parse_json_body

system_bp = Blueprint('system', __name__)

DEEPGRAM_SPEAK_URL = 'https://api.deepgram.com/v1/speak'
DEEPGRAM_CHUNK_LIMIT = 2000
TTS_MAX_CHARS = 6000


LLM_PROVIDER_CATALOG = [
    {
        'id': 'deepseek',
        'label': 'DeepSeek',
        'default_model': 'deepseek-v4-pro',
        'base_url': 'https://api.deepseek.com',
        'models': [
            {'id': 'deepseek-v4-pro', 'label': 'DeepSeek V4 Pro'},
            {'id': 'deepseek-v4-flash', 'label': 'DeepSeek V4 Flash'},
            {'id': 'deepseek-chat', 'label': 'DeepSeek Chat (legacy)'},
            {'id': 'deepseek-reasoner', 'label': 'DeepSeek Reasoner (legacy)'},
        ],
    },
    {
        'id': 'gemini',
        'label': 'Gemini',
        'default_model': 'models/gemini-3-flash-preview',
        'models': [
            {'id': 'models/gemini-3-flash-preview', 'label': 'Gemini 3 Flash Preview'},
            {'id': 'models/gemini-2.5-flash', 'label': 'Gemini 2.5 Flash'},
        ],
    },
    {
        'id': 'nvidia',
        'label': 'NVIDIA',
        'default_model': 'moonshotai/kimi-k2.5',
        'base_url': 'https://integrate.api.nvidia.com/v1',
        'models': [
            {'id': 'moonshotai/kimi-k2.5', 'label': 'Kimi K2.5'},
            {'id': 'deepseek-v4-pro', 'label': 'DeepSeek V4 Pro via NVIDIA'},
        ],
    },
    {
        'id': 'fallback',
        'label': 'Fallback',
        'default_model': 'deterministic-v1',
        'models': [{'id': 'deterministic-v1', 'label': 'Deterministic Local Fallback'}],
    },
]


def _latest_llm_turn_payload() -> dict | None:
    latest_llm_turn = (
        DmTurn.query.filter(DmTurn.llm_provider.isnot(None), DmTurn.llm_model.isnot(None))
        .order_by(DmTurn.turn_id.desc())
        .first()
    )
    if not latest_llm_turn:
        return None
    return {
        'turn_id': latest_llm_turn.turn_id,
        'session_id': latest_llm_turn.session_id,
        'provider': latest_llm_turn.llm_provider,
        'model': latest_llm_turn.llm_model,
        'latency_ms': latest_llm_turn.latency_ms,
        'completed_at': latest_llm_turn.completed_at.isoformat() if latest_llm_turn.completed_at else None,
    }


def _provider_option(provider_id: str) -> dict | None:
    for option in LLM_PROVIDER_CATALOG:
        if option['id'] == provider_id:
            return option
    return None


def _provider_configured(provider_id: str) -> bool:
    if provider_id == 'deepseek':
        return bool(
            current_app.config.get('AIDM_DEEPSEEK_API_KEY')
            or os.getenv('AIDM_DEEPSEEK_API_KEY')
            or os.getenv('DEEPSEEK_API_KEY')
            or os.getenv('AIDM_NVIDIA_API_KEY')
        )
    if provider_id in {'nvidia', 'kimi'}:
        return bool(os.getenv('AIDM_NVIDIA_API_KEY') or os.getenv('NVIDIA_API_KEY'))
    if provider_id == 'gemini':
        return bool(current_app.config.get('GOOGLE_GENAI_API_KEY') or os.getenv('GOOGLE_GENAI_API_KEY'))
    if provider_id == 'fallback':
        return True
    return False


def _current_llm_payload() -> dict:
    fallback_models = current_app.config.get('AIDM_LLM_FALLBACK_MODELS', []) or []
    provider = str(current_app.config.get('AIDM_LLM_PROVIDER', 'unknown'))
    model = str(current_app.config.get('AIDM_LLM_MODEL', 'unknown'))
    return {
        'provider': provider,
        'model': model,
        'fallback_models': list(fallback_models),
        'configured': _provider_configured(provider),
        'latest_turn': _latest_llm_turn_payload(),
    }


def _llm_config_payload() -> dict:
    providers = []
    for option in LLM_PROVIDER_CATALOG:
        providers.append(
            {
                **option,
                'configured': _provider_configured(option['id']),
            }
        )
    return {
        'current': _current_llm_payload(),
        'providers': providers,
        'persisted': False,
    }


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
    return {
        'provider': 'deepgram',
        'configured': bool(_deepgram_api_key()),
        'model': _tts_model(),
    }


def _repo_root() -> Path:
    return Path(current_app.root_path).resolve().parent


def _persist_env_updates(updates: dict[str, str]):
    env_file = _repo_root() / '.env.local'
    lines = env_file.read_text(encoding='utf-8').splitlines(keepends=True) if env_file.exists() else []
    written: set[str] = set()
    output: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in line:
            output.append(line)
            continue
        key = line.split('=', 1)[0].strip()
        if key in updates:
            output.append(f'{key}={updates[key]}\n')
            written.add(key)
        else:
            output.append(line)

    for key, value in updates.items():
        if key not in written:
            output.append(f'{key}={value}\n')

    env_file.write_text(''.join(output), encoding='utf-8')
    env_file.chmod(0o600)


def _apply_llm_runtime(provider: str, model: str, *, persist: bool = True):
    updates = {
        'AIDM_LLM_PROVIDER': provider,
        'AIDM_LLM_MODEL': model,
        'AIDM_LLM_FALLBACK_MODELS': '',
    }
    if provider == 'deepseek':
        option = _provider_option(provider) or {}
        updates['AIDM_DEEPSEEK_BASE_URL'] = str(option.get('base_url') or 'https://api.deepseek.com')
        if not os.getenv('AIDM_DEEPSEEK_API_KEY'):
            fallback_key = os.getenv('DEEPSEEK_API_KEY') or os.getenv('AIDM_NVIDIA_API_KEY')
            if fallback_key:
                os.environ['AIDM_DEEPSEEK_API_KEY'] = fallback_key
    elif provider == 'nvidia':
        option = _provider_option(provider) or {}
        updates['AIDM_NVIDIA_INVOKE_URL'] = str(option.get('base_url') or 'https://integrate.api.nvidia.com/v1')

    for key, value in updates.items():
        os.environ[key] = value

    current_app.config['AIDM_LLM_PROVIDER'] = provider
    current_app.config['AIDM_LLM_MODEL'] = model
    current_app.config['AIDM_LLM_FALLBACK_MODELS'] = []
    if provider == 'deepseek':
        current_app.config['AIDM_DEEPSEEK_BASE_URL'] = updates['AIDM_DEEPSEEK_BASE_URL']
        if os.getenv('AIDM_DEEPSEEK_API_KEY'):
            current_app.config['AIDM_DEEPSEEK_API_KEY'] = os.getenv('AIDM_DEEPSEEK_API_KEY')

    if persist:
        _persist_env_updates(updates)


def _llm_config_persistence_allowed() -> bool:
    env = str(current_app.config.get('AIDM_ENV', 'development')).strip().lower()
    return env in {'development', 'local', 'test'}


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
            'llm': _current_llm_payload(),
        }
    )


@system_bp.route('/metrics', methods=['GET'])
def metrics_snapshot():
    telemetry_metric('system.metrics.requests_total', 1)
    client = get_telemetry()
    snapshot = client.snapshot() if client else {'enabled': False, 'counters': {}, 'timings': {}}
    snapshot['beta'] = _beta_summary()
    return jsonify(snapshot)


@system_bp.route('/llm/config', methods=['GET'])
def llm_config():
    telemetry_metric('system.llm_config.requests_total', 1)
    return jsonify(_llm_config_payload())


@system_bp.route('/tts/config', methods=['GET'])
def tts_config():
    telemetry_metric('system.tts_config.requests_total', 1)
    return jsonify(_tts_config_payload())


def _chunk_text_for_tts(text: str, max_chars: int = DEEPGRAM_CHUNK_LIMIT) -> list[str]:
    """Split *text* into chunks of at most *max_chars* characters.

    Tries to split on sentence boundaries (`.`, `!`, `?`) first, then falls
    back to the nearest space so words are not cut in the middle.
    """
    chunks: list[str] = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        # Try to find a sentence-ending punctuation near the limit.
        split_at = -1
        for sep in ('.', '!', '?'):
            idx = text.rfind(sep, 0, max_chars)
            if idx > split_at:
                split_at = idx
        if split_at > 0:
            split_at += 1  # include the punctuation
        else:
            # Fall back to the last space before the limit.
            split_at = text.rfind(' ', 0, max_chars)
        if split_at <= 0:
            split_at = max_chars  # hard cut as last resort
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    return [c for c in chunks if c]


def _deepgram_tts_request(api_key: str, model: str, text: str, *, stream: bool = False) -> requests.Response:
    """Make a single Deepgram TTS request."""
    return requests.post(
        DEEPGRAM_SPEAK_URL,
        params={'model': model, 'encoding': 'mp3'},
        headers={
            'Authorization': f'Token {api_key}',
            'Content-Type': 'application/json',
        },
        json={'text': text},
        stream=stream,
        timeout=(5, 60),
    )


def _iter_tts_response_content(upstream: requests.Response):
    for audio_chunk in upstream.iter_content(chunk_size=1024):
        if audio_chunk:
            yield audio_chunk


def _stream_tts_chunks(
    first_upstream: requests.Response,
    remaining_chunks: list[str],
    *,
    api_key: str,
    model: str,
):
    upstream: requests.Response | None = first_upstream
    try:
        while upstream is not None:
            yield from _iter_tts_response_content(upstream)
            upstream.close()
            upstream = None

            if not remaining_chunks:
                break

            next_chunk = remaining_chunks.pop(0)
            upstream = _deepgram_tts_request(api_key, model, next_chunk, stream=True)
            if not upstream.ok:
                current_app.logger.warning(
                    'Deepgram TTS chunk failed while streaming: status=%s detail=%s',
                    upstream.status_code,
                    upstream.text[:500] if upstream.text else '',
                )
                break
    finally:
        if upstream is not None:
            upstream.close()


@system_bp.route('/tts/speak', methods=['POST'])
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

    try:
        first_upstream = _deepgram_tts_request(api_key, model, chunks[0], stream=True)
    except requests.RequestException as exc:
        return error_response('tts_request_failed', f'Deepgram TTS request failed: {exc}', 502)

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
            _stream_tts_chunks(first_upstream, chunks[1:], api_key=api_key, model=model),
        ),
        mimetype=content_type,
        direct_passthrough=True,
    )
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['X-AIDM-TTS-Provider'] = 'deepgram'
    response.headers['X-AIDM-TTS-Model'] = model
    return response


@system_bp.route('/llm/config', methods=['PATCH', 'POST'])
def update_llm_config():
    telemetry_metric('system.llm_config_updates.requests_total', 1)
    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    provider = str(payload.get('provider') or '').strip().lower()
    model = str(payload.get('model') or '').strip()
    persist = coerce_bool(payload.get('persist'), True)
    if persist is None:
        return error_response('validation_error', 'persist must be a boolean value.', 400)
    if persist and not _llm_config_persistence_allowed():
        return error_response(
            'llm_config_persist_disabled',
            'Persisting LLM config from the API is disabled outside local/test environments.',
            403,
        )

    if provider not in SUPPORTED_LLM_PROVIDERS:
        return error_response(
            'unsupported_provider',
            f'Unsupported provider "{provider}".',
            400,
            {'providers': sorted(SUPPORTED_LLM_PROVIDERS)},
        )

    option = _provider_option(provider)
    if option is None:
        return error_response('unsupported_provider', f'Provider "{provider}" is not configurable from the UI.', 400)

    model = model or str(option['default_model'])
    allowed_models = {str(item['id']) for item in option.get('models', [])}
    if model not in allowed_models:
        return error_response(
            'unsupported_model',
            f'Model "{model}" is not available for provider "{provider}".',
            400,
            {'models': sorted(allowed_models)},
        )

    if not _provider_configured(provider):
        return error_response(
            'provider_not_configured',
            f'Provider "{provider}" is missing its API key.',
            400,
        )

    _apply_llm_runtime(provider, model, persist=persist)
    response = _llm_config_payload()
    response['persisted'] = persist
    return jsonify(response)


def _beta_summary() -> dict:
    total_turns = db.session.query(func.count(DmTurn.turn_id)).scalar() or 0
    failed_turns = db.session.query(func.count(DmTurn.turn_id)).filter(DmTurn.status == 'failed').scalar() or 0
    avg_turn_latency = db.session.query(func.avg(DmTurn.latency_ms)).scalar()

    total_sessions = db.session.query(func.count(Session.session_id)).scalar() or 0
    completed_sessions = db.session.query(func.count(Session.session_id)).filter(Session.state_snapshot.isnot(None)).scalar() or 0

    feedback_count = db.session.query(func.count(DmCoherenceFeedback.feedback_id)).scalar() or 0
    avg_feedback = db.session.query(func.avg(DmCoherenceFeedback.coherence_score)).scalar()

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

    session_obj = db.session.get(Session, session_id)
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

"""Application configuration helpers for AI-DM."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import List


SUPPORTED_LLM_PROVIDERS = {'deepseek', 'gemini', 'nvidia', 'kimi', 'fallback'}


def _to_bool(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _to_int(value: str | int | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_list(value: str | None, default: List[str]) -> List[str]:
    if value is None:
        return list(default)
    items = [item.strip() for item in value.split(',') if item.strip()]
    return items if items else list(default)


@dataclass(frozen=True)
class AppConfig:
    env: str
    debug: bool
    secret_key: str
    cors_allowlist: List[str]
    cors_allow_private_network: bool
    socketio_cors_allowlist: List[str]
    socketio_async_mode: str
    database_uri: str
    auto_create_schema: bool
    max_request_bytes: int
    admin_enabled: bool

    auth_required: bool
    api_auth_tokens: List[str]

    llm_provider: str
    llm_model: str
    llm_fallback_models: List[str]
    google_genai_api_key: str | None
    deepgram_api_key: str | None
    deepgram_tts_model: str

    rules_engine_enabled: bool
    segment_evaluator_enabled: bool

    telemetry_enabled: bool
    telemetry_endpoint: str
    telemetry_api_key: str | None
    telemetry_timeout_seconds: int
    telemetry_max_queue_size: int

    rate_limit_window_seconds: int
    rate_limit_max_api_requests: int
    rate_limit_max_socket_messages: int
    trusted_proxy_count: int


DEFAULT_SQLITE_PATH = 'sqlite:///instance/dnd_ai_dm.db'


def _resolve_secret_key(env: str, configured_value: str | None) -> str:
    secret_key = (configured_value or '').strip()
    if secret_key:
        return secret_key
    if env == 'production':
        raise ValueError('FLASK_SECRET_KEY is required when AIDM_ENV=production.')
    return secrets.token_hex(32)


def load_config() -> AppConfig:
    env = os.getenv('AIDM_ENV', 'development').strip().lower()
    debug = _to_bool(os.getenv('AIDM_DEBUG'), default=(env != 'production'))
    llm_provider = os.getenv('AIDM_LLM_PROVIDER', 'gemini').strip().lower()
    if llm_provider not in SUPPORTED_LLM_PROVIDERS:
        raise ValueError(
            'Unsupported AIDM_LLM_PROVIDER '
            f'"{llm_provider}". Expected one of: {", ".join(sorted(SUPPORTED_LLM_PROVIDERS))}.'
        )
    if llm_provider == 'deepseek':
        default_llm_model = 'deepseek-v4-pro'
    elif llm_provider in {'nvidia', 'kimi'}:
        default_llm_model = 'moonshotai/kimi-k2.5'
    elif llm_provider == 'fallback':
        default_llm_model = 'deterministic-v1'
    else:
        default_llm_model = 'models/gemini-3-flash-preview'

    default_cors = ['*'] if debug else []
    cors_allowlist = _to_list(os.getenv('AIDM_CORS_ALLOWLIST'), default_cors)
    cors_allow_private_network = _to_bool(
        os.getenv('AIDM_CORS_ALLOW_PRIVATE_NETWORK'),
        default=(env != 'production'),
    )
    socketio_cors_allowlist = _to_list(os.getenv('AIDM_SOCKET_CORS_ALLOWLIST'), cors_allowlist)
    llm_fallback_models = _to_list(os.getenv('AIDM_LLM_FALLBACK_MODELS'), [])

    return AppConfig(
        env=env,
        debug=debug,
        secret_key=_resolve_secret_key(env, os.getenv('FLASK_SECRET_KEY')),
        cors_allowlist=cors_allowlist,
        cors_allow_private_network=cors_allow_private_network,
        socketio_cors_allowlist=socketio_cors_allowlist,
        socketio_async_mode=os.getenv('AIDM_SOCKETIO_ASYNC_MODE', 'threading').strip().lower(),
        database_uri=os.getenv('AIDM_DATABASE_URI', DEFAULT_SQLITE_PATH),
        auto_create_schema=_to_bool(os.getenv('AIDM_AUTO_CREATE_SCHEMA'), default=True),
        max_request_bytes=_to_int(os.getenv('AIDM_MAX_REQUEST_BYTES'), default=1_048_576),
        admin_enabled=_to_bool(
            os.getenv('AIDM_ADMIN_ENABLED'),
            default=env in {'development', 'local'},
        ),
        auth_required=_to_bool(os.getenv('AIDM_AUTH_REQUIRED'), default=False),
        api_auth_tokens=_to_list(os.getenv('AIDM_API_AUTH_TOKENS'), []),
        llm_provider=llm_provider,
        llm_model=os.getenv('AIDM_LLM_MODEL', default_llm_model),
        llm_fallback_models=llm_fallback_models,
        google_genai_api_key=os.getenv('GOOGLE_GENAI_API_KEY'),
        deepgram_api_key=os.getenv('AIDM_DEEPGRAM_API_KEY') or os.getenv('DEEPGRAM_API_KEY'),
        deepgram_tts_model=os.getenv('AIDM_DEEPGRAM_TTS_MODEL', 'aura-2-draco-en'),
        rules_engine_enabled=_to_bool(os.getenv('AIDM_RULES_ENGINE_ENABLED'), default=True),
        segment_evaluator_enabled=_to_bool(os.getenv('AIDM_SEGMENT_EVALUATOR_ENABLED'), default=True),
        telemetry_enabled=_to_bool(os.getenv('AIDM_TELEMETRY_ENABLED'), default=False),
        telemetry_endpoint=os.getenv('AIDM_TELEMETRY_ENDPOINT', ''),
        telemetry_api_key=os.getenv('AIDM_TELEMETRY_API_KEY'),
        telemetry_timeout_seconds=_to_int(os.getenv('AIDM_TELEMETRY_TIMEOUT_SECONDS'), default=2),
        telemetry_max_queue_size=_to_int(os.getenv('AIDM_TELEMETRY_MAX_QUEUE_SIZE'), default=1000),
        rate_limit_window_seconds=_to_int(os.getenv('AIDM_RATE_LIMIT_WINDOW_SECONDS'), default=30),
        rate_limit_max_api_requests=_to_int(os.getenv('AIDM_RATE_LIMIT_MAX_API_REQUESTS'), default=120),
        rate_limit_max_socket_messages=_to_int(os.getenv('AIDM_RATE_LIMIT_MAX_SOCKET_MESSAGES'), default=40),
        trusted_proxy_count=max(0, _to_int(os.getenv('AIDM_TRUSTED_PROXY_COUNT'), default=0)),
    )

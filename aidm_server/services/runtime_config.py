from __future__ import annotations

import os
from pathlib import Path

from flask import current_app

from aidm_server.models import DmTurn
from aidm_server.provider_registry import (
    SUPPORTED_LLM_PROVIDERS,
    provider_catalog_payload,
    provider_option,
)


class RuntimeConfigError(ValueError):
    def __init__(self, error_code: str, message: str, status_code: int = 400, details: dict | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.details = details


def latest_llm_turn_payload() -> dict | None:
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


def provider_configured(provider_id: str) -> bool:
    if provider_id == 'deepseek':
        return bool(
            current_app.config.get('AIDM_DEEPSEEK_API_KEY')
            or os.getenv('AIDM_DEEPSEEK_API_KEY')
            or os.getenv('DEEPSEEK_API_KEY')
        )
    if provider_id in {'nvidia', 'kimi'}:
        return bool(os.getenv('AIDM_NVIDIA_API_KEY') or os.getenv('NVIDIA_API_KEY'))
    if provider_id == 'gemini':
        return bool(current_app.config.get('GOOGLE_GENAI_API_KEY') or os.getenv('GOOGLE_GENAI_API_KEY'))
    if provider_id == 'fallback':
        return True
    return False


def current_llm_payload() -> dict:
    fallback_models = current_app.config.get('AIDM_LLM_FALLBACK_MODELS', []) or []
    provider = str(current_app.config.get('AIDM_LLM_PROVIDER', 'unknown'))
    model = str(current_app.config.get('AIDM_LLM_MODEL', 'unknown'))
    return {
        'provider': provider,
        'model': model,
        'fallback_models': list(fallback_models),
        'configured': provider_configured(provider),
        'latest_turn': latest_llm_turn_payload(),
    }


def llm_config_payload() -> dict:
    providers = []
    for option in provider_catalog_payload():
        providers.append(
            {
                **option,
                'configured': provider_configured(option['id']),
            }
        )
    return {
        'current': current_llm_payload(),
        'providers': providers,
        'persisted': False,
        'runtime_scope': 'process',
        'restart_required_for_other_workers': True,
    }


def repo_root() -> Path:
    return Path(current_app.root_path).resolve().parent


def persist_env_updates(updates: dict[str, str]):
    env_file = repo_root() / '.env.local'
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


def validate_provider_model(provider: str, model: str) -> tuple[str, str]:
    provider = str(provider or '').strip().lower()
    model = str(model or '').strip()
    if provider not in SUPPORTED_LLM_PROVIDERS:
        raise RuntimeConfigError(
            'unsupported_provider',
            f'Unsupported provider "{provider}".',
            details={'providers': sorted(SUPPORTED_LLM_PROVIDERS)},
        )

    option = provider_option(provider)
    if option is None:
        raise RuntimeConfigError('unsupported_provider', f'Provider "{provider}" is not configurable from the UI.')

    selected_model = model or str(option['default_model'])
    allowed_models = {str(item['id']) for item in option.get('models', [])}
    if selected_model not in allowed_models:
        raise RuntimeConfigError(
            'unsupported_model',
            f'Model "{selected_model}" is not available for provider "{provider}".',
            details={'models': sorted(allowed_models)},
        )

    return provider, selected_model


def apply_llm_runtime(provider: str, model: str, *, persist: bool = True):
    updates = {
        'AIDM_LLM_PROVIDER': provider,
        'AIDM_LLM_MODEL': model,
        'AIDM_LLM_FALLBACK_MODELS': '',
    }
    if provider == 'deepseek':
        option = provider_option(provider) or {}
        updates['AIDM_DEEPSEEK_BASE_URL'] = str(option.get('base_url') or 'https://api.deepseek.com')
        if not os.getenv('AIDM_DEEPSEEK_API_KEY'):
            fallback_key = os.getenv('DEEPSEEK_API_KEY')
            if fallback_key:
                os.environ['AIDM_DEEPSEEK_API_KEY'] = fallback_key
    elif provider == 'nvidia':
        option = provider_option(provider) or {}
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
        persist_env_updates(updates)


def llm_config_persistence_allowed() -> bool:
    env = str(current_app.config.get('AIDM_ENV', 'development')).strip().lower()
    return env in {'development', 'local', 'test'}

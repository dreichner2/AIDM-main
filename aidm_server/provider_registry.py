"""LLM provider catalog and capability metadata."""

from __future__ import annotations

from copy import deepcopy


PROVIDER_CATALOG: dict[str, dict] = {
    'deepseek': {
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
        'capabilities': {
            'streaming': True,
            'openai_compatible': True,
            'thinking_control': True,
            'default_timeout_seconds': 180,
            'default_temperature': 0.7,
        },
    },
    'gemini': {
        'id': 'gemini',
        'label': 'Gemini',
        'default_model': 'models/gemini-3-flash-preview',
        'models': [
            {'id': 'models/gemini-3-flash-preview', 'label': 'Gemini 3 Flash Preview'},
            {'id': 'models/gemini-2.5-flash', 'label': 'Gemini 2.5 Flash'},
        ],
        'capabilities': {
            'streaming': True,
            'fallback_cooldown': True,
            'thinking_control': False,
            'default_timeout_seconds': 60,
            'default_temperature': 0.7,
        },
    },
    'nvidia': {
        'id': 'nvidia',
        'label': 'NVIDIA',
        'default_model': 'moonshotai/kimi-k2.5',
        'base_url': 'https://integrate.api.nvidia.com/v1',
        'models': [
            {'id': 'moonshotai/kimi-k2.5', 'label': 'Kimi K2.5'},
            {'id': 'deepseek-v4-pro', 'label': 'DeepSeek V4 Pro via NVIDIA'},
        ],
        'capabilities': {
            'streaming': True,
            'openai_compatible': True,
            'thinking_control': True,
            'default_timeout_seconds': 60,
            'default_temperature': 1.0,
        },
    },
    'kimi': {
        'id': 'kimi',
        'label': 'Kimi',
        'default_model': 'moonshotai/kimi-k2.5',
        'base_url': 'https://integrate.api.nvidia.com/v1',
        'models': [{'id': 'moonshotai/kimi-k2.5', 'label': 'Kimi K2.5'}],
        'capabilities': {
            'streaming': True,
            'openai_compatible': True,
            'thinking_control': True,
            'default_timeout_seconds': 60,
            'default_temperature': 1.0,
        },
    },
    'fallback': {
        'id': 'fallback',
        'label': 'Fallback',
        'default_model': 'deterministic-v1',
        'models': [{'id': 'deterministic-v1', 'label': 'Deterministic Local Fallback'}],
        'capabilities': {
            'streaming': False,
            'thinking_control': False,
            'default_timeout_seconds': 1,
            'default_temperature': 0.0,
        },
    },
}

SUPPORTED_LLM_PROVIDERS = set(PROVIDER_CATALOG)


def provider_option(provider_id: str) -> dict | None:
    option = PROVIDER_CATALOG.get(provider_id)
    return deepcopy(option) if option else None


def provider_default_model(provider_id: str) -> str:
    option = PROVIDER_CATALOG.get(provider_id) or PROVIDER_CATALOG['gemini']
    return str(option['default_model'])


def provider_capabilities(provider_id: str) -> dict:
    option = PROVIDER_CATALOG.get(provider_id) or {}
    return deepcopy(option.get('capabilities', {}))


def provider_catalog_payload() -> list[dict]:
    return [deepcopy(PROVIDER_CATALOG[key]) for key in ('deepseek', 'gemini', 'nvidia', 'kimi', 'fallback')]

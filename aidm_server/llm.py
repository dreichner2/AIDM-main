"""LLM interactions with provider abstraction and deterministic fallback behavior."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
import os
from threading import Lock
from typing import Any, Generator

from flask import current_app, has_app_context
import requests
from sqlalchemy import func

from aidm_server.contracts import ProviderRequest, ProviderResponse
from aidm_server.config import SUPPORTED_LLM_PROVIDERS
from aidm_server.emergent_memory import build_emergent_context, inventory_payload
from aidm_server.models import (
    Campaign,
    CampaignSegment,
    DmTurn,
    Player,
    PlayerAction,
    SessionLogEntry,
    SessionState,
    World,
    safe_json_loads,
)
from aidm_server.database import db
from aidm_server.telemetry import telemetry_event, telemetry_metric
from aidm_server.time_utils import utc_now


logger = logging.getLogger(__name__)

CONTEXT_VERSION = 'v2'
DEFAULT_GEMINI_MODEL = 'models/gemini-3-flash-preview'
DEFAULT_NVIDIA_MODEL = 'moonshotai/kimi-k2.5'
DEFAULT_DEEPSEEK_MODEL = 'deepseek-v4-pro'


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


GEMINI_RATE_LIMIT_THRESHOLD = _int_env('AIDM_LLM_RATE_LIMIT_THRESHOLD', 2)
GEMINI_RATE_LIMIT_COOLDOWN_SECONDS = _int_env('AIDM_LLM_RATE_LIMIT_COOLDOWN_SECONDS', 120)


class ProviderNotConfiguredError(RuntimeError):
    pass


def _truncate_text(value: str | None, max_length: int) -> str:
    text = str(value or '').strip()
    if len(text) <= max_length:
        return text
    return f'{text[: max(0, max_length - 1)].rstrip()}…'


class BaseLLMProvider:
    provider_name = 'base'

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError

    def stream(self, request: ProviderRequest) -> Generator[str, None, None]:
        response = self.generate(request)
        if response.text:
            yield response.text


class GeminiProvider(BaseLLMProvider):
    provider_name = 'gemini'
    _rate_limit_state: dict[str, dict[str, Any]] = {}
    _rate_limit_lock = Lock()

    def __init__(self, model_name: str, api_key: str | None, fallback_models: list[str] | None = None):
        self.model_name = model_name
        self.api_key = api_key
        self.fallback_models = self._normalize_models(fallback_models or [])
        self._client = None

    @staticmethod
    def _normalize_models(model_names: list[str]) -> list[str]:
        normalized = []
        seen = set()
        for raw_name in model_names:
            model_name = str(raw_name or '').strip()
            if not model_name or model_name in seen:
                continue
            normalized.append(model_name)
            seen.add(model_name)
        return normalized

    def _candidate_models(self) -> list[str]:
        return self._normalize_models([self.model_name, *self.fallback_models])

    def _build_prompt(self, request: ProviderRequest) -> str:
        if request.system_message:
            return f"{request.system_message}\n\n{request.prompt}"
        return request.prompt

    def _ensure_sdk(self):
        if self._client is not None:
            return

        if not self.api_key:
            telemetry_event('llm.provider_not_configured', payload={'provider': self.provider_name}, severity='warning')
            raise ProviderNotConfiguredError('GOOGLE_GENAI_API_KEY is not configured')

        try:
            from google import genai
        except Exception as exc:
            telemetry_event(
                'llm.provider_import_failed',
                payload={'provider': self.provider_name, 'error': str(exc)},
                severity='error',
            )
            raise ProviderNotConfiguredError(f'google.genai SDK import failed: {str(exc)}') from exc

        self._client = genai.Client(api_key=self.api_key)

    @staticmethod
    def _extract_text(response: Any, preserve_whitespace: bool = False) -> str:
        text = getattr(response, 'text', None)
        if isinstance(text, str):
            return text if preserve_whitespace else text.strip()

        # Handle response variants where text is nested in candidates/parts.
        fragments = []
        candidates = getattr(response, 'candidates', None) or []
        for candidate in candidates:
            content = getattr(candidate, 'content', None)
            parts = getattr(content, 'parts', None) or []
            for part in parts:
                part_text = getattr(part, 'text', None)
                if isinstance(part_text, str) and part_text:
                    fragments.append(part_text)
        joined = ''.join(fragments)
        return joined if preserve_whitespace else joined.strip()

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        status_code = getattr(exc, 'status_code', None)
        if status_code == 429:
            return True
        message = str(exc).lower()
        return '429' in message or 'too many requests' in message or 'resource_exhausted' in message

    @classmethod
    def _is_model_in_cooldown(cls, model_name: str) -> tuple[bool, int]:
        now = utc_now()
        with cls._rate_limit_lock:
            state = cls._rate_limit_state.get(model_name)
            if not state:
                return False, 0
            cooldown_until = state.get('cooldown_until')
            if not isinstance(cooldown_until, datetime):
                return False, 0
            if cooldown_until <= now:
                state['cooldown_until'] = None
                return False, 0
            remaining = max(0, int((cooldown_until - now).total_seconds()))
            return True, remaining

    @classmethod
    def _record_model_success(cls, model_name: str):
        with cls._rate_limit_lock:
            state = cls._rate_limit_state.setdefault(model_name, {})
            state['consecutive_429'] = 0
            state['cooldown_until'] = None

    @classmethod
    def _record_model_rate_limit(cls, model_name: str) -> datetime | None:
        now = utc_now()
        with cls._rate_limit_lock:
            state = cls._rate_limit_state.setdefault(model_name, {})
            consecutive = int(state.get('consecutive_429', 0)) + 1
            state['consecutive_429'] = consecutive
            if consecutive < GEMINI_RATE_LIMIT_THRESHOLD:
                return None

            cooldown_until = now + timedelta(seconds=GEMINI_RATE_LIMIT_COOLDOWN_SECONDS)
            state['cooldown_until'] = cooldown_until
            state['consecutive_429'] = 0
            return cooldown_until

    def _generate_with_model(self, model_name: str, full_prompt: str) -> str:
        self._ensure_sdk()
        response = self._client.models.generate_content(
            model=model_name,
            contents=full_prompt,
        )
        return self._extract_text(response, preserve_whitespace=False)

    def _stream_with_model(self, model_name: str, full_prompt: str) -> Generator[str, None, None]:
        self._ensure_sdk()
        response = self._client.models.generate_content_stream(
            model=model_name,
            contents=full_prompt,
        )
        for chunk in response:
            text = self._extract_text(chunk, preserve_whitespace=True)
            if text != '':
                yield text

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        full_prompt = self._build_prompt(request)
        last_error: Exception | None = None

        for index, model_name in enumerate(self._candidate_models()):
            in_cooldown, remaining_seconds = self._is_model_in_cooldown(model_name)
            if in_cooldown:
                telemetry_event(
                    'llm.model_skipped_cooldown',
                    payload={
                        'provider': self.provider_name,
                        'model': model_name,
                        'remaining_seconds': remaining_seconds,
                    },
                    severity='warning',
                )
                last_error = RuntimeError(f'Model in cooldown for {remaining_seconds} seconds: {model_name}')
                continue

            try:
                text = self._generate_with_model(model_name, full_prompt).strip()
                if not text:
                    raise RuntimeError('Model returned an empty response')
                if index > 0:
                    telemetry_event(
                        'llm.model_fallback_used',
                        payload={'provider': self.provider_name, 'selected_model': model_name, 'primary_model': self.model_name},
                        severity='warning',
                    )
                telemetry_metric('llm.generate.success_total', 1, tags={'provider': self.provider_name, 'model': model_name})
                self._record_model_success(model_name)
                return ProviderResponse(text=text, provider=self.provider_name, model=model_name)
            except Exception as exc:
                last_error = exc
                if self._is_rate_limit_error(exc):
                    cooldown_until = self._record_model_rate_limit(model_name)
                    telemetry_event(
                        'llm.model_rate_limited',
                        payload={
                            'provider': self.provider_name,
                            'model': model_name,
                            'error': str(exc),
                            'cooldown_until': cooldown_until.isoformat() if cooldown_until else None,
                            'cooldown_seconds': GEMINI_RATE_LIMIT_COOLDOWN_SECONDS if cooldown_until else 0,
                        },
                        severity='warning',
                    )
                telemetry_event(
                    'llm.model_attempt_failed',
                    payload={'provider': self.provider_name, 'model': model_name, 'error': str(exc)},
                    severity='warning',
                )
                continue

        configured_models = ', '.join(self._candidate_models()) or self.model_name
        raise RuntimeError(f'All Gemini models failed: {configured_models}') from last_error

    def stream(self, request: ProviderRequest) -> Generator[str, None, None]:
        full_prompt = self._build_prompt(request)
        last_error: Exception | None = None

        for index, model_name in enumerate(self._candidate_models()):
            in_cooldown, remaining_seconds = self._is_model_in_cooldown(model_name)
            if in_cooldown:
                telemetry_event(
                    'llm.model_skipped_cooldown',
                    payload={
                        'provider': self.provider_name,
                        'model': model_name,
                        'remaining_seconds': remaining_seconds,
                    },
                    severity='warning',
                )
                last_error = RuntimeError(f'Model in cooldown for {remaining_seconds} seconds: {model_name}')
                continue

            yielded = False
            try:
                for chunk in self._stream_with_model(model_name, full_prompt):
                    yielded = True
                    yield chunk

                if yielded:
                    if index > 0:
                        telemetry_event(
                            'llm.model_fallback_used',
                            payload={'provider': self.provider_name, 'selected_model': model_name, 'primary_model': self.model_name},
                            severity='warning',
                        )
                    telemetry_metric('llm.stream.start_total', 1, tags={'provider': self.provider_name, 'model': model_name})
                    self._record_model_success(model_name)
                    return

                raise RuntimeError('Model returned an empty streaming response')
            except Exception as exc:
                # If streaming already began from this model, preserve continuity and let caller fall back
                # to deterministic handling instead of mixing chunks from two model outputs.
                if yielded:
                    raise
                last_error = exc
                if self._is_rate_limit_error(exc):
                    cooldown_until = self._record_model_rate_limit(model_name)
                    telemetry_event(
                        'llm.model_rate_limited',
                        payload={
                            'provider': self.provider_name,
                            'model': model_name,
                            'error': str(exc),
                            'cooldown_until': cooldown_until.isoformat() if cooldown_until else None,
                            'cooldown_seconds': GEMINI_RATE_LIMIT_COOLDOWN_SECONDS if cooldown_until else 0,
                        },
                        severity='warning',
                    )
                telemetry_event(
                    'llm.model_attempt_failed',
                    payload={'provider': self.provider_name, 'model': model_name, 'error': str(exc)},
                    severity='warning',
                )
                continue

        configured_models = ', '.join(self._candidate_models()) or self.model_name
        raise RuntimeError(f'All Gemini streaming models failed: {configured_models}') from last_error


class DeterministicFallbackProvider(BaseLLMProvider):
    provider_name = 'fallback'

    def __init__(self, model_name: str = 'deterministic-v1'):
        self.model_name = model_name

    def _make_text(self, request: ProviderRequest) -> str:
        prompt = request.prompt.strip()
        opening = (
            'The scene advances with deliberate tension as the world reacts to the party\'s intent. '
            'Describe your next move and I will keep continuity while we reconnect full AI narration.'
        )
        if 'roll a d20' in prompt.lower() or 'requires_roll' in prompt.lower():
            return f"{opening}\n\nThis moment likely calls for a roll. Roll a d20 and tell me the result."
        return opening

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            text=self._make_text(request),
            provider=self.provider_name,
            model=self.model_name,
        )


class NvidiaChatProvider(BaseLLMProvider):
    provider_name = 'nvidia'
    display_name = 'NVIDIA'

    def __init__(
        self,
        model_name: str,
        api_key: str | None,
        invoke_url: str,
        fallback_models: list[str] | None = None,
        max_tokens: int = 16384,
        temperature: float = 1.0,
        top_p: float = 1.0,
        thinking_enabled: bool = True,
        timeout_seconds: int = 60,
    ):
        self.model_name = model_name
        self.api_key = (api_key or '').strip() or None
        self.invoke_url = self._normalize_invoke_url(invoke_url)
        self.fallback_models = self._normalize_models(fallback_models or [])
        self.max_tokens = max(1, int(max_tokens))
        self.temperature = float(temperature)
        self.top_p = float(top_p)
        self.thinking_enabled = bool(thinking_enabled)
        self.timeout_seconds = max(1, int(timeout_seconds))

    @staticmethod
    def _normalize_models(model_names: list[str]) -> list[str]:
        normalized = []
        seen = set()
        for raw_name in model_names:
            model_name = str(raw_name or '').strip()
            if not model_name or model_name in seen:
                continue
            normalized.append(model_name)
            seen.add(model_name)
        return normalized

    def _candidate_models(self) -> list[str]:
        return self._normalize_models([self.model_name, *self.fallback_models])

    @staticmethod
    def _normalize_invoke_url(invoke_url: str | None) -> str:
        url = (invoke_url or '').strip().rstrip('/')
        if not url:
            return ''
        if url.endswith('/v1'):
            return f'{url}/chat/completions'
        return url

    def _ensure_configured(self):
        if not self.api_key:
            telemetry_event('llm.provider_not_configured', payload={'provider': self.provider_name}, severity='warning')
            raise ProviderNotConfiguredError('AIDM_NVIDIA_API_KEY (or NVIDIA_API_KEY) is not configured')
        if not self.invoke_url:
            raise ProviderNotConfiguredError('AIDM_NVIDIA_INVOKE_URL is not configured')

    @staticmethod
    def _as_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            fragments = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get('text')
                    if isinstance(text, str):
                        fragments.append(text)
                elif isinstance(item, str):
                    fragments.append(item)
            return ''.join(fragments)
        if isinstance(content, dict):
            text = content.get('text')
            return text if isinstance(text, str) else ''
        return ''

    @staticmethod
    def _extract_completion_text(payload: dict) -> str:
        choices = payload.get('choices') or []
        if not choices:
            return ''
        message = (choices[0] or {}).get('message') or {}
        text = NvidiaChatProvider._as_text(message.get('content'))
        if text:
            return text.strip()

        # Fallback for alternate response shapes.
        delta = (choices[0] or {}).get('delta') or {}
        return NvidiaChatProvider._as_text(delta.get('content')).strip()

    @staticmethod
    def _extract_stream_chunk(payload: dict) -> str:
        choices = payload.get('choices') or []
        fragments = []
        for choice in choices:
            delta = (choice or {}).get('delta') or {}
            value = delta.get('content')
            text = NvidiaChatProvider._as_text(value)
            if text:
                fragments.append(text)
        return ''.join(fragments)

    def _build_messages(self, request: ProviderRequest) -> list[dict]:
        messages = []
        if request.system_message:
            messages.append({'role': 'system', 'content': request.system_message})
        messages.append({'role': 'user', 'content': request.prompt})
        return messages

    def _headers(self, stream: bool) -> dict[str, str]:
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Accept': 'text/event-stream' if stream else 'application/json',
            'Content-Type': 'application/json',
        }

    def _thinking_payload(self) -> dict[str, str]:
        if self.thinking_enabled:
            return {'type': 'enabled'}
        return {'type': 'disabled'}

    def _payload_for_model(self, model_name: str, request: ProviderRequest, stream: bool) -> dict:
        return {
            'model': model_name,
            'messages': self._build_messages(request),
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'top_p': self.top_p,
            'stream': stream,
            # Official NVIDIA Kimi API expects a top-level `thinking` control object.
            'thinking': self._thinking_payload(),
        }

    def _post(self, payload: dict, stream: bool) -> requests.Response:
        self._ensure_configured()
        response = requests.post(
            self.invoke_url,
            headers=self._headers(stream=stream),
            json=payload,
            timeout=self.timeout_seconds,
            stream=stream,
        )
        if response.status_code >= 400:
            raise RuntimeError(f'{self.display_name} provider error {response.status_code}: {response.text[:300]}')
        return response

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        last_error: Exception | None = None
        for index, model_name in enumerate(self._candidate_models()):
            try:
                payload = self._payload_for_model(model_name, request=request, stream=False)
                response = self._post(payload, stream=False)
                try:
                    data = response.json()
                finally:
                    response.close()

                text = self._extract_completion_text(data)
                if not text:
                    raise RuntimeError(f'{self.display_name} provider returned an empty completion')

                if index > 0:
                    telemetry_event(
                        'llm.model_fallback_used',
                        payload={'provider': self.provider_name, 'selected_model': model_name, 'primary_model': self.model_name},
                        severity='warning',
                    )
                telemetry_metric('llm.generate.success_total', 1, tags={'provider': self.provider_name, 'model': model_name})
                return ProviderResponse(text=text, provider=self.provider_name, model=model_name)
            except Exception as exc:
                last_error = exc
                telemetry_event(
                    'llm.model_attempt_failed',
                    payload={'provider': self.provider_name, 'model': model_name, 'error': str(exc)},
                    severity='warning',
                )
                continue

        configured = ', '.join(self._candidate_models()) or self.model_name
        raise RuntimeError(f'All {self.display_name} models failed: {configured}') from last_error

    def stream(self, request: ProviderRequest) -> Generator[str, None, None]:
        last_error: Exception | None = None
        for index, model_name in enumerate(self._candidate_models()):
            yielded = False
            response = None
            try:
                payload = self._payload_for_model(model_name, request=request, stream=True)
                response = self._post(payload, stream=True)
                for raw_line in response.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    line = str(raw_line).strip()
                    if not line.startswith('data:'):
                        continue
                    data_part = line[5:].strip()
                    if data_part == '[DONE]':
                        break
                    try:
                        event = json.loads(data_part)
                    except json.JSONDecodeError:
                        continue
                    chunk = self._extract_stream_chunk(event)
                    if chunk:
                        yielded = True
                        yield chunk

                if yielded:
                    if index > 0:
                        telemetry_event(
                            'llm.model_fallback_used',
                            payload={'provider': self.provider_name, 'selected_model': model_name, 'primary_model': self.model_name},
                            severity='warning',
                        )
                    telemetry_metric('llm.stream.start_total', 1, tags={'provider': self.provider_name, 'model': model_name})
                    return
                raise RuntimeError(f'{self.display_name} provider returned an empty streaming response')
            except Exception as exc:
                if yielded:
                    raise
                last_error = exc
                telemetry_event(
                    'llm.model_attempt_failed',
                    payload={'provider': self.provider_name, 'model': model_name, 'error': str(exc)},
                    severity='warning',
                )
                continue
            finally:
                if response is not None:
                    response.close()

        configured = ', '.join(self._candidate_models()) or self.model_name
        raise RuntimeError(f'All {self.display_name} streaming models failed: {configured}') from last_error


class DeepSeekChatProvider(NvidiaChatProvider):
    provider_name = 'deepseek'
    display_name = 'DeepSeek'

    def __init__(
        self,
        model_name: str,
        api_key: str | None,
        base_url: str = 'https://api.deepseek.com',
        fallback_models: list[str] | None = None,
        max_tokens: int = 16384,
        temperature: float = 1.0,
        top_p: float = 1.0,
        thinking_enabled: bool = True,
        reasoning_effort: str = 'high',
        timeout_seconds: int = 60,
    ):
        super().__init__(
            model_name=model_name,
            api_key=api_key,
            invoke_url=self._chat_completion_url(base_url),
            fallback_models=fallback_models,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            thinking_enabled=thinking_enabled,
            timeout_seconds=timeout_seconds,
        )
        self.reasoning_effort = str(reasoning_effort or 'high').strip().lower()

    @staticmethod
    def _chat_completion_url(base_url: str | None) -> str:
        url = (base_url or '').strip().rstrip('/')
        if not url:
            url = 'https://api.deepseek.com'
        if url.endswith('/chat/completions'):
            return url
        return f'{url}/chat/completions'

    def _ensure_configured(self):
        if not self.api_key:
            telemetry_event('llm.provider_not_configured', payload={'provider': self.provider_name}, severity='warning')
            raise ProviderNotConfiguredError('AIDM_DEEPSEEK_API_KEY (or DEEPSEEK_API_KEY) is not configured')
        if not self.invoke_url:
            raise ProviderNotConfiguredError('AIDM_DEEPSEEK_BASE_URL is not configured')

    def _payload_for_model(self, model_name: str, request: ProviderRequest, stream: bool) -> dict:
        payload = super()._payload_for_model(model_name=model_name, request=request, stream=stream)
        if self.reasoning_effort in {'high', 'max'}:
            payload['reasoning_effort'] = self.reasoning_effort
        return payload


def _cfg(key: str, default=None):
    if has_app_context():
        value = current_app.config.get(key, None)
        if value is not None:
            return value
    return os.getenv(key, default)


def _cfg_list(key: str) -> list[str]:
    raw_value = _cfg(key, [])
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    if isinstance(raw_value, str):
        return [item.strip() for item in raw_value.split(',') if item.strip()]
    return []


def get_provider() -> BaseLLMProvider:
    provider_name = str(_cfg('AIDM_LLM_PROVIDER', 'gemini')).strip().lower()
    if provider_name not in SUPPORTED_LLM_PROVIDERS:
        raise ProviderNotConfiguredError(
            'Unsupported AIDM_LLM_PROVIDER '
            f'"{provider_name}". Expected one of: {", ".join(sorted(SUPPORTED_LLM_PROVIDERS))}.'
        )
    model_name = str(_cfg('AIDM_LLM_MODEL', DEFAULT_GEMINI_MODEL))
    fallback_models = _cfg_list('AIDM_LLM_FALLBACK_MODELS')

    if provider_name == 'gemini':
        return GeminiProvider(
            model_name=model_name,
            api_key=_cfg('GOOGLE_GENAI_API_KEY'),
            fallback_models=fallback_models,
        )
    if provider_name == 'deepseek':
        chosen_model = model_name or DEFAULT_DEEPSEEK_MODEL
        if chosen_model == DEFAULT_GEMINI_MODEL:
            chosen_model = DEFAULT_DEEPSEEK_MODEL
        thinking_enabled = str(_cfg('AIDM_DEEPSEEK_THINKING', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
        return DeepSeekChatProvider(
            model_name=chosen_model,
            api_key=_cfg(
                'AIDM_DEEPSEEK_API_KEY',
                os.getenv('DEEPSEEK_API_KEY') or os.getenv('AIDM_NVIDIA_API_KEY'),
            ),
            base_url=str(_cfg('AIDM_DEEPSEEK_BASE_URL', 'https://api.deepseek.com')),
            fallback_models=fallback_models,
            max_tokens=_int_env('AIDM_DEEPSEEK_MAX_TOKENS', 16384),
            temperature=_float_env('AIDM_DEEPSEEK_TEMPERATURE', 1.0),
            top_p=_float_env('AIDM_DEEPSEEK_TOP_P', 0.95),
            thinking_enabled=thinking_enabled,
            reasoning_effort=str(_cfg('AIDM_DEEPSEEK_REASONING_EFFORT', 'high')),
            timeout_seconds=_int_env('AIDM_DEEPSEEK_TIMEOUT_SECONDS', 180),
        )
    if provider_name in {'nvidia', 'kimi'}:
        chosen_model = model_name or DEFAULT_NVIDIA_MODEL
        if chosen_model == DEFAULT_GEMINI_MODEL:
            chosen_model = DEFAULT_NVIDIA_MODEL
        thinking_enabled = str(_cfg('AIDM_NVIDIA_THINKING', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
        default_temperature = 1.0 if thinking_enabled else 0.6
        return NvidiaChatProvider(
            model_name=chosen_model,
            api_key=_cfg('AIDM_NVIDIA_API_KEY', os.getenv('NVIDIA_API_KEY')),
            invoke_url=str(_cfg('AIDM_NVIDIA_INVOKE_URL', 'https://integrate.api.nvidia.com/v1')),
            fallback_models=fallback_models,
            max_tokens=_int_env('AIDM_NVIDIA_MAX_TOKENS', 16384),
            temperature=_float_env('AIDM_NVIDIA_TEMPERATURE', default_temperature),
            top_p=_float_env('AIDM_NVIDIA_TOP_P', 0.95),
            thinking_enabled=thinking_enabled,
            timeout_seconds=_int_env('AIDM_NVIDIA_TIMEOUT_SECONDS', 60),
        )

    return DeterministicFallbackProvider()


def _recent_actions_by_player(player_ids: list[int], limit_per_player: int = 3) -> dict[int, list[str]]:
    if not player_ids:
        return {}

    ranked_actions = (
        db.session.query(
            PlayerAction.player_id.label('player_id'),
            PlayerAction.action_text.label('action_text'),
            func.row_number()
            .over(
                partition_by=PlayerAction.player_id,
                order_by=(PlayerAction.timestamp.desc(), PlayerAction.action_id.desc()),
            )
            .label('row_number'),
        )
        .filter(PlayerAction.player_id.in_(player_ids))
        .subquery()
    )
    rows = (
        db.session.query(ranked_actions.c.player_id, ranked_actions.c.action_text)
        .filter(ranked_actions.c.row_number <= limit_per_player)
        .order_by(ranked_actions.c.player_id.asc(), ranked_actions.c.row_number.desc())
        .all()
    )

    recent_actions: dict[int, list[str]] = {}
    for row in rows:
        recent_actions.setdefault(int(row.player_id), []).append(str(row.action_text))
    return recent_actions


def build_dm_context(world_id, campaign_id, session_id=None, max_turns: int = 8, query_text: str | None = None):
    """Build deterministic bounded context for DM responses."""
    world = db.session.get(World, world_id)
    campaign = db.session.get(Campaign, campaign_id)

    world_summary = {
        'world_id': world_id,
        'name': world.name if world else 'Unknown',
        'description': world.description if world else 'No world data available.',
    }

    campaign_summary = {
        'campaign_id': campaign_id,
        'title': campaign.title if campaign else 'Unknown',
        'description': campaign.description if campaign else 'No campaign data available.',
        'current_quest': (campaign.current_quest if campaign else None) or 'None',
        'location': (campaign.location if campaign else None) or 'Unknown',
    }

    players = Player.query.filter_by(campaign_id=campaign_id).all()
    recent_actions_map = _recent_actions_by_player([player.player_id for player in players])
    active_players = []
    for player in players:
        active_players.append(
            {
                'player_id': player.player_id,
                'character_name': player.character_name,
                'race': player.race,
                'class': player.class_,
                'level': player.level,
                'inventory': inventory_payload(player.inventory),
                'recent_actions': recent_actions_map.get(player.player_id, []),
            }
        )

    recent_turns = []
    if session_id:
        turns = (
            DmTurn.query.filter_by(session_id=session_id)
            .order_by(DmTurn.turn_id.desc())
            .limit(max_turns)
            .all()
        )
        for turn in reversed(turns):
            recent_turns.append(
                {
                    'turn_id': turn.turn_id,
                    'player_id': turn.player_id,
                    'player_input': _truncate_text(turn.player_input, 240),
                    'dm_output': _truncate_text(turn.dm_output, 600),
                    'requires_roll': turn.requires_roll,
                    'rule_type': turn.rule_type,
                    'confidence': turn.confidence,
                    'roll_value': turn.roll_value,
                    'outcome_status': turn.outcome_status,
                }
            )

    recent_log = []
    if session_id and not recent_turns:
        entries = (
            SessionLogEntry.query.filter_by(session_id=session_id)
            .order_by(SessionLogEntry.timestamp.desc(), SessionLogEntry.id.desc())
            .limit(max_turns)
            .all()
        )
        recent_log = [entry.message for entry in reversed(entries)]

    pending_checks = []
    if session_id:
        pending_turns = (
            DmTurn.query.filter_by(session_id=session_id, outcome_status='deferred')
            .order_by(DmTurn.turn_id.asc())
            .limit(5)
            .all()
        )
        for turn in pending_turns:
            turn_hint = safe_json_loads(turn.rules_hint, {})
            pending_checks.append(
                {
                    'turn_id': turn.turn_id,
                    'player_input': turn.player_input,
                    'rule_type': turn.rule_type,
                    'dc_hint': turn_hint.get('dc_hint') if isinstance(turn_hint, dict) else None,
                }
            )

    segments = CampaignSegment.query.filter_by(campaign_id=campaign_id, is_triggered=True).all()
    triggered_segments = [
        {
            'segment_id': seg.segment_id,
            'title': seg.title,
            'description': seg.description,
            'tags': seg.tags,
        }
        for seg in segments
    ]

    session_state_payload = {
        'rolling_summary': '',
        'current_location': campaign_summary['location'],
        'current_quest': campaign_summary['current_quest'],
        'active_segments': [],
        'memory_snippets': [],
    }

    if session_id:
        state = SessionState.query.filter_by(session_id=session_id).first()
        if state:
            memory_snippets = safe_json_loads(state.memory_snippets, [])
            memory_snippets = memory_snippets if isinstance(memory_snippets, list) else []
            session_state_payload = {
                'rolling_summary': _truncate_text(state.rolling_summary, 4000),
                'current_location': state.current_location or campaign_summary['location'],
                'current_quest': state.current_quest or campaign_summary['current_quest'],
                'active_segments': safe_json_loads(state.active_segments, []),
                'memory_snippets': [
                    {
                        **snippet,
                        'player_input': _truncate_text(snippet.get('player_input'), 180),
                        'dm_output': _truncate_text(snippet.get('dm_output'), 260),
                    }
                    for snippet in memory_snippets[-8:]
                    if isinstance(snippet, dict)
                ],
            }

    emergent_memory = build_emergent_context(
        campaign_id=campaign_id,
        session_id=session_id,
        query_text=query_text,
        current_location=session_state_payload['current_location'],
        current_quest=session_state_payload['current_quest'],
        recent_turns=recent_turns,
    )

    context_payload = {
        'context_version': CONTEXT_VERSION,
        'generated_at': utc_now().isoformat(),
        'world': world_summary,
        'campaign': campaign_summary,
        'session_state': session_state_payload,
        'active_players': active_players,
        'triggered_segments': triggered_segments,
        'authored_segments': triggered_segments,
        'story_threads': emergent_memory.get('threads', []),
        'emergent_memory': emergent_memory,
        'recent_turns': recent_turns,
        'recent_log': recent_log,
        'pending_checks': pending_checks,
    }
    return json.dumps(context_payload, separators=(',', ':'), ensure_ascii=False)


def _system_message_for_dm():
    return (
        'You are a narrative-first Dungeons & Dragons Dungeon Master. '
        'Maintain immersion, keep continuity, and honor existing campaign context. '
        'Treat emergent_memory and story_threads as canon that arose through play. '
        'Treat authored_segments as optional prompts, not rails or hard boundaries on creativity. '
        'Follow RULES_HINT strictly when present. '
        'If RULES_HINT.requires_roll is false and pending_checks is empty, do not request a new roll. '
        'If RULES_HINT.resolved_turn_id is set with a roll_value, treat that pending check as resolved and advance the scene. '
        'If an action warrants a roll, request a roll and defer final outcomes until a roll result arrives. '
        'Never contradict established state unless you explain a plausible in-world reason.'
    )


def _fallback_dm_response(user_input: str) -> str:
    return (
        'The torchlight flickers as your action reshapes the moment. '
        'I can continue with continuity-safe narration while the primary model reconnects. '
        f'You attempt: "{user_input.strip()}". '
        'Tell me your next detail, or roll if this action requires one.'
    )


def _chunk_text_for_stream(text: str, max_chunk_size: int = 260):
    full_text = str(text or '')
    if not full_text:
        return

    start = 0
    length = len(full_text)
    while start < length:
        if length - start <= max_chunk_size:
            yield full_text[start:]
            return

        window_end = min(length, start + max_chunk_size)
        split_at = -1
        split_width = 0
        for marker in ('\n\n', '. ', '! ', '? ', '\n', ' '):
            idx = full_text.rfind(marker, start + 1, window_end + 1)
            if idx > split_at:
                split_at = idx
                split_width = len(marker)

        if split_at <= start:
            split_at = window_end
            split_width = 0
        else:
            split_at += split_width

        yield full_text[start:split_at]
        start = split_at


def query_dm_function(user_input, context, speaking_player_id=None, rules_hint: dict | None = None):
    rules_hint_section = ''
    if rules_hint:
        rules_hint_section = f"\n\nRULES_HINT:\n{json.dumps(rules_hint)}\n"
    request = ProviderRequest(
        prompt=f'CONTEXT:\n{context}\n{rules_hint_section}\nPLAYER ACTION:\n{user_input}\n',
        system_message=_system_message_for_dm(),
    )

    provider = get_provider()
    try:
        response = provider.generate(request)
        text = response.text.strip()
        return text if text else _fallback_dm_response(user_input)
    except Exception as exc:
        logger.warning('DM provider failure in query_dm_function: %s', str(exc))
        telemetry_event('llm.query_dm_function.failed', payload={'error': str(exc)}, severity='warning')
        return _fallback_dm_response(user_input)


def query_dm_function_stream(user_input, context, speaking_player=None, rules_hint: dict | None = None):
    speaker_text = ''
    if speaking_player:
        speaker_text = (
            f"\nCurrent speaker: {speaking_player.get('character_name')} "
            f"(ID: {speaking_player.get('player_id')})."
        )
    rules_hint_text = ''
    if rules_hint:
        rules_hint_text = f'\nRULES_HINT:\n{json.dumps(rules_hint)}\n'

    request = ProviderRequest(
        prompt=(
            f'{speaker_text}\n'
            f'CONTEXT:\n{context}\n\n'
            f'{rules_hint_text}'
            f'PLAYER INPUT:\n{user_input}\n'
        ),
        system_message=_system_message_for_dm(),
    )

    provider = get_provider()
    try:
        if isinstance(provider, NvidiaChatProvider):
            # NVIDIA/Kimi's SSE path has been materially less reliable than
            # single-shot generation for large campaign prompts. For gameplay,
            # prefer the stable completion path and stream it to the client in
            # application-sized chunks.
            response = provider.generate(request)
            text = response.text.strip()
            if text:
                for chunk in _chunk_text_for_stream(text):
                    yield chunk
                return
            yield _fallback_dm_response(user_input)
            return

        yielded = False
        for chunk in provider.stream(request):
            yielded = True
            if chunk:
                yield chunk
        if not yielded:
            yield _fallback_dm_response(user_input)
    except Exception as exc:
        logger.warning('DM provider failure in stream: %s', str(exc))
        telemetry_event('llm.query_dm_stream.failed', payload={'error': str(exc)}, severity='warning')
        yield _fallback_dm_response(user_input)


def query_gpt(prompt, system_message=None):
    request = ProviderRequest(prompt=prompt, system_message=system_message)
    provider = get_provider()
    try:
        response = provider.generate(request)
        return response.text.strip() or 'No summary available.'
    except Exception as exc:
        logger.warning('Provider failure in query_gpt: %s', str(exc))
        telemetry_event('llm.query_gpt.failed', payload={'error': str(exc)}, severity='warning')
        return 'Session summary is temporarily unavailable due to AI provider unavailability.'


def query_gpt_stream(prompt, system_message=None):
    request = ProviderRequest(prompt=prompt, system_message=system_message)
    provider = get_provider()

    try:
        yielded = False
        for chunk in provider.stream(request):
            yielded = True
            if chunk:
                yield chunk
        if not yielded:
            yield 'No summary available.'
    except Exception:
        yield 'Session summary is temporarily unavailable due to AI provider unavailability.'

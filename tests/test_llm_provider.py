from __future__ import annotations

import pytest

from aidm_server.contracts import ProviderRequest
from aidm_server.llm import (
    GeminiProvider,
    NvidiaChatProvider,
    ProviderNotConfiguredError,
    ProviderResponse,
    _chunk_text_for_stream,
    get_provider,
    query_dm_function_stream,
)


def test_get_provider_reads_fallback_models_from_env(monkeypatch):
    monkeypatch.setenv('AIDM_LLM_PROVIDER', 'gemini')
    monkeypatch.setenv('AIDM_LLM_MODEL', 'models/gemini-3-flash-preview')
    monkeypatch.setenv('AIDM_LLM_FALLBACK_MODELS', 'models/gemini-2.5-flash, models/gemini-flash-lite-latest')

    provider = get_provider()

    assert isinstance(provider, GeminiProvider)
    assert provider.model_name == 'models/gemini-3-flash-preview'
    assert provider.fallback_models == ['models/gemini-2.5-flash', 'models/gemini-flash-lite-latest']


def test_gemini_provider_generate_uses_fallback_model_when_primary_fails(monkeypatch):
    provider = GeminiProvider(
        model_name='models/gemini-3-flash-preview',
        api_key='fake-key',
        fallback_models=['models/gemini-2.5-flash'],
    )
    attempts: list[str] = []

    def fake_generate(model_name: str, full_prompt: str):
        attempts.append(model_name)
        if model_name == 'models/gemini-3-flash-preview':
            raise RuntimeError('model unavailable')
        return 'Fallback model response'

    monkeypatch.setattr(provider, '_generate_with_model', fake_generate)

    response = provider.generate(ProviderRequest(prompt='hello'))

    assert attempts == ['models/gemini-3-flash-preview', 'models/gemini-2.5-flash']
    assert response.text == 'Fallback model response'
    assert response.model == 'models/gemini-2.5-flash'


def test_gemini_provider_stream_uses_fallback_when_primary_fails_before_output(monkeypatch):
    provider = GeminiProvider(
        model_name='models/gemini-3-flash-preview',
        api_key='fake-key',
        fallback_models=['models/gemini-2.5-flash'],
    )
    attempts: list[str] = []

    def fake_stream(model_name: str, full_prompt: str):
        attempts.append(model_name)
        if model_name == 'models/gemini-3-flash-preview':
            raise RuntimeError('model unavailable')
        yield 'fallback chunk'

    monkeypatch.setattr(provider, '_stream_with_model', fake_stream)

    chunks = list(provider.stream(ProviderRequest(prompt='hello')))

    assert attempts == ['models/gemini-3-flash-preview', 'models/gemini-2.5-flash']
    assert chunks == ['fallback chunk']


def test_gemini_provider_stream_does_not_mix_models_after_partial_output(monkeypatch):
    provider = GeminiProvider(
        model_name='models/gemini-3-flash-preview',
        api_key='fake-key',
        fallback_models=['models/gemini-2.5-flash'],
    )
    attempts: list[str] = []

    def fake_stream(model_name: str, full_prompt: str):
        attempts.append(model_name)
        if model_name == 'models/gemini-3-flash-preview':
            yield 'partial chunk'
            raise RuntimeError('stream interrupted')
        yield 'fallback chunk'

    monkeypatch.setattr(provider, '_stream_with_model', fake_stream)

    stream_iter = provider.stream(ProviderRequest(prompt='hello'))
    assert next(stream_iter) == 'partial chunk'
    with pytest.raises(RuntimeError):
        next(stream_iter)

    assert attempts == ['models/gemini-3-flash-preview']


def test_extract_text_preserves_stream_whitespace():
    class _Chunk:
        text = ' leading-space'

    text = GeminiProvider._extract_text(_Chunk(), preserve_whitespace=True)
    assert text == ' leading-space'


def test_gemini_provider_skips_primary_when_rate_limited_cooldown_active(monkeypatch):
    import aidm_server.llm as llm_module

    monkeypatch.setattr(llm_module, 'GEMINI_RATE_LIMIT_THRESHOLD', 1)
    monkeypatch.setattr(llm_module, 'GEMINI_RATE_LIMIT_COOLDOWN_SECONDS', 120)
    GeminiProvider._rate_limit_state.clear()

    provider = GeminiProvider(
        model_name='models/gemini-3-flash-preview',
        api_key='fake-key',
        fallback_models=['models/gemini-2.5-flash'],
    )
    attempts: list[str] = []

    def fake_generate(model_name: str, full_prompt: str):
        attempts.append(model_name)
        if model_name == 'models/gemini-3-flash-preview':
            raise RuntimeError('429 Too Many Requests')
        return 'Fallback works'

    monkeypatch.setattr(provider, '_generate_with_model', fake_generate)

    first = provider.generate(ProviderRequest(prompt='hello one'))
    second = provider.generate(ProviderRequest(prompt='hello two'))

    assert first.model == 'models/gemini-2.5-flash'
    assert second.model == 'models/gemini-2.5-flash'
    assert attempts == [
        'models/gemini-3-flash-preview',
        'models/gemini-2.5-flash',
        'models/gemini-2.5-flash',
    ]


def test_get_provider_supports_nvidia(monkeypatch):
    monkeypatch.setenv('AIDM_LLM_PROVIDER', 'nvidia')
    monkeypatch.setenv('AIDM_LLM_MODEL', 'moonshotai/kimi-k2.5')
    monkeypatch.setenv('AIDM_NVIDIA_API_KEY', 'nvapi-test')
    monkeypatch.setenv('AIDM_NVIDIA_INVOKE_URL', 'https://integrate.api.nvidia.com/v1/chat/completions')

    provider = get_provider()

    assert isinstance(provider, NvidiaChatProvider)
    assert provider.model_name == 'moonshotai/kimi-k2.5'


def test_get_provider_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv('AIDM_LLM_PROVIDER', 'typo-provider')

    with pytest.raises(ProviderNotConfiguredError):
        get_provider()


def test_nvidia_provider_generate_parses_openai_shape(monkeypatch):
    import aidm_server.llm as llm_module

    class _FakeResponse:
        status_code = 200
        text = ''

        def json(self):
            return {'choices': [{'message': {'content': 'Kimi is online.'}}]}

        def close(self):
            return None

    def fake_post(url, headers, json, timeout, stream):
        assert stream is False
        assert url == 'https://integrate.api.nvidia.com/v1/chat/completions'
        assert json['model'] == 'moonshotai/kimi-k2.5'
        assert json['thinking'] == {'type': 'enabled'}
        assert 'chat_template_kwargs' not in json
        return _FakeResponse()

    monkeypatch.setattr(llm_module.requests, 'post', fake_post)

    provider = NvidiaChatProvider(
        model_name='moonshotai/kimi-k2.5',
        api_key='nvapi-test',
        invoke_url='https://integrate.api.nvidia.com/v1/chat/completions',
    )
    response = provider.generate(ProviderRequest(prompt='hello'))

    assert response.provider == 'nvidia'
    assert response.model == 'moonshotai/kimi-k2.5'
    assert response.text == 'Kimi is online.'


def test_nvidia_provider_normalizes_base_v1_endpoint():
    provider = NvidiaChatProvider(
        model_name='moonshotai/kimi-k2.5',
        api_key='nvapi-test',
        invoke_url='https://integrate.api.nvidia.com/v1',
    )
    assert provider.invoke_url == 'https://integrate.api.nvidia.com/v1/chat/completions'


def test_nvidia_provider_stream_parses_sse_chunks(monkeypatch):
    import aidm_server.llm as llm_module

    class _FakeStreamResponse:
        status_code = 200
        text = ''

        def iter_lines(self, decode_unicode=True):
            yield 'data: {"choices":[{"delta":{"content":"Hello "}}]}'
            yield 'data: {"choices":[{"delta":{"content":"world"}}]}'
            yield 'data: [DONE]'

        def close(self):
            return None

    def fake_post(url, headers, json, timeout, stream):
        assert stream is True
        assert json['thinking'] == {'type': 'enabled'}
        return _FakeStreamResponse()

    monkeypatch.setattr(llm_module.requests, 'post', fake_post)

    provider = NvidiaChatProvider(
        model_name='moonshotai/kimi-k2.5',
        api_key='nvapi-test',
        invoke_url='https://integrate.api.nvidia.com/v1/chat/completions',
    )
    chunks = list(provider.stream(ProviderRequest(prompt='hello')))
    assert chunks == ['Hello ', 'world']


def test_nvidia_provider_instant_mode_sets_disabled_thinking(monkeypatch):
    import aidm_server.llm as llm_module

    class _FakeResponse:
        status_code = 200
        text = ''

        def json(self):
            return {'choices': [{'message': {'content': 'Instant mode response'}}]}

        def close(self):
            return None

    def fake_post(url, headers, json, timeout, stream):
        assert json['thinking'] == {'type': 'disabled'}
        return _FakeResponse()

    monkeypatch.setattr(llm_module.requests, 'post', fake_post)

    provider = NvidiaChatProvider(
        model_name='moonshotai/kimi-k2.5',
        api_key='nvapi-test',
        invoke_url='https://integrate.api.nvidia.com/v1',
        thinking_enabled=False,
    )
    response = provider.generate(ProviderRequest(prompt='hello'))
    assert response.text == 'Instant mode response'


def test_query_dm_function_stream_uses_generate_chunking_for_nvidia(monkeypatch):
    provider = NvidiaChatProvider(
        model_name='moonshotai/kimi-k2.5',
        api_key='nvapi-test',
        invoke_url='https://integrate.api.nvidia.com/v1',
    )

    def fail_stream(_request):
        raise AssertionError('provider.stream should not be used for NVIDIA query_dm_function_stream')

    def fake_generate(_request):
        return ProviderResponse(
            text='First sentence. Second sentence. Third sentence.',
            provider='nvidia',
            model='moonshotai/kimi-k2.5',
        )

    monkeypatch.setattr(provider, 'stream', fail_stream)
    monkeypatch.setattr(provider, 'generate', fake_generate)
    monkeypatch.setattr('aidm_server.llm.get_provider', lambda: provider)

    chunks = list(query_dm_function_stream('hello', '{"campaign":"test"}'))

    assert ''.join(chunk if chunk.endswith(' ') else f'{chunk} ' for chunk in chunks).strip().startswith('First sentence.')
    assert len(chunks) >= 1


def test_chunk_text_for_stream_preserves_boundary_whitespace():
    text = 'The ash settles. Liora stands beside you.\n\nYou ask what comes next.'
    chunks = list(_chunk_text_for_stream(text, max_chunk_size=24))

    assert ''.join(chunks) == text

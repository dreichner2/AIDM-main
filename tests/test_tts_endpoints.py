from __future__ import annotations

import aidm_server.blueprints.system as system_blueprint


def test_tts_config_reports_missing_key(client):
    response = client.get('/api/tts/config')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['provider'] == 'deepgram'
    assert payload['configured'] is False
    assert payload['model'] == 'aura-2-draco-en'


def test_tts_speak_requires_api_key(client):
    response = client.post('/api/tts/speak', json={'text': 'The torches flicker.'})

    assert response.status_code == 503
    assert response.get_json()['error_code'] == 'tts_not_configured'


def test_tts_speak_proxies_deepgram_audio(client, app, monkeypatch):
    app.config['AIDM_DEEPGRAM_API_KEY'] = 'test-key'
    app.config['AIDM_DEEPGRAM_TTS_MODEL'] = 'aura-2-draco-en'
    captured = {}

    class FakeDeepgramResponse:
        ok = True
        content = b'mp3-bytes'
        status_code = 200
        text = ''
        headers = {'Content-Type': 'audio/mpeg'}

        def iter_content(self, chunk_size=1024):
            del chunk_size
            yield self.content

        def close(self):
            pass

    def fake_tts_request(api_key, model, text, *, stream=False):
        captured['api_key'] = api_key
        captured['model'] = model
        captured['text'] = text
        captured['stream'] = stream
        return FakeDeepgramResponse()

    monkeypatch.setattr(system_blueprint, '_deepgram_tts_request', fake_tts_request)

    response = client.post('/api/tts/speak', json={'text': 'The torches flicker.'})

    assert response.status_code == 200
    assert response.data == b'mp3-bytes'
    assert response.mimetype == 'audio/mpeg'
    assert captured['api_key'] == 'test-key'
    assert captured['model'] == 'aura-2-draco-en'
    assert captured['text'] == 'The torches flicker.'
    assert captured['stream'] is True


def test_tts_speak_strips_reasoning_tags_before_proxying(client, app, monkeypatch):
    app.config['AIDM_DEEPGRAM_API_KEY'] = 'test-key'
    captured = {}

    class FakeDeepgramResponse:
        ok = True
        content = b'audio'
        status_code = 200
        text = ''
        headers = {'Content-Type': 'audio/mpeg'}

        def iter_content(self, chunk_size=1024):
            del chunk_size
            yield self.content

        def close(self):
            pass

    def fake_tts_request(api_key, model, text, *, stream=False):
        del api_key, model, stream
        captured['text'] = text
        return FakeDeepgramResponse()

    monkeypatch.setattr(system_blueprint, '_deepgram_tts_request', fake_tts_request)

    response = client.post('/api/tts/speak', json={'text': 'Speak. <thought>hidden</thought> Continue.'})

    assert response.status_code == 200
    assert captured['text'] == 'Speak. Continue.'


def test_tts_speak_normalizes_markdown_before_proxying(client, app, monkeypatch):
    app.config['AIDM_DEEPGRAM_API_KEY'] = 'test-key'
    captured = {}

    class FakeDeepgramResponse:
        ok = True
        content = b'audio'
        status_code = 200
        text = ''
        headers = {'Content-Type': 'audio/mpeg'}

        def iter_content(self, chunk_size=1024):
            del chunk_size
            yield self.content

        def close(self):
            pass

    def fake_tts_request(api_key, model, text, *, stream=False):
        del api_key, model, stream
        captured['text'] = text
        return FakeDeepgramResponse()

    monkeypatch.setattr(system_blueprint, '_deepgram_tts_request', fake_tts_request)

    response = client.post(
        '/api/tts/speak',
        json={'text': '## Arrival\n- **Open** the [gate](https://example.test).\n`Carefully`.'},
    )

    assert response.status_code == 200
    assert captured['text'] == 'Arrival Open the gate. Carefully.'


def test_tts_speak_chunks_long_text(client, app, monkeypatch):
    app.config['AIDM_DEEPGRAM_API_KEY'] = 'test-key'
    app.config['AIDM_DEEPGRAM_TTS_MODEL'] = 'aura-2-draco-en'
    chunks_received = []

    class FakeDeepgramResponse:
        ok = True
        content = b'audio'
        status_code = 200
        text = ''
        headers = {'Content-Type': 'audio/mpeg'}

        def iter_content(self, chunk_size=1024):
            del chunk_size
            yield self.content

        def close(self):
            pass

    def fake_tts_request(api_key, model, text, *, stream=False):
        assert stream is True
        chunks_received.append(text)
        return FakeDeepgramResponse()

    monkeypatch.setattr(system_blueprint, '_deepgram_tts_request', fake_tts_request)

    # Build text longer than DEEPGRAM_CHUNK_LIMIT (2000 chars)
    long_text = 'The torches flicker in the ancient hall. ' * 60  # ~2400 chars
    response = client.post('/api/tts/speak', json={'text': long_text})

    assert response.status_code == 200
    assert response.data == b'audio' * len(system_blueprint._chunk_text_for_tts(long_text))
    assert len(chunks_received) >= 2
    for chunk in chunks_received:
        assert len(chunk) <= system_blueprint.DEEPGRAM_CHUNK_LIMIT
    assert response.data == b'audio' * len(chunks_received)


def test_chunk_text_for_tts_short_text():
    result = system_blueprint._chunk_text_for_tts('Hello world.', max_chars=2000)
    assert result == ['Hello world.']


def test_chunk_text_for_tts_splits_on_sentence():
    text = 'First sentence. Second sentence. Third sentence.'
    result = system_blueprint._chunk_text_for_tts(text, max_chars=35)
    assert all(len(c) <= 35 for c in result)
    assert len(result) >= 2


def test_llm_config_rejects_ambiguous_persist_boolean(client):
    response = client.patch(
        '/api/llm/config',
        json={'provider': 'fallback', 'model': 'deterministic-v1', 'persist': 'not-sure'},
    )

    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'validation_error'


def test_llm_config_rejects_persistent_writes_outside_local_env(client, app):
    app.config['AIDM_ENV'] = 'production'

    response = client.patch(
        '/api/llm/config',
        json={'provider': 'fallback', 'model': 'deterministic-v1', 'persist': True},
    )

    assert response.status_code == 403
    assert response.get_json()['error_code'] == 'llm_config_persist_disabled'

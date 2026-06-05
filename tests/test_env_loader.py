from __future__ import annotations

import os

from aidm_server.env_loader import load_runtime_env


def test_load_runtime_env_prefers_env_local(tmp_path, monkeypatch):
    root = tmp_path
    (root / '.env').write_text('AIDM_LLM_PROVIDER=gemini\nAIDM_LLM_MODEL=models/gemini-3-flash-preview\n', encoding='utf-8')
    (root / '.env.local').write_text(
        'AIDM_LLM_PROVIDER=nvidia\nAIDM_LLM_MODEL=moonshotai/kimi-k2.5\nAIDM_LLM_FALLBACK_MODELS=\n',
        encoding='utf-8',
    )

    monkeypatch.delenv('AIDM_LLM_PROVIDER', raising=False)
    monkeypatch.delenv('AIDM_LLM_MODEL', raising=False)
    monkeypatch.delenv('AIDM_LLM_FALLBACK_MODELS', raising=False)

    load_runtime_env(root)

    assert os.getenv('AIDM_LLM_PROVIDER') == 'nvidia'
    assert os.getenv('AIDM_LLM_MODEL') == 'moonshotai/kimi-k2.5'
    assert os.getenv('AIDM_LLM_FALLBACK_MODELS') == ''

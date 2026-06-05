from __future__ import annotations

from pathlib import Path

from scripts.scan_secrets import scan_paths


def test_secret_scan_detects_likely_committed_api_key(tmp_path):
    source = tmp_path / 'bad.py'
    source.write_text(
        'DEEPGRAM_API_KEY = "' + '0123456789abcdef0123456789abcdef' + '"\n',
        encoding='utf-8',
    )

    findings = scan_paths([source])

    assert len(findings) == 1
    assert findings[0].path == source
    assert findings[0].kind == 'Deepgram-looking API key'


def test_secret_scan_allows_placeholders_and_ignored_local_env(tmp_path):
    example = tmp_path / '.env.local.example'
    example.write_text('AIDM_API_AUTH_TOKENS=your-token-placeholder\n', encoding='utf-8')
    local_env = tmp_path / '.env.local'
    local_env.write_text(
        'DEEPGRAM_API_KEY = "' + '0123456789abcdef0123456789abcdef' + '"\n',
        encoding='utf-8',
    )

    findings = scan_paths([tmp_path])

    assert findings == []


def test_secret_scan_skips_generated_directories(tmp_path):
    generated = tmp_path / 'aidm_frontend' / 'node_modules' / 'pkg'
    generated.mkdir(parents=True)
    source = generated / 'index.js'
    source.write_text(
        'const token = "' + '0123456789abcdef0123456789abcdef' + '";\n',
        encoding='utf-8',
    )

    findings = scan_paths([tmp_path])

    assert findings == []

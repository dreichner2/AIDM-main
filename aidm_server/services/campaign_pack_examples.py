from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EXAMPLE_PACKS_DIR = Path(__file__).resolve().parents[2] / 'docs' / 'examples'
EXAMPLE_PACK_GLOB = '*.json'
SHORT_DESCRIPTION_LENGTH = 180


def list_example_campaign_pack_summaries() -> list[dict[str, Any]]:
    return [_summary_payload(entry) for entry in _example_campaign_packs()]


def get_example_campaign_pack(pack_id: str) -> dict[str, Any] | None:
    normalized_pack_id = str(pack_id or '').strip()
    if not normalized_pack_id:
        return None
    for entry in _example_campaign_packs():
        if entry['pack_id'] == normalized_pack_id:
            return entry
    return None


def _example_campaign_packs() -> tuple[dict[str, Any], ...]:
    entries: list[dict[str, Any]] = []
    for pack_path in sorted(EXAMPLE_PACKS_DIR.glob(EXAMPLE_PACK_GLOB)):
        try:
            with pack_path.open('r', encoding='utf-8') as pack_file:
                manifest = json.load(pack_file)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict):
            continue

        pack_id = _text(_first(manifest, 'packId', 'pack_id'))
        title = _text(_first(manifest, 'title', 'name'))
        if not pack_id or not title:
            continue
        description = _text(_first(manifest, 'description', 'summary'))
        world = _record(_first(manifest, 'world', 'worldSettings', 'world_settings'))
        entries.append(
            {
                'pack_id': pack_id,
                'title': title,
                'description': description,
                'short_description': _short_description(description),
                'version': _text(_first(manifest, 'version')),
                'schema_version': _text(_first(manifest, 'schemaVersion', 'schema_version')) or '1',
                'source_filename': pack_path.name,
                'world_name': _text(_first(world, 'name', 'title')),
                'manifest': manifest,
            }
        )
    return tuple(entries)


def _summary_payload(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        'pack_id': entry['pack_id'],
        'title': entry['title'],
        'description': entry['description'],
        'short_description': entry['short_description'],
        'version': entry['version'],
        'schema_version': entry['schema_version'],
        'source_filename': entry['source_filename'],
        'world_name': entry['world_name'],
        'source': 'bundled_example',
    }


def _short_description(description: str) -> str:
    cleaned = ' '.join(str(description or '').split())
    if len(cleaned) <= SHORT_DESCRIPTION_LENGTH:
        return cleaned
    clipped = cleaned[:SHORT_DESCRIPTION_LENGTH].rsplit(' ', 1)[0].rstrip('.,;:')
    return f'{clipped}...'


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record.get(key) not in (None, ''):
            return record.get(key)
    return None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ''

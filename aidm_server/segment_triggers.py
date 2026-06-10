"""Segment trigger parsing and evaluation."""

from __future__ import annotations

from dataclasses import asdict

from aidm_server.contracts import SegmentTriggerSpec
from aidm_server.models import safe_json_loads


def _search_values(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).lower() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).lower() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text.lower()] if text else []


def _contains_value(needle: str, values: list[str]) -> bool:
    return any(needle in value for value in values)


def parse_trigger_spec(trigger_condition: str | None) -> SegmentTriggerSpec:
    raw_text = (trigger_condition or "").strip()
    if not raw_text:
        return SegmentTriggerSpec(trigger_type="manual", raw={"trigger_condition": ""})

    raw = safe_json_loads(raw_text, None)
    if isinstance(raw, dict):
        trigger_type = str(raw.get("type", "manual")).strip().lower()
        return SegmentTriggerSpec(trigger_type=trigger_type or "manual", raw=raw)

    keywords = [k.strip().lower() for k in raw_text.split(",") if k.strip()]
    return SegmentTriggerSpec(trigger_type="keywords", raw={"keywords": keywords, "match": "any"})


def evaluate_segment_trigger(
    trigger_condition: str | None,
    player_message: str,
    session_state: dict | None,
    campaign_state: dict | None,
) -> tuple[bool, str, dict]:
    spec = parse_trigger_spec(trigger_condition)
    text = (player_message or "").lower()
    session_state = session_state or {}
    campaign_state = campaign_state or {}

    if spec.trigger_type == "manual":
        return False, "manual_trigger_only", asdict(spec)

    if spec.trigger_type == "keywords":
        keywords = [str(k).lower() for k in spec.raw.get("keywords", []) if str(k).strip()]
        if not keywords:
            return False, "no_keywords_configured", asdict(spec)

        match_mode = str(spec.raw.get("match", "any")).lower()
        if match_mode == "all":
            matched = all(k in text for k in keywords)
        else:
            matched = any(k in text for k in keywords)

        reason = f"keywords:{','.join(keywords)}"
        return matched, reason, asdict(spec)

    if spec.trigger_type == "state":
        location_contains = str(spec.raw.get("location_contains", "")).lower().strip()
        quest_contains = str(spec.raw.get("quest_contains", "")).lower().strip()

        location_values = [
            *_search_values(session_state.get("current_location")),
            *_search_values(session_state.get("current_location_id")),
        ]
        if not location_values:
            location_values = _search_values(campaign_state.get("location"))

        active_quest_values = [
            *_search_values(session_state.get("active_quest_texts")),
            *_search_values(session_state.get("active_quest_ids")),
            *_search_values(session_state.get("active_quest_titles")),
            *_search_values(session_state.get("active_quest_stages")),
            *_search_values(session_state.get("active_quest_summaries")),
            *_search_values(session_state.get("active_quest_objectives")),
        ]
        quest_values = active_quest_values
        if not quest_values:
            quest_values = [
                *_search_values(session_state.get("current_quest")),
                *_search_values(campaign_state.get("current_quest")),
            ]

        location_ok = True if not location_contains else _contains_value(location_contains, location_values)
        quest_ok = True if not quest_contains else _contains_value(quest_contains, quest_values)

        matched = location_ok and quest_ok
        reason = f"state:location={location_contains or '*'};quest={quest_contains or '*'}"
        return matched, reason, asdict(spec)

    return False, f"unsupported_trigger_type:{spec.trigger_type}", asdict(spec)

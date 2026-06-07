"""Segment trigger parsing and evaluation."""

from __future__ import annotations

from dataclasses import asdict

from aidm_server.contracts import SegmentTriggerSpec
from aidm_server.models import safe_json_loads


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

        location = str(session_state.get("current_location") or campaign_state.get("location") or "").lower()
        quest = str(session_state.get("current_quest") or campaign_state.get("current_quest") or "").lower()

        location_ok = True if not location_contains else (location_contains in location)
        quest_ok = True if not quest_contains else (quest_contains in quest)

        matched = location_ok and quest_ok
        reason = f"state:location={location_contains or '*'};quest={quest_contains or '*'}"
        return matched, reason, asdict(spec)

    return False, f"unsupported_trigger_type:{spec.trigger_type}", asdict(spec)

"""Session projection updates derived from accepted canon and turns."""

from __future__ import annotations

from aidm_server.models import (
    Campaign,
    DmTurn,
    StoryFact,
    StoryThread,
    get_or_create_session_state,
    safe_json_dumps,
    safe_json_loads,
)
from aidm_server.time_utils import utc_now


def append_session_memory(turn: DmTurn):
    state = get_or_create_session_state(turn.session_id, turn.campaign)
    memory_snippets = safe_json_loads(state.memory_snippets, [])
    memory_snippets = memory_snippets if isinstance(memory_snippets, list) else []
    memory_snippets = [
        snippet
        for snippet in memory_snippets
        if not isinstance(snippet, dict) or snippet.get('turn_id') != turn.turn_id
    ]
    memory_snippets.append(
        {
            'turn_id': turn.turn_id,
            'player_input': turn.player_input[:250],
            'dm_output': (turn.dm_output or '')[:350],
            'requires_roll': turn.requires_roll,
            'rule_type': turn.rule_type,
            'confidence': turn.confidence,
            'roll_value': turn.roll_value,
            'outcome_status': turn.outcome_status,
            'created_at': utc_now().isoformat(),
        }
    )
    state.memory_snippets = safe_json_dumps(memory_snippets[-12:], [])

    existing_summary = (state.rolling_summary or '').strip()
    next_line = f"T{turn.turn_id} | P{turn.player_id}: {turn.player_input[:160]} | DM: {(turn.dm_output or '')[:220]}"
    summary_lines = [
        line
        for line in existing_summary.splitlines()
        if not line.startswith(f"T{turn.turn_id} | ")
    ]
    summary_lines.append(next_line)
    state.rolling_summary = '\n'.join(summary_lines).strip()[-8000:]
    state.updated_at = utc_now()
    return state


def _latest_location_fact(campaign_id: int) -> StoryFact | None:
    return (
        StoryFact.query.filter(
            StoryFact.campaign_id == campaign_id,
            StoryFact.predicate == 'current_location',
            StoryFact.fact_status == 'accepted',
        )
        .order_by(StoryFact.fact_id.desc())
        .first()
    )


def refresh_session_projection(session_id: int, campaign: Campaign, triggered_segments: list[dict] | None = None):
    triggered_segments = triggered_segments or []
    state = get_or_create_session_state(session_id, campaign)

    location_fact = _latest_location_fact(campaign.campaign_id)
    if location_fact and location_fact.value_text:
        state.current_location = location_fact.value_text
    elif not state.current_location:
        state.current_location = campaign.location

    open_threads = (
        StoryThread.query.filter(
            StoryThread.campaign_id == campaign.campaign_id,
            StoryThread.status.in_(('open', 'active')),
        )
        .order_by(StoryThread.priority.desc(), StoryThread.updated_at.desc(), StoryThread.thread_id.desc())
        .limit(3)
        .all()
    )
    if open_threads:
        state.current_quest = ' | '.join(thread.title for thread in open_threads)
    else:
        state.current_quest = campaign.current_quest

    active_segments = safe_json_loads(state.active_segments, [])
    active_segments = active_segments if isinstance(active_segments, list) else []
    for segment_payload in triggered_segments:
        if not any(existing.get('segment_id') == segment_payload.get('segment_id') for existing in active_segments):
            active_segments.append(segment_payload)
    state.active_segments = safe_json_dumps(active_segments, [])
    state.updated_at = utc_now()
    return state

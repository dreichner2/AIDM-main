"""Relevant canon retrieval for DM prompt context."""

from __future__ import annotations

from sqlalchemy.orm import joinedload

from aidm_server.canon_text import normalized_name
from aidm_server.models import SessionState, StoryEntity, StoryFact, StoryThread, safe_json_loads


EMERGENT_ENTITY_CANDIDATE_LIMIT = 240
EMERGENT_FACT_CANDIDATE_LIMIT = 480
EMERGENT_THREAD_CANDIDATE_LIMIT = 160

_GLOBAL_SINGLETON_FACTS = {'current_location', 'current_quest'}
_RETRIEVAL_STOPWORDS = {
    'a',
    'an',
    'and',
    'at',
    'for',
    'from',
    'into',
    'is',
    'of',
    'on',
    'or',
    'the',
    'to',
    'with',
}


def _candidate_labels(entity: StoryEntity) -> set[str]:
    labels = {
        normalized_name(entity.name),
        normalized_name(entity.canonical_name),
    }
    aliases = safe_json_loads(entity.aliases_json, [])
    aliases = aliases if isinstance(aliases, list) else []
    labels.update(normalized_name(alias) for alias in aliases)
    return {label for label in labels if label}


def _retrieval_tokens(*values: str | None) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        normalized = normalized_name(value)
        if not normalized:
            continue
        for token in normalized.split():
            if len(token) < 3 or token in _RETRIEVAL_STOPWORDS:
                continue
            tokens.add(token)
    return tokens


def _recent_signal_text(recent_turns: list[dict] | None) -> str:
    if not recent_turns:
        return ''
    fragments: list[str] = []
    for turn in recent_turns[-3:]:
        if not isinstance(turn, dict):
            continue
        player_input = str(turn.get('player_input') or '').strip()
        dm_output = str(turn.get('dm_output') or '').strip()
        if player_input:
            fragments.append(player_input)
        if dm_output:
            fragments.append(dm_output[:160])
    return '\n'.join(fragments)


def _entity_retrieval_score(
    entity: StoryEntity,
    *,
    signal_text: str,
    signal_tokens: set[str],
    session_id: int | None,
) -> float:
    score = 0.0
    labels = _candidate_labels(entity)
    if signal_text:
        for label in labels:
            if label and label in signal_text:
                score += 10.0
    for label in labels:
        overlap = len(set(label.split()) & signal_tokens)
        if overlap:
            score += overlap * 3.0
    summary_tokens = _retrieval_tokens(entity.summary)
    summary_overlap = len(summary_tokens & signal_tokens)
    if summary_overlap:
        score += summary_overlap * 1.5
    if session_id is not None and entity.session_id == session_id:
        score += 1.0
    if str(entity.status or '').lower() in {'active', 'open'}:
        score += 0.5
    return score


def _fact_retrieval_score(
    fact: StoryFact,
    *,
    signal_text: str,
    signal_tokens: set[str],
    relevant_entity_ids: set[int],
) -> float:
    score = 0.0
    if fact.subject_entity_id in relevant_entity_ids:
        score += 5.0
    if fact.object_entity_id in relevant_entity_ids:
        score += 4.0
    if fact.predicate in _GLOBAL_SINGLETON_FACTS:
        score += 2.5

    predicate_tokens = _retrieval_tokens(fact.predicate)
    value_tokens = _retrieval_tokens(fact.value_text)
    score += len(predicate_tokens & signal_tokens) * 2.0
    score += len(value_tokens & signal_tokens) * 1.0

    subject_name = fact.subject_entity.name if fact.subject_entity else None
    object_name = fact.object_entity.name if fact.object_entity else None
    for name in (subject_name, object_name):
        normalized = normalized_name(name)
        if normalized and normalized in signal_text:
            score += 3.0
    return score


def _thread_retrieval_score(thread: StoryThread, *, signal_text: str, signal_tokens: set[str]) -> float:
    score = float(thread.priority or 0)
    if str(thread.status or '').lower() in {'open', 'active'}:
        score += 2.0
    title_tokens = _retrieval_tokens(thread.title)
    summary_tokens = _retrieval_tokens(thread.summary)
    score += len(title_tokens & signal_tokens) * 2.5
    score += len(summary_tokens & signal_tokens) * 1.0
    normalized_title = normalized_name(thread.title)
    if normalized_title and normalized_title in signal_text:
        score += 4.0
    return score


def build_emergent_context(
    campaign_id: int,
    session_id: int | None = None,
    entity_limit: int = 12,
    fact_limit: int = 20,
    thread_limit: int = 8,
    entity_candidate_limit: int | None = None,
    fact_candidate_limit: int | None = None,
    thread_candidate_limit: int | None = None,
    query_text: str | None = None,
    current_location: str | None = None,
    current_quest: str | None = None,
    recent_turns: list[dict] | None = None,
) -> dict:
    recent_signal = _recent_signal_text(recent_turns)
    signal_text = normalized_name(
        ' '.join(
            part
            for part in [
                query_text or '',
                current_location or '',
                current_quest or '',
                recent_signal,
            ]
            if part
        )
    )
    signal_tokens = _retrieval_tokens(query_text, current_location, current_quest, recent_signal)

    entity_candidate_limit = min(
        max(entity_limit * 8, entity_limit),
        entity_candidate_limit or EMERGENT_ENTITY_CANDIDATE_LIMIT,
    )
    fact_candidate_limit = min(
        max(fact_limit * 8, fact_limit),
        fact_candidate_limit or EMERGENT_FACT_CANDIDATE_LIMIT,
    )
    thread_candidate_limit = min(
        max(thread_limit * 8, thread_limit),
        thread_candidate_limit or EMERGENT_THREAD_CANDIDATE_LIMIT,
    )

    all_entities = (
        StoryEntity.query.filter_by(campaign_id=campaign_id)
        .order_by(StoryEntity.updated_at.desc(), StoryEntity.entity_id.desc())
        .limit(entity_candidate_limit)
        .all()
    )
    ranked_entities = sorted(
        all_entities,
        key=lambda entity: (
            _entity_retrieval_score(entity, signal_text=signal_text, signal_tokens=signal_tokens, session_id=session_id),
            entity.updated_at or entity.created_at,
            entity.entity_id,
        ),
        reverse=True,
    )
    entities = ranked_entities[:entity_limit]
    relevant_entity_ids = {entity.entity_id for entity in entities}

    all_facts = (
        StoryFact.query.options(
            joinedload(StoryFact.subject_entity),
            joinedload(StoryFact.object_entity),
        )
        .filter(
            StoryFact.campaign_id == campaign_id,
            StoryFact.fact_status == 'accepted',
        )
        .order_by(StoryFact.fact_id.desc())
        .limit(fact_candidate_limit)
        .all()
    )
    ranked_facts = sorted(
        all_facts,
        key=lambda fact: (
            _fact_retrieval_score(
                fact,
                signal_text=signal_text,
                signal_tokens=signal_tokens,
                relevant_entity_ids=relevant_entity_ids,
            ),
            fact.fact_id,
        ),
        reverse=True,
    )
    if ranked_facts and _fact_retrieval_score(
        ranked_facts[0],
        signal_text=signal_text,
        signal_tokens=signal_tokens,
        relevant_entity_ids=relevant_entity_ids,
    ) <= 0.0:
        ranked_facts = sorted(all_facts, key=lambda fact: fact.fact_id, reverse=True)
    facts = ranked_facts[:fact_limit]

    all_threads = (
        StoryThread.query.filter_by(campaign_id=campaign_id)
        .order_by(StoryThread.updated_at.desc(), StoryThread.thread_id.desc())
        .limit(thread_candidate_limit)
        .all()
    )
    ranked_threads = sorted(
        all_threads,
        key=lambda thread: (
            _thread_retrieval_score(thread, signal_text=signal_text, signal_tokens=signal_tokens),
            thread.updated_at or thread.created_at,
            thread.thread_id,
        ),
        reverse=True,
    )
    threads = ranked_threads[:thread_limit]

    payload = {
        'entities': [
            {
                'entity_id': entity.entity_id,
                'entity_type': entity.entity_type,
                'name': entity.name,
                'canonical_name': entity.canonical_name,
                'aliases': safe_json_loads(entity.aliases_json, []),
                'summary': entity.summary,
                'status': entity.status,
            }
            for entity in entities
        ],
        'facts': [
            {
                'fact_id': fact.fact_id,
                'subject': fact.subject_entity.name if fact.subject_entity else None,
                'predicate': fact.predicate,
                'object': fact.object_entity.name if fact.object_entity else None,
                'value_text': fact.value_text,
                'confidence': fact.confidence,
            }
            for fact in facts
        ],
        'threads': [
            {
                'thread_id': thread.thread_id,
                'title': thread.title,
                'summary': thread.summary,
                'status': thread.status,
                'priority': thread.priority,
                'source': thread.source,
            }
            for thread in threads
        ],
    }

    if session_id:
        state = SessionState.query.filter_by(session_id=session_id).first()
        payload['projection'] = {
            'current_location': state.current_location if state else None,
            'current_quest': state.current_quest if state else None,
            'rolling_summary': state.rolling_summary if state else '',
        }

    return payload

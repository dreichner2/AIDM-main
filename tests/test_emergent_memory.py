from __future__ import annotations

from sqlalchemy import event

from aidm_server.database import db
from aidm_server.emergent_memory import (
    apply_canon_patch,
    build_emergent_context,
    extract_canon_patch,
    refresh_session_projection,
    validate_canon_patch,
)
from aidm_server.models import DmTurn, Player, SessionState, StoryEntity, StoryFact, StoryThread, TurnCanonUpdate, safe_json_loads
from tests.helpers import seed_world_campaign_player_session


def _create_turn(app, ids, *, player_input: str, dm_output: str) -> DmTurn:
    turn = DmTurn(
        session_id=ids['session_id'],
        campaign_id=ids['campaign_id'],
        player_id=ids['player_id'],
        player_input=player_input,
        dm_output=dm_output,
        status='completed',
        outcome_status='resolved',
    )
    db.session.add(turn)
    db.session.commit()
    return db.session.get(DmTurn, turn.turn_id)


def test_alias_resolution_reuses_existing_entity(app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        first_turn = _create_turn(
            app,
            ids,
            player_input='I ask Captain Liora Vale for guidance.',
            dm_output='Captain Liora Vale studies the fire and nods.',
        )
        campaign = first_turn.campaign

        patch_1 = {
            'entities': [
                {
                    'entity_type': 'npc',
                    'name': 'Captain Liora Vale',
                    'aliases': ['Liora'],
                    'summary': 'A grim captain carrying ash-soaked authority.',
                }
            ]
        }
        validated_1, rejections_1 = validate_canon_patch(first_turn, campaign, patch_1)
        assert rejections_1 == []
        apply_canon_patch(first_turn, campaign, validated_1, 'test-extractor', rejections_1)
        db.session.commit()

        second_turn = _create_turn(
            app,
            ids,
            player_input='I follow Liora into the chapel.',
            dm_output='Liora motions for silence as the bells settle.',
        )

        patch_2 = {'entities': [{'entity_type': 'npc', 'name': 'Liora', 'summary': 'Referred to by shorthand.'}]}
        validated_2, rejections_2 = validate_canon_patch(second_turn, campaign, patch_2)
        assert rejections_2 == []
        apply_canon_patch(second_turn, campaign, validated_2, 'test-extractor', rejections_2)
        db.session.commit()

        entities = StoryEntity.query.filter_by(campaign_id=ids['campaign_id'], entity_type='npc').all()
        assert len(entities) == 1
        entity = entities[0]
        aliases = safe_json_loads(entity.aliases_json, [])
        assert entity.name == 'Captain Liora Vale'
        assert 'Liora' in aliases


def test_conflicting_fact_requires_explicit_change_type(app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        first_turn = _create_turn(
            app,
            ids,
            player_input='I enter the chapel.',
            dm_output='You enter the chapel in silence.',
        )
        campaign = first_turn.campaign

        accepted_patch = {
            'facts': [
                {
                    'predicate': 'current_location',
                    'value_text': 'Chapel',
                    'replace_existing': True,
                }
            ]
        }
        validated_1, rejections_1 = validate_canon_patch(first_turn, campaign, accepted_patch)
        assert rejections_1 == []
        apply_canon_patch(first_turn, campaign, validated_1, 'test-extractor', rejections_1)
        refresh_session_projection(ids['session_id'], campaign)
        db.session.commit()

        second_turn = _create_turn(
            app,
            ids,
            player_input='I am suddenly at the harbor.',
            dm_output='The story now says harbor without transition.',
        )
        conflicting_patch = {'facts': [{'predicate': 'current_location', 'value_text': 'Harbor'}]}
        validated_2, rejections_2 = validate_canon_patch(second_turn, campaign, conflicting_patch)
        assert validated_2['facts'] == []
        assert len(rejections_2) == 1

        apply_canon_patch(second_turn, campaign, validated_2, 'test-extractor', rejections_2)
        refresh_session_projection(ids['session_id'], campaign)
        db.session.commit()

        accepted_facts = StoryFact.query.filter_by(campaign_id=ids['campaign_id'], predicate='current_location', fact_status='accepted').all()
        assert len(accepted_facts) == 1
        assert accepted_facts[0].value_text == 'Chapel'

        latest_update = TurnCanonUpdate.query.order_by(TurnCanonUpdate.update_id.desc()).first()
        assert latest_update is not None
        assert latest_update.status == 'applied_with_rejections'


def test_subject_singleton_fact_replacement_only_supersedes_matching_subject(app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        first_turn = _create_turn(
            app,
            ids,
            player_input='I study both survivors.',
            dm_output='Alice and Bob both survive the first ordeal.',
        )
        campaign = first_turn.campaign

        setup_patch = {
            'entities': [
                {'entity_type': 'npc', 'name': 'Alice'},
                {'entity_type': 'npc', 'name': 'Bob'},
            ],
            'facts': [
                {'subject': 'Alice', 'predicate': 'status', 'value_text': 'alive'},
                {'subject': 'Bob', 'predicate': 'status', 'value_text': 'wounded'},
            ],
        }
        validated_setup, setup_rejections = validate_canon_patch(first_turn, campaign, setup_patch)
        assert setup_rejections == []
        apply_canon_patch(first_turn, campaign, validated_setup, 'test-extractor', setup_rejections)
        db.session.commit()

        second_turn = _create_turn(
            app,
            ids,
            player_input='I check Alice again.',
            dm_output='Alice does not rise.',
        )
        replacement_patch = {
            'facts': [
                {
                    'subject': 'Alice',
                    'predicate': 'status',
                    'value_text': 'dead',
                    'replace_existing': True,
                }
            ]
        }
        validated_replacement, replacement_rejections = validate_canon_patch(second_turn, campaign, replacement_patch)
        assert replacement_rejections == []
        apply_canon_patch(second_turn, campaign, validated_replacement, 'test-extractor', replacement_rejections)
        db.session.commit()

        alice_facts = (
            StoryFact.query.filter_by(campaign_id=ids['campaign_id'], predicate='status')
            .join(StoryEntity, StoryEntity.entity_id == StoryFact.subject_entity_id)
            .filter(StoryEntity.name == 'Alice')
            .order_by(StoryFact.fact_id.asc())
            .all()
        )
        bob_facts = (
            StoryFact.query.filter_by(campaign_id=ids['campaign_id'], predicate='status')
            .join(StoryEntity, StoryEntity.entity_id == StoryFact.subject_entity_id)
            .filter(StoryEntity.name == 'Bob')
            .order_by(StoryFact.fact_id.asc())
            .all()
        )

        assert [fact.fact_status for fact in alice_facts] == ['superseded', 'accepted']
        assert [fact.value_text for fact in alice_facts] == ['alive', 'dead']
        assert [fact.fact_status for fact in bob_facts] == ['accepted']
        assert bob_facts[0].value_text == 'wounded'
        assert alice_facts[1].supersedes_fact_id == alice_facts[0].fact_id


def test_validate_canon_patch_batches_existing_fact_lookup(app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        first_turn = _create_turn(
            app,
            ids,
            player_input='I study the witnesses.',
            dm_output='Alice is alive and the party is in the chapel.',
        )
        campaign = first_turn.campaign
        setup_patch = {
            'entities': [{'entity_type': 'npc', 'name': 'Alice'}],
            'facts': [
                {'subject': 'Alice', 'predicate': 'status', 'value_text': 'alive'},
                {'predicate': 'current_location', 'value_text': 'Chapel'},
            ],
        }
        validated_setup, setup_rejections = validate_canon_patch(first_turn, campaign, setup_patch)
        assert setup_rejections == []
        apply_canon_patch(first_turn, campaign, validated_setup, 'test-extractor', setup_rejections)
        db.session.commit()

        second_turn = _create_turn(
            app,
            ids,
            player_input='I check the witnesses again.',
            dm_output='Alice is wounded and the party reaches the harbor.',
        )
        replacement_patch = {
            'facts': [
                {'subject': 'Alice', 'predicate': 'status', 'value_text': 'wounded', 'replace_existing': True},
                {'predicate': 'current_location', 'value_text': 'Harbor', 'replace_existing': True},
            ],
        }
        story_fact_selects = []

        def count_story_fact_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = ' '.join(statement.lower().split())
            if normalized.startswith('select') and ' from story_facts' in normalized:
                story_fact_selects.append(statement)

        event.listen(db.engine, 'before_cursor_execute', count_story_fact_selects)
        try:
            validated_replacement, replacement_rejections = validate_canon_patch(
                second_turn,
                campaign,
                replacement_patch,
            )
        finally:
            event.remove(db.engine, 'before_cursor_execute', count_story_fact_selects)

        assert replacement_rejections == []
        assert len(validated_replacement['facts']) == 2
        assert len(story_fact_selects) == 1


def test_apply_canon_patch_batches_thread_title_lookup(app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        turn = _create_turn(
            app,
            ids,
            player_input='I review active threads.',
            dm_output='The bell and gate threads both move forward.',
        )
        campaign = turn.campaign
        db.session.add_all(
            [
                StoryThread(campaign_id=ids['campaign_id'], title='Bell Tower', summary='Old summary.'),
                StoryThread(campaign_id=ids['campaign_id'], title='Ash Gate', summary='Old summary.'),
            ]
        )
        db.session.commit()
        patch = {
            'threads': [
                {'title': 'Bell Tower', 'summary': 'The bell tolls again.', 'priority': 3},
                {'title': 'Ash Gate', 'summary': 'The gate opens.', 'priority': 2},
            ]
        }
        story_thread_selects = []

        def count_story_thread_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = ' '.join(statement.lower().split())
            if normalized.startswith('select') and ' from story_threads' in normalized:
                story_thread_selects.append(statement)

        event.listen(db.engine, 'before_cursor_execute', count_story_thread_selects)
        try:
            summary = apply_canon_patch(turn, campaign, patch, 'test-extractor', [])
        finally:
            event.remove(db.engine, 'before_cursor_execute', count_story_thread_selects)

        assert len(summary['threads_created_or_updated']) == 2
        assert len(story_thread_selects) == 1
        assert StoryThread.query.filter_by(campaign_id=ids['campaign_id']).count() == 2


def test_inventory_validation_rejects_abstract_or_directional_phrases(app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        turn = _create_turn(
            app,
            ids,
            player_input='I keep moving and listen carefully.',
            dm_output='You take the path deeper into the ruins as Liora gives you a warning.',
        )

        patch = {
            'inventory_changes': [
                {'action': 'acquire', 'item_name': 'path deeper into the ruins'},
                {'action': 'acquire', 'item_name': 'warning'},
                {'action': 'acquire', 'item_name': 'silver key'},
            ]
        }
        validated_patch, rejections = validate_canon_patch(turn, turn.campaign, patch)

        assert validated_patch['inventory_changes'] == [
            {'action': 'acquire', 'item_name': 'silver key', 'quantity': 1}
        ]
        assert len(rejections) == 2
        assert {rejection['item_name'] for rejection in rejections} == {
            'path deeper into ruins',
            'warning',
        }


def test_canon_patch_coerces_malformed_model_numbers(app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        turn = _create_turn(
            app,
            ids,
            player_input='I take the silver key and hurry to the chapel.',
            dm_output='You take the silver key and arrive at the chapel.',
        )

        patch = {
            'facts': [
                {
                    'predicate': 'current_location',
                    'value_text': 'Chapel',
                    'confidence': 'certain',
                }
            ],
            'threads': [
                {
                    'title': 'Find the Chapel',
                    'summary': 'The party has reached the chapel.',
                    'priority': 'urgent',
                }
            ],
            'inventory_changes': [
                {
                    'action': 'acquire',
                    'item_name': 'silver key',
                    'quantity': 'two',
                }
            ],
        }

        validated_patch, rejections = validate_canon_patch(turn, turn.campaign, patch)
        assert rejections == []
        assert validated_patch['inventory_changes'] == [
            {'action': 'acquire', 'item_name': 'silver key', 'quantity': 1}
        ]

        apply_canon_patch(turn, turn.campaign, validated_patch, 'test-extractor', rejections)
        db.session.commit()

        fact = StoryFact.query.filter_by(campaign_id=ids['campaign_id'], predicate='current_location').one()
        thread = StoryThread.query.filter_by(campaign_id=ids['campaign_id'], title='Find the Chapel').one()
        player = db.session.get(Player, ids['player_id'])

        assert fact.confidence is None
        assert thread.priority == 1
        assert safe_json_loads(player.inventory, []) == [{'name': 'silver key', 'quantity': 1}]


def test_extract_canon_patch_ignores_movement_and_warning_phrases(app, monkeypatch):
    ids = seed_world_campaign_player_session(app)
    monkeypatch.setattr('aidm_server.emergent_memory._extract_with_provider', lambda *args, **kwargs: (None, None))

    with app.app_context():
        turn = _create_turn(
            app,
            ids,
            player_input='I keep moving deeper into the ruins.',
            dm_output='You take the path deeper into the ruins as Liora gives you a warning.',
        )

        patch, extractor_model = extract_canon_patch(
            turn=turn,
            campaign=turn.campaign,
            dm_output=turn.dm_output,
            speaking_player_name='Seraphina',
            triggered_segments=[],
        )

        assert extractor_model in {'heuristic-v1', 'provider', 'fallback'}
        assert patch['inventory_changes'] == []


def test_refresh_session_projection_resets_current_quest_when_open_threads_are_resolved(app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        turn = _create_turn(
            app,
            ids,
            player_input='I uncover an old vow.',
            dm_output='A new vow hangs over the party.',
        )
        campaign = turn.campaign

        patch = {
            'threads': [
                {
                    'title': 'Open Hook',
                    'summary': 'An unresolved vow.',
                    'status': 'open',
                }
            ]
        }
        validated_patch, rejections = validate_canon_patch(turn, campaign, patch)
        assert rejections == []
        apply_canon_patch(turn, campaign, validated_patch, 'test-extractor', rejections)
        refresh_session_projection(ids['session_id'], campaign)
        db.session.commit()

        state = SessionState.query.filter_by(session_id=ids['session_id']).first()
        assert state is not None
        assert state.current_quest == 'Open Hook'

        resolve_turn = _create_turn(
            app,
            ids,
            player_input='I fulfill the vow.',
            dm_output='The vow is fulfilled.',
        )
        resolve_patch = {
            'threads': [
                {
                    'title': 'Open Hook',
                    'status': 'resolved',
                }
            ]
        }
        validated_resolve, resolve_rejections = validate_canon_patch(resolve_turn, campaign, resolve_patch)
        assert resolve_rejections == []
        apply_canon_patch(resolve_turn, campaign, validated_resolve, 'test-extractor', resolve_rejections)
        refresh_session_projection(ids['session_id'], campaign)
        db.session.commit()

        db.session.refresh(state)
        assert state.current_quest == campaign.current_quest


def test_extract_canon_patch_does_not_reuse_shared_patch_state(app, monkeypatch):
    ids = seed_world_campaign_player_session(app)
    monkeypatch.setattr('aidm_server.emergent_memory._extract_with_provider', lambda *args, **kwargs: (None, None))

    with app.app_context():
        first_turn = _create_turn(
            app,
            ids,
            player_input='I grab the silver key.',
            dm_output='You take the silver key from the altar.',
        )
        first_patch, _ = extract_canon_patch(
            turn=first_turn,
            campaign=first_turn.campaign,
            dm_output=first_turn.dm_output,
            speaking_player_name='Seraphina',
            triggered_segments=[],
        )
        assert first_patch['inventory_changes'] == [
            {'action': 'acquire', 'item_name': 'silver key', 'quantity': 1}
        ]

        second_turn = _create_turn(
            app,
            ids,
            player_input='I keep moving deeper into the ruins.',
            dm_output='You take the path deeper into the ruins as Liora gives you a warning.',
        )
        second_patch, _ = extract_canon_patch(
            turn=second_turn,
            campaign=second_turn.campaign,
            dm_output=second_turn.dm_output,
            speaking_player_name='Seraphina',
            triggered_segments=[],
        )
        assert second_patch['inventory_changes'] == []


def test_inventory_loss_and_quantity_merging_are_deterministic(app, monkeypatch):
    ids = seed_world_campaign_player_session(app)
    monkeypatch.setattr('aidm_server.emergent_memory._extract_with_provider', lambda *args, **kwargs: (None, None))

    with app.app_context():
        player = db.session.get(Player, ids['player_id'])
        player.inventory = '[{"name":"silver key","quantity":1},{"name":"torch","quantity":1}]'
        db.session.commit()

        turn = _create_turn(
            app,
            ids,
            player_input='I gather what I can and spend the torch.',
            dm_output='You take a silver key. You pick up a silver key. You spend the torch.',
        )

        patch, extractor_model = extract_canon_patch(
            turn=turn,
            campaign=turn.campaign,
            dm_output=turn.dm_output,
            speaking_player_name='Seraphina',
            triggered_segments=[],
        )

        assert extractor_model in {'heuristic-v1', 'provider', 'fallback'}
        assert patch['inventory_changes'] == [
            {'action': 'acquire', 'item_name': 'silver key', 'quantity': 2},
            {'action': 'lose', 'item_name': 'torch', 'quantity': 1},
        ]

        validated_patch, rejections = validate_canon_patch(turn, turn.campaign, patch)
        assert rejections == []

        apply_canon_patch(turn, turn.campaign, validated_patch, 'test-extractor', rejections)
        db.session.commit()
        db.session.refresh(player)

        assert safe_json_loads(player.inventory, []) == [{'name': 'silver key', 'quantity': 3}]


def test_build_emergent_context_prioritizes_relevant_older_canon(app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        first_turn = _create_turn(
            app,
            ids,
            player_input='I first meet Captain Liora Vale in the bell tower.',
            dm_output='Captain Liora Vale warns you about the ash bells.',
        )
        campaign = first_turn.campaign
        early_patch = {
            'entities': [
                {
                    'entity_type': 'npc',
                    'name': 'Captain Liora Vale',
                    'aliases': ['Liora'],
                    'summary': 'Captain of the soot watch and keeper of the bell tower.',
                }
            ],
            'facts': [
                {
                    'subject': 'Captain Liora Vale',
                    'predicate': 'role',
                    'value_text': 'keeper of the bell tower',
                }
            ],
        }
        validated_early, early_rejections = validate_canon_patch(first_turn, campaign, early_patch)
        assert early_rejections == []
        apply_canon_patch(first_turn, campaign, validated_early, 'test-extractor', early_rejections)

        for idx in range(6):
            noise_turn = _create_turn(
                app,
                ids,
                player_input=f'I encounter wanderer {idx}.',
                dm_output=f'Wanderer {idx} trades rumors in the market square.',
            )
            noise_patch = {
                'entities': [{'entity_type': 'npc', 'name': f'Wanderer {idx}', 'summary': 'A recent but irrelevant extra.'}],
                'threads': [{'title': f'Recent Noise {idx}', 'summary': 'A low-signal side beat.', 'status': 'open', 'priority': 1}],
            }
            validated_noise, noise_rejections = validate_canon_patch(noise_turn, campaign, noise_patch)
            assert noise_rejections == []
            apply_canon_patch(noise_turn, campaign, validated_noise, 'test-extractor', noise_rejections)

        db.session.commit()

        context = build_emergent_context(
            campaign_id=ids['campaign_id'],
            session_id=ids['session_id'],
            query_text='I ask Liora about the bell tower.',
            current_location='Market Square',
            current_quest='Find the relic',
            recent_turns=[{'player_input': 'I ask Liora about the bell tower.', 'dm_output': ''}],
            entity_limit=4,
            fact_limit=4,
            thread_limit=4,
        )

    entity_names = {entity['name'] for entity in context['entities']}
    fact_subjects = {fact['subject'] for fact in context['facts']}
    assert 'Captain Liora Vale' in entity_names
    assert 'Captain Liora Vale' in fact_subjects


def test_build_emergent_context_caps_candidate_pools(app, monkeypatch):
    ids = seed_world_campaign_player_session(app)
    import aidm_server.emergent_memory as emergent_memory

    monkeypatch.setattr(emergent_memory, 'EMERGENT_ENTITY_CANDIDATE_LIMIT', 3)
    monkeypatch.setattr(emergent_memory, 'EMERGENT_FACT_CANDIDATE_LIMIT', 3)
    monkeypatch.setattr(emergent_memory, 'EMERGENT_THREAD_CANDIDATE_LIMIT', 3)

    with app.app_context():
        turn = _create_turn(
            app,
            ids,
            player_input='I scan the archive.',
            dm_output='The archive is full of names.',
        )
        entities = [
            StoryEntity(
                campaign_id=ids['campaign_id'],
                session_id=ids['session_id'],
                entity_type='npc',
                name=f'Archivist {index}',
                canonical_name=f'archivist-{index}',
                summary='Candidate cap test.',
                last_seen_turn_id=turn.turn_id,
            )
            for index in range(8)
        ]
        db.session.add_all(entities)
        db.session.flush()
        facts = [
            StoryFact(
                campaign_id=ids['campaign_id'],
                subject_entity_id=entities[index].entity_id,
                predicate='role',
                value_text=f'Role {index}',
                fact_status='accepted',
            )
            for index in range(8)
        ]
        threads = [
            StoryThread(
                campaign_id=ids['campaign_id'],
                title=f'Archive Thread {index}',
                summary='Candidate cap test.',
                status='open',
            )
            for index in range(8)
        ]
        db.session.add_all(facts + threads)
        db.session.commit()

        context = build_emergent_context(
            campaign_id=ids['campaign_id'],
            entity_limit=8,
            fact_limit=8,
            thread_limit=8,
        )

    assert len(context['entities']) == 3
    assert len(context['facts']) == 3
    assert len(context['threads']) == 3

    with app.app_context():
        capped_context = build_emergent_context(
            campaign_id=ids['campaign_id'],
            entity_limit=2,
            fact_limit=2,
            thread_limit=2,
        )

    assert len(capped_context['entities']) == 2
    assert len(capped_context['facts']) == 2
    assert len(capped_context['threads']) == 2

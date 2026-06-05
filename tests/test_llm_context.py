from __future__ import annotations

import json

from aidm_server.database import db
from aidm_server.llm import build_dm_context
from aidm_server.models import Campaign, Player, PlayerAction, Session, SessionState, World, safe_json_dumps


def test_build_dm_context_collects_recent_actions_for_multiple_players(app):
    with app.app_context():
        world = World(name='Context World', description='world')
        db.session.add(world)
        db.session.flush()

        campaign = Campaign(title='Context Campaign', world_id=world.world_id)
        db.session.add(campaign)
        db.session.flush()

        player_one = Player(campaign_id=campaign.campaign_id, name='Alice', character_name='Alice')
        player_two = Player(campaign_id=campaign.campaign_id, name='Borin', character_name='Borin')
        db.session.add_all([player_one, player_two])
        db.session.flush()

        session = Session(campaign_id=campaign.campaign_id)
        db.session.add(session)
        db.session.flush()

        db.session.add_all(
            [
                PlayerAction(player_id=player_one.player_id, session_id=session.session_id, action_text='scout'),
                PlayerAction(player_id=player_one.player_id, session_id=session.session_id, action_text='hide'),
                PlayerAction(player_id=player_one.player_id, session_id=session.session_id, action_text='strike'),
                PlayerAction(player_id=player_one.player_id, session_id=session.session_id, action_text='retreat'),
                PlayerAction(player_id=player_two.player_id, session_id=session.session_id, action_text='chant'),
                PlayerAction(player_id=player_two.player_id, session_id=session.session_id, action_text='guard'),
            ]
        )
        db.session.commit()

        payload = json.loads(build_dm_context(world.world_id, campaign.campaign_id, session.session_id))

    players = {entry['character_name']: entry for entry in payload['active_players']}
    assert players['Alice']['recent_actions'] == ['hide', 'strike', 'retreat']
    assert players['Borin']['recent_actions'] == ['chant', 'guard']


def test_build_dm_context_truncates_large_session_payloads(app):
    with app.app_context():
        world = World(name='Compact World', description='world')
        db.session.add(world)
        db.session.flush()

        campaign = Campaign(title='Compact Campaign', world_id=world.world_id)
        db.session.add(campaign)
        db.session.flush()

        player = Player(campaign_id=campaign.campaign_id, name='Alice', character_name='Alice')
        db.session.add(player)
        db.session.flush()

        session = Session(campaign_id=campaign.campaign_id)
        db.session.add(session)
        db.session.flush()

        state = SessionState(
            session_id=session.session_id,
            rolling_summary='R' * 6000,
            current_location='Long Hall',
            current_quest='Find the relic',
            active_segments=safe_json_dumps([], []),
            memory_snippets=safe_json_dumps(
                [
                    {
                        'turn_id': 1,
                        'player_input': 'P' * 500,
                        'dm_output': 'D' * 800,
                    }
                ]
                * 10,
                [],
            ),
        )
        db.session.add(state)

        db.session.add(
            PlayerAction(
                player_id=player.player_id,
                session_id=session.session_id,
                action_text='search',
            )
        )
        db.session.commit()

        payload = json.loads(build_dm_context(world.world_id, campaign.campaign_id, session.session_id))

    assert len(payload['session_state']['rolling_summary']) <= 4000
    assert len(payload['session_state']['memory_snippets']) == 8
    assert len(payload['session_state']['memory_snippets'][0]['player_input']) <= 180
    assert len(payload['session_state']['memory_snippets'][0]['dm_output']) <= 260

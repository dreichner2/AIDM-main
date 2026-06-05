from __future__ import annotations

from aidm_server.database import db
from aidm_server.models import Campaign, CampaignSegment, Player, Session, World


def seed_world_campaign_player_session(app):
    with app.app_context():
        world = World(name='Test World', description='A realm for tests')
        db.session.add(world)
        db.session.flush()

        campaign = Campaign(
            title='Test Campaign',
            description='Campaign for tests',
            world_id=world.world_id,
            current_quest='Find the relic',
            location='Old Ruins',
        )
        db.session.add(campaign)
        db.session.flush()

        player = Player(
            campaign_id=campaign.campaign_id,
            name='Alice',
            character_name='Seraphina',
            race='Elf',
            class_='Ranger',
            level=3,
        )
        db.session.add(player)
        db.session.flush()

        session = Session(campaign_id=campaign.campaign_id)
        db.session.add(session)
        db.session.commit()

        return {
            'world_id': world.world_id,
            'campaign_id': campaign.campaign_id,
            'player_id': player.player_id,
            'session_id': session.session_id,
        }


def seed_segment(app, campaign_id: int, trigger_condition: str):
    with app.app_context():
        segment = CampaignSegment(
            campaign_id=campaign_id,
            title='Hidden Chamber Unlocked',
            description='The chamber awakens.',
            trigger_condition=trigger_condition,
            tags='chamber,secret',
            is_triggered=False,
        )
        db.session.add(segment)
        db.session.commit()
        return segment.segment_id

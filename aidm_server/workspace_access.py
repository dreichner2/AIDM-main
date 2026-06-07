"""Helpers for auth-token scoped campaign workspaces."""

from __future__ import annotations

from flask import g, has_request_context

from aidm_server.auth import DEFAULT_WORKSPACE_ID
from aidm_server.database import db
from aidm_server.models import Campaign, CampaignSegment, Map, Player, Session, World


def current_workspace_id() -> str:
    if not has_request_context():
        return DEFAULT_WORKSPACE_ID
    return str(getattr(g, 'aidm_workspace_id', None) or DEFAULT_WORKSPACE_ID)


def campaign_query():
    return Campaign.query.filter_by(workspace_id=current_workspace_id())


def world_query():
    return World.query.filter_by(workspace_id=current_workspace_id())


def campaign_is_visible(campaign: Campaign | None, workspace_id: str | None = None) -> bool:
    if not campaign:
        return False
    return (campaign.workspace_id or DEFAULT_WORKSPACE_ID) == (workspace_id or current_workspace_id())


def world_is_visible(world: World | None, workspace_id: str | None = None) -> bool:
    if not world:
        return False
    return (world.workspace_id or DEFAULT_WORKSPACE_ID) == (workspace_id or current_workspace_id())


def get_world(world_id: int, workspace_id: str | None = None) -> World | None:
    return World.query.filter_by(
        world_id=world_id,
        workspace_id=workspace_id or current_workspace_id(),
    ).first()


def get_campaign(campaign_id: int, workspace_id: str | None = None) -> Campaign | None:
    return Campaign.query.filter_by(
        campaign_id=campaign_id,
        workspace_id=workspace_id or current_workspace_id(),
    ).first()


def get_session(session_id: int, workspace_id: str | None = None) -> Session | None:
    session_obj = db.session.get(Session, session_id)
    if not session_obj or not campaign_is_visible(session_obj.campaign, workspace_id):
        return None
    return session_obj


def get_player(player_id: int, workspace_id: str | None = None) -> Player | None:
    player = db.session.get(Player, player_id)
    if not player:
        return None
    target_workspace_id = workspace_id or current_workspace_id()
    if player.workspace_id:
        return player if player.workspace_id == target_workspace_id else None
    if not campaign_is_visible(player.campaign, target_workspace_id):
        return None
    return player


def get_campaign_map(map_id: int, workspace_id: str | None = None) -> Map | None:
    map_obj = db.session.get(Map, map_id)
    if not map_obj:
        return None
    if map_obj.campaign_id is None:
        return map_obj if world_is_visible(map_obj.world, workspace_id) else None
    return map_obj if campaign_is_visible(map_obj.campaign, workspace_id) else None


def get_segment(segment_id: int, workspace_id: str | None = None) -> CampaignSegment | None:
    segment = db.session.get(CampaignSegment, segment_id)
    if not segment or not campaign_is_visible(segment.campaign, workspace_id):
        return None
    return segment

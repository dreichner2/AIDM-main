from __future__ import annotations

from aidm_server.database import db
from aidm_server.models import DmTurn, Player, PlayerAction, TurnEvent


def delete_player_record(player: Player) -> dict:
    player_id = player.player_id
    campaign_id = player.campaign_id
    PlayerAction.query.filter_by(player_id=player_id).delete(synchronize_session=False)
    DmTurn.query.filter_by(player_id=player_id).update(
        {DmTurn.player_id: None},
        synchronize_session=False,
    )
    TurnEvent.query.filter_by(player_id=player_id).update(
        {TurnEvent.player_id: None},
        synchronize_session=False,
    )
    db.session.delete(player)
    return {'deleted': True, 'player_id': player_id, 'campaign_id': campaign_id}

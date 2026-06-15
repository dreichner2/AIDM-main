from __future__ import annotations

import json
from typing import Any

from aidm_server.database import db
from aidm_server.models import OperatorActionAudit
from aidm_server.time_utils import utc_now
from aidm_server.workspace_access import current_account_id, current_account_is_workspace_admin, current_workspace_id


def _actor_label() -> str:
    account_id = current_account_id()
    if account_id is None:
        return 'local_operator'
    role = 'admin' if current_account_is_workspace_admin() else 'player'
    return f'account:{account_id}:{role}'


def _actor_role(actor: str) -> str:
    if actor == 'local_operator':
        return 'local_operator'
    parts = actor.split(':')
    if len(parts) >= 3 and parts[0] == 'account':
        return parts[-1] or 'account'
    return actor.split(':', 1)[0] or 'unknown'


def _actor_account_id(actor: str) -> int | None:
    parts = actor.split(':')
    if len(parts) < 3 or parts[0] != 'account':
        return None
    try:
        return int(parts[1])
    except (TypeError, ValueError):
        return None


def _json_details(details: dict[str, Any] | None) -> str:
    try:
        return json.dumps(details or {}, default=str)
    except (TypeError, ValueError):
        return '{}'


def record_operator_action(
    *,
    action: str,
    resource_type: str,
    workspace_id: str | None = None,
    campaign_id: int | None = None,
    session_id: int | None = None,
    resource_id: str | int | None = None,
    status: str = 'success',
    details: dict[str, Any] | None = None,
) -> OperatorActionAudit:
    actor = _actor_label()
    audit = OperatorActionAudit(
        workspace_id=(workspace_id or current_workspace_id() or 'owner')[:80],
        campaign_id=campaign_id,
        session_id=session_id,
        action=action[:120],
        resource_type=resource_type[:80],
        resource_id=(str(resource_id)[:160] if resource_id not in (None, '') else None),
        actor=actor[:160],
        actor_account_id=_actor_account_id(actor),
        actor_role=_actor_role(actor)[:32],
        status=(status or 'success')[:32],
        details_json=_json_details(details),
        created_at=utc_now(),
    )
    db.session.add(audit)
    return audit

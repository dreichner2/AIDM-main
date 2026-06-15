from __future__ import annotations

from typing import Literal

from aidm_server.errors import error_response
from aidm_server.workspace_access import current_account_id, current_account_is_workspace_admin


Capability = Literal[
    'player_read',
    'player_action',
    'dm_authoring',
    'dm_runtime_control',
    'debug_read',
    'admin_workspace',
    'local_operator_only',
    'server_internal',
]

CAPABILITY_DESCRIPTIONS: dict[Capability, str] = {
    'player_read': 'Read player-visible game state.',
    'player_action': 'Submit normal player actions.',
    'dm_authoring': 'Create or save DM-authored campaign content.',
    'dm_runtime_control': 'Directly control mutable runtime session state.',
    'debug_read': 'Read operator/debug state.',
    'admin_workspace': 'Manage workspace-level resources.',
    'local_operator_only': 'Use local unauthenticated operator tooling.',
    'server_internal': 'Call server-internal hooks only.',
}

PLAYER_CAPABILITIES: set[Capability] = {'player_read', 'player_action'}
WORKSPACE_ADMIN_CAPABILITIES: set[Capability] = {
    *PLAYER_CAPABILITIES,
    'dm_authoring',
    'dm_runtime_control',
    'debug_read',
    'admin_workspace',
}
LOCAL_OPERATOR_CAPABILITIES: set[Capability] = {*WORKSPACE_ADMIN_CAPABILITIES, 'local_operator_only'}


def current_actor_capabilities() -> set[Capability]:
    """Return request-scoped capabilities without treating unauthenticated local mode as a player."""
    if current_account_id() is None:
        return set(LOCAL_OPERATOR_CAPABILITIES)
    if current_account_is_workspace_admin():
        return set(WORKSPACE_ADMIN_CAPABILITIES)
    return set(PLAYER_CAPABILITIES)


def current_actor_has_capability(capability: Capability) -> bool:
    if capability == 'server_internal':
        return False
    return capability in current_actor_capabilities()


def capability_forbidden_response(capability: Capability, message: str | None = None):
    if current_actor_has_capability(capability):
        return None
    return error_response(
        'forbidden',
        message or f'Missing required capability: {capability}.',
        403,
        {'required_capability': capability},
    )

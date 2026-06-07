"""Authentication helpers for API and Socket.IO requests."""

from __future__ import annotations

import re

from flask import current_app, request


DEFAULT_WORKSPACE_ID = "owner"
_WORKSPACE_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")


def normalize_workspace_id(value: str | None) -> str:
    workspace_id = _WORKSPACE_ID_RE.sub("_", str(value or "").strip()).strip("_")
    return (workspace_id or DEFAULT_WORKSPACE_ID)[:80]


def _configured_token_workspaces() -> dict[str, str]:
    raw_mapping = current_app.config.get("AIDM_API_AUTH_TOKEN_WORKSPACES", {})
    if not isinstance(raw_mapping, dict):
        return {}
    return {
        str(token).strip(): normalize_workspace_id(str(workspace_id))
        for token, workspace_id in raw_mapping.items()
        if str(token).strip()
    }


def _configured_tokens() -> set[str]:
    tokens = current_app.config.get("AIDM_API_AUTH_TOKENS", [])
    configured = {token.strip() for token in tokens if isinstance(token, str) and token.strip()}
    configured.update(_configured_token_workspaces().keys())
    return configured


def auth_required() -> bool:
    return bool(current_app.config.get("AIDM_AUTH_REQUIRED", False))


def extract_bearer_token(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    header = auth_header.strip()
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    return token or None


def is_token_authorized(token: str | None) -> bool:
    if not auth_required():
        return True
    if not token:
        return False
    valid_tokens = _configured_tokens()
    if not valid_tokens:
        return False
    return token in valid_tokens


def workspace_id_for_token(token: str | None) -> str | None:
    if not auth_required():
        return DEFAULT_WORKSPACE_ID
    if not is_token_authorized(token):
        return None
    return _configured_token_workspaces().get(str(token or "").strip(), DEFAULT_WORKSPACE_ID)


def request_auth_token() -> str | None:
    return extract_bearer_token(request.headers.get("Authorization"))


def request_workspace_id() -> str | None:
    return workspace_id_for_token(request_auth_token())


def request_is_authorized() -> bool:
    return is_token_authorized(request_auth_token())


def extract_socket_token(auth_payload: dict | None = None, data_payload: dict | None = None) -> str | None:
    del data_payload
    if isinstance(auth_payload, dict):
        token = auth_payload.get("token") or auth_payload.get("auth_token")
        if token:
            return str(token)

    header_token = extract_bearer_token(request.headers.get("Authorization"))
    return header_token

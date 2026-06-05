"""Authentication helpers for API and Socket.IO requests."""

from __future__ import annotations

from flask import current_app, request


def _configured_tokens() -> set[str]:
    tokens = current_app.config.get("AIDM_API_AUTH_TOKENS", [])
    return {token.strip() for token in tokens if isinstance(token, str) and token.strip()}


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


def request_is_authorized() -> bool:
    token = extract_bearer_token(request.headers.get("Authorization"))
    return is_token_authorized(token)


def extract_socket_token(auth_payload: dict | None = None, data_payload: dict | None = None) -> str | None:
    del data_payload
    if isinstance(auth_payload, dict):
        token = auth_payload.get("token") or auth_payload.get("auth_token")
        if token:
            return str(token)

    header_token = extract_bearer_token(request.headers.get("Authorization"))
    return header_token

"""Shared error helpers for HTTP and Socket.IO responses."""

from __future__ import annotations

from flask import jsonify


def build_error(code: str, message: str, details: dict | None = None) -> dict:
    payload = {
        "error": message,
        "error_code": code,
        "details": details or {},
    }
    return payload


def error_response(code: str, message: str, status: int = 400, details: dict | None = None):
    return jsonify(build_error(code=code, message=message, details=details)), status


def socket_error(code: str, message: str, details: dict | None = None) -> dict:
    return build_error(code=code, message=message, details=details)

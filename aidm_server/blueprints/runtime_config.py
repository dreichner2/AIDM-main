from __future__ import annotations

from flask import Blueprint, jsonify, request

from aidm_server.errors import error_response
from aidm_server.services.runtime_config import (
    RuntimeConfigError,
    apply_llm_runtime,
    llm_config_payload,
    llm_config_persistence_allowed,
    provider_configured,
    validate_provider_model,
)
from aidm_server.telemetry import telemetry_metric
from aidm_server.validation import coerce_bool, parse_json_body

runtime_config_bp = Blueprint('runtime_config', __name__)


@runtime_config_bp.route('/llm/config', methods=['GET'])
def llm_config():
    telemetry_metric('runtime_config.llm_config.requests_total', 1)
    return jsonify(llm_config_payload())


@runtime_config_bp.route('/llm/config', methods=['PATCH', 'POST'])
def update_llm_config():
    telemetry_metric('runtime_config.llm_config_updates.requests_total', 1)
    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    persist = coerce_bool(payload.get('persist'), True)
    if persist is None:
        return error_response('validation_error', 'persist must be a boolean value.', 400)
    if persist and not llm_config_persistence_allowed():
        return error_response(
            'llm_config_persist_disabled',
            'Persisting LLM config from the API is disabled outside local/test environments.',
            403,
        )

    try:
        provider, model = validate_provider_model(payload.get('provider'), payload.get('model'))
    except RuntimeConfigError as exc:
        return error_response(exc.error_code, exc.message, exc.status_code, exc.details)

    if not provider_configured(provider):
        return error_response(
            'provider_not_configured',
            f'Provider "{provider}" is missing its API key.',
            400,
        )

    apply_llm_runtime(provider, model, persist=persist)
    response = llm_config_payload()
    response['persisted'] = persist
    return jsonify(response)

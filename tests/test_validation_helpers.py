from __future__ import annotations

from flask import Flask, request

from aidm_server.validation import parse_json_body, parse_optional_json_body


def _parse_payload(parser=parse_json_body, *, json=None, data=None, content_type: str | None = None):
    app = Flask(__name__)
    with app.test_request_context('/probe', method='POST', json=json, data=data, content_type=content_type):
        return parser(request)


def test_parse_json_body_returns_object_payload():
    assert _parse_payload(json={'name': 'The Cinder March'}) == {'name': 'The Cinder March'}


def test_parse_json_body_rejects_absent_malformed_and_non_object_payloads():
    assert _parse_payload(data='not-json', content_type='text/plain') is None
    assert _parse_payload(data='{', content_type='application/json') is None
    assert _parse_payload(data='null', content_type='application/json') is None
    assert _parse_payload(json=['not', 'an', 'object']) is None
    assert _parse_payload(data='"not an object"', content_type='application/json') is None


def test_parse_optional_json_body_accepts_omitted_body_as_empty_object():
    assert _parse_payload(parse_optional_json_body) == {}
    assert _parse_payload(parse_optional_json_body, data='not-json', content_type='text/plain') == {}
    assert _parse_payload(parse_optional_json_body, json={'session_name': 'The Watch'}) == {'session_name': 'The Watch'}


def test_parse_optional_json_body_rejects_malformed_and_non_object_json():
    assert _parse_payload(parse_optional_json_body, data='{', content_type='application/json') is None
    assert _parse_payload(parse_optional_json_body, data='null', content_type='application/json') is None
    assert _parse_payload(parse_optional_json_body, json=['not', 'an', 'object']) is None
    assert _parse_payload(parse_optional_json_body, data='"not an object"', content_type='application/json') is None

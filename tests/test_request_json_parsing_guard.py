from __future__ import annotations

from scripts.check_request_json_parsing import find_violations, main


def test_find_violations_allows_shared_validation_helper(tmp_path):
    server = tmp_path / 'aidm_server'
    server.mkdir()
    validation = server / 'validation.py'
    validation.write_text(
        "def parse(request):\n    return request.get_json(silent=True)\n",
        encoding='utf-8',
    )
    routes = server / 'routes.py'
    routes.write_text('def ok():\n    return {}\n', encoding='utf-8')

    violations = find_violations(server, allowed_paths=(validation,))

    assert violations == []


def test_find_violations_reports_route_level_silent_json_parsing(tmp_path):
    server = tmp_path / 'aidm_server'
    server.mkdir()
    validation = server / 'validation.py'
    validation.write_text('def parse(request):\n    return request.get_json(silent=True)\n', encoding='utf-8')
    route = server / 'blueprint.py'
    route.write_text(
        "def unsafe(request):\n    payload = request.get_json(silent=True) if request.is_json else {}\n",
        encoding='utf-8',
    )

    violations = find_violations(server, allowed_paths=(validation,))

    assert len(violations) == 1
    assert violations[0].path == route
    assert violations[0].line_number == 2


def test_find_violations_reports_multiline_silent_json_parsing(tmp_path):
    server = tmp_path / 'aidm_server'
    server.mkdir()
    validation = server / 'validation.py'
    validation.write_text('def parse(request):\n    return request.get_json(silent=True)\n', encoding='utf-8')
    route = server / 'blueprint.py'
    route.write_text(
        "def unsafe(request):\n"
        "    payload = request.get_json(\n"
        "        silent=True,\n"
        "    )\n"
        "    return payload\n",
        encoding='utf-8',
    )

    violations = find_violations(server, allowed_paths=(validation,))

    assert len(violations) == 1
    assert violations[0].path == route
    assert violations[0].line_number == 2


def test_find_violations_reports_positional_silent_json_parsing(tmp_path):
    server = tmp_path / 'aidm_server'
    server.mkdir()
    validation = server / 'validation.py'
    validation.write_text('def parse(request):\n    return request.get_json(silent=True)\n', encoding='utf-8')
    route = server / 'blueprint.py'
    route.write_text(
        "def unsafe(request):\n"
        "    return request.get_json(False, True)\n",
        encoding='utf-8',
    )

    violations = find_violations(server, allowed_paths=(validation,))

    assert len(violations) == 1
    assert violations[0].path == route
    assert violations[0].line_number == 2


def test_find_violations_reports_syntax_errors_without_traceback(tmp_path):
    server = tmp_path / 'aidm_server'
    server.mkdir()
    validation = server / 'validation.py'
    validation.write_text('def parse(request):\n    return request.get_json(silent=True)\n', encoding='utf-8')
    route = server / 'broken_route.py'
    route.write_text('def broken(:\n    return {}\n', encoding='utf-8')

    violations = find_violations(server, allowed_paths=(validation,))

    assert len(violations) == 1
    assert violations[0].path == route
    assert violations[0].line_number == 1
    assert '<syntax error:' in violations[0].line


def test_main_returns_nonzero_when_violation_exists(tmp_path, capsys):
    server = tmp_path / 'aidm_server'
    server.mkdir()
    route = server / 'route.py'
    route.write_text('def unsafe(request):\n    return request.get_json(silent=True)\n', encoding='utf-8')

    exit_code = main(['--scan-root', str(server)])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert 'Direct get_json(silent=True) usage found' in output
    assert 'parse_optional_json_body' in output

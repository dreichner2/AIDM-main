from __future__ import annotations

from scripts import check_observability_bundle


def test_static_observability_bundle_validates_required_files_and_metrics():
    warnings = check_observability_bundle.validate_static_bundle()

    assert warnings == []


def test_docker_compose_check_warns_when_docker_is_optional(monkeypatch):
    monkeypatch.setattr(check_observability_bundle.shutil, 'which', lambda _name: None)

    warnings = check_observability_bundle.validate_docker_compose_config(require_docker=False)

    assert warnings == ['Docker is not installed; skipped `docker compose config`.']


def test_docker_compose_check_fails_when_docker_is_required(monkeypatch):
    monkeypatch.setattr(check_observability_bundle.shutil, 'which', lambda _name: None)

    try:
        check_observability_bundle.validate_docker_compose_config(require_docker=True)
    except check_observability_bundle.ObservabilityBundleError as exc:
        assert 'Docker is not installed' in str(exc)
    else:  # pragma: no cover - defensive assertion path
        raise AssertionError('expected ObservabilityBundleError')

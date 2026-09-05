from __future__ import annotations

import json

import pytest

from src.providers.thetadata_control import (
    configured_theta_base_url,
    probe_theta_terminal,
    wait_for_theta_terminal,
)


def test_theta_probe_ready_on_200_json():
    health = probe_theta_terminal(
        base_url="http://127.0.0.1:25503/v3",
        transport=lambda url, timeout: (
            200,
            json.dumps(["2026-09-04"]).encode(),
        ),
    )

    assert health.ready is True
    assert health.state == "READY"
    assert health.http_status == 200
    assert health.contract_json_valid is True


def test_theta_probe_distinguishes_unreachable():
    def fail(url, timeout):
        raise ConnectionError("refused")

    health = probe_theta_terminal(
        base_url="http://127.0.0.1:25503/v3",
        transport=fail,
    )

    assert health.ready is False
    assert health.state == "UNREACHABLE"


def test_theta_probe_rejects_non_json_200():
    health = probe_theta_terminal(
        base_url="http://127.0.0.1:25503/v3",
        transport=lambda url, timeout: (200, b"not-json"),
    )

    assert health.ready is False
    assert health.state == "CONTRACT_ERROR"


def test_theta_base_url_is_local_only(monkeypatch):
    monkeypatch.setenv(
        "CHRISTIANIA_THETA_BASE_URL",
        "https://example.com/v3",
    )

    with pytest.raises(ValueError, match="local HTTP v3 endpoint"):
        configured_theta_base_url()


def test_wait_probe_can_transition_to_ready():
    responses = [ConnectionError("booting"), (200, b"[]")]

    def transport(url, timeout):
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    clock_values = iter([0.0, 0.0, 0.1, 0.1])
    health = wait_for_theta_terminal(
        wait_seconds=1.0,
        poll_seconds=0.1,
        transport=transport,
        sleep=lambda _seconds: None,
        monotonic=lambda: next(clock_values),
    )

    assert health.ready is True


def test_theta_base_url_rejects_userinfo_host_confusion(monkeypatch):
    monkeypatch.setenv(
        "CHRISTIANIA_THETA_BASE_URL",
        "http://127.0.0.1:25503@evil.example/v3",
    )

    with pytest.raises(ValueError, match="local HTTP v3 endpoint"):
        configured_theta_base_url()


def test_theta_base_url_requires_v3_path(monkeypatch):
    monkeypatch.setenv(
        "CHRISTIANIA_THETA_BASE_URL",
        "http://127.0.0.1:25503/v2",
    )

    with pytest.raises(ValueError, match="local HTTP v3 endpoint"):
        configured_theta_base_url()


def test_theta_probe_reports_config_error_instead_of_crashing(monkeypatch):
    monkeypatch.setenv(
        "CHRISTIANIA_THETA_BASE_URL",
        "https://remote.example/v3",
    )

    health = probe_theta_terminal()

    assert health.ready is False
    assert health.state == "CONFIG_ERROR"
    assert health.http_status is None


def test_theta_probe_rejects_json_error_object_on_http_200():
    health = probe_theta_terminal(
        base_url="http://127.0.0.1:25503/v3",
        transport=lambda url, timeout: (
            200,
            b'{"error":"not ready"}',
        ),
    )

    assert health.state == "CONTRACT_ERROR"
    assert health.ready is False

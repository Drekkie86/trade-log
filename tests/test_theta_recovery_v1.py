from __future__ import annotations

import subprocess

import pytest

from src.operations import theta_recovery


class Health:
    def __init__(self, ready: bool):
        self.ready = ready
        self.state = "READY" if ready else "HTTP_ERROR"
        self.detail = self.state

    def as_dict(self):
        return {
            "ready": self.ready,
            "state": self.state,
            "detail": self.detail,
        }


def _completed():
    return subprocess.CompletedProcess(
        args=["systemctl"],
        returncode=0,
        stdout="",
        stderr="",
    )


def test_recovery_restarts_dependency_then_daemon(tmp_path, monkeypatch):
    calls = []

    def systemctl(*args, check=True):
        calls.append(args)
        return _completed()

    monkeypatch.setattr(
        theta_recovery,
        "reset_watchdog_state",
        lambda **kwargs: calls.append(("reset-watchdog",)),
    )

    result = theta_recovery.recover_theta(
        reason="test",
        audit_dir=tmp_path,
        systemctl=systemctl,
        active=lambda unit: True,
        wait_ready=lambda **kwargs: Health(True),
    )

    assert result.state == "RECOVERED"
    assert ("stop", theta_recovery.DAEMON_UNIT) in calls
    assert ("restart", theta_recovery.THETA_UNIT) in calls
    assert ("start", theta_recovery.DAEMON_UNIT) in calls
    assert calls.index(("restart", theta_recovery.THETA_UNIT)) < calls.index(
        ("start", theta_recovery.DAEMON_UNIT)
    )


def test_recovery_preserves_intentionally_stopped_daemon(
    tmp_path,
    monkeypatch,
):
    calls = []

    def systemctl(*args, check=True):
        calls.append(args)
        return _completed()

    monkeypatch.setattr(
        theta_recovery,
        "reset_watchdog_state",
        lambda **kwargs: calls.append(("reset-watchdog",)),
    )

    result = theta_recovery.recover_theta(
        reason="maintenance-test",
        audit_dir=tmp_path,
        systemctl=systemctl,
        active=lambda unit: False,
        wait_ready=lambda **kwargs: Health(True),
    )

    assert result.state == "RECOVERED"
    assert result.daemon_was_active is False
    assert result.daemon_started is False
    assert ("stop", theta_recovery.DAEMON_UNIT) not in calls
    assert ("restart", theta_recovery.THETA_UNIT) in calls
    assert ("start", theta_recovery.DAEMON_UNIT) not in calls


def test_recovery_leaves_daemon_stopped_when_theta_stays_bad(
    tmp_path,
    monkeypatch,
):
    calls = []

    def systemctl(*args, check=True):
        calls.append(args)
        return _completed()

    with pytest.raises(RuntimeError, match="did not recover"):
        theta_recovery.recover_theta(
            reason="test-failure",
            audit_dir=tmp_path,
            systemctl=systemctl,
            active=lambda unit: True,
            wait_ready=lambda **kwargs: Health(False),
        )

    assert ("stop", theta_recovery.DAEMON_UNIT) in calls
    assert ("restart", theta_recovery.THETA_UNIT) in calls
    assert ("start", theta_recovery.DAEMON_UNIT) not in calls

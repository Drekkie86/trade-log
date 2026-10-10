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
        if args == ("is-failed", theta_recovery.DAEMON_UNIT):
            return subprocess.CompletedProcess(
                args=["systemctl", *args],
                returncode=1,
                stdout="inactive\n",
                stderr="",
            )
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


def test_recovery_revives_daemon_failed_by_theta_outage(
    tmp_path,
    monkeypatch,
):
    calls = []

    def systemctl(*args, check=True):
        calls.append(args)
        if args == ("is-failed", theta_recovery.DAEMON_UNIT):
            return subprocess.CompletedProcess(
                args=["systemctl", *args],
                returncode=0,
                stdout="failed\n",
                stderr="",
            )
        return _completed()

    monkeypatch.setattr(
        theta_recovery,
        "reset_watchdog_state",
        lambda **kwargs: calls.append(("reset-watchdog",)),
    )

    result = theta_recovery.recover_theta(
        reason="watchdog-threshold",
        audit_dir=tmp_path,
        systemctl=systemctl,
        active=lambda unit: False,
        wait_ready=lambda **kwargs: Health(True),
    )

    assert result.state == "RECOVERED"
    assert result.daemon_was_active is False
    assert result.daemon_was_failed is True
    assert result.daemon_started is True
    assert ("stop", theta_recovery.DAEMON_UNIT) not in calls
    assert ("reset-failed", theta_recovery.DAEMON_UNIT) in calls
    assert ("start", theta_recovery.DAEMON_UNIT) in calls
    assert calls.index(
        ("reset-failed", theta_recovery.DAEMON_UNIT)
    ) < calls.index(
        ("start", theta_recovery.DAEMON_UNIT)
    )


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


def test_failed_theta_recovery_persists_restart_obligation(tmp_path, monkeypatch):
    calls = []

    def systemctl(*args, check=True):
        calls.append(args)
        return _completed()

    monkeypatch.setattr(
        theta_recovery, "reset_watchdog_state",
        lambda **kwargs: calls.append(("reset-watchdog",)),
    )
    with pytest.raises(RuntimeError, match="did not recover"):
        theta_recovery.recover_theta(
            reason="outage",
            audit_dir=tmp_path,
            systemctl=systemctl,
            active=lambda unit: True,
            wait_ready=lambda **kwargs: Health(False),
        )
    assert theta_recovery.restart_intent_pending(tmp_path)
    assert ("stop", theta_recovery.DAEMON_UNIT) in calls
    assert ("start", theta_recovery.DAEMON_UNIT) not in calls


def test_next_successful_theta_recovery_restores_previous_daemon(tmp_path, monkeypatch):
    calls = []

    def systemctl(*args, check=True):
        calls.append(args)
        if args == ("is-failed", theta_recovery.DAEMON_UNIT):
            return subprocess.CompletedProcess(
                args=["systemctl", *args], returncode=1,
                stdout="inactive\n", stderr="",
            )
        return _completed()

    monkeypatch.setattr(
        theta_recovery, "reset_watchdog_state",
        lambda **kwargs: calls.append(("reset-watchdog",)),
    )
    with pytest.raises(RuntimeError, match="did not recover"):
        theta_recovery.recover_theta(
            reason="watchdog-threshold",
            audit_dir=tmp_path,
            systemctl=systemctl,
            active=lambda unit: True,
            wait_ready=lambda **kwargs: Health(False),
        )

    calls.clear()
    result = theta_recovery.recover_theta(
        reason="watchdog-threshold-retry",
        audit_dir=tmp_path,
        systemctl=systemctl,
        active=lambda unit: False,
        wait_ready=lambda **kwargs: Health(True),
    )
    assert result.daemon_was_active is False
    assert result.daemon_was_failed is False
    assert result.daemon_started is True
    assert ("stop", theta_recovery.DAEMON_UNIT) not in calls
    assert ("restart", theta_recovery.THETA_UNIT) in calls
    assert ("start", theta_recovery.DAEMON_UNIT) in calls
    assert not theta_recovery.restart_intent_pending(tmp_path)


def test_failed_daemon_start_keeps_restart_obligation(tmp_path, monkeypatch):
    calls = []
    fail_start = [True]

    def systemctl(*args, check=True):
        calls.append(args)
        if args == ("is-failed", theta_recovery.DAEMON_UNIT):
            return subprocess.CompletedProcess(
                args=["systemctl", *args], returncode=1,
                stdout="inactive\n", stderr="",
            )
        if args == ("start", theta_recovery.DAEMON_UNIT) and fail_start[0]:
            raise RuntimeError("daemon start refused")
        return _completed()

    monkeypatch.setattr(
        theta_recovery, "reset_watchdog_state",
        lambda **kwargs: calls.append(("reset-watchdog",)),
    )
    with pytest.raises(RuntimeError, match="daemon start refused"):
        theta_recovery.recover_theta(
            reason="watchdog-threshold",
            audit_dir=tmp_path, systemctl=systemctl,
            active=lambda unit: True, wait_ready=lambda **kwargs: Health(True),
        )
    assert theta_recovery.restart_intent_pending(tmp_path)
    fail_start[0] = False
    result = theta_recovery.recover_theta(
        reason="watchdog-retry", audit_dir=tmp_path,
        systemctl=systemctl, active=lambda unit: False,
        wait_ready=lambda **kwargs: Health(True),
    )
    assert result.daemon_started is True
    assert not theta_recovery.restart_intent_pending(tmp_path)


def test_restart_intent_write_failure_cannot_stop_daemon(tmp_path, monkeypatch):
    calls = []

    def systemctl(*args, check=True):
        calls.append(args)
        return _completed()

    def refuse(**kwargs):
        raise OSError("restart intent disk unavailable")

    monkeypatch.setattr(theta_recovery, "remember_daemon_restart", refuse)
    with pytest.raises(OSError, match="restart intent disk unavailable"):
        theta_recovery.recover_theta(
            reason="test", audit_dir=tmp_path, systemctl=systemctl,
            active=lambda unit: True, wait_ready=lambda **kwargs: Health(True),
        )
    assert ("stop", theta_recovery.DAEMON_UNIT) not in calls

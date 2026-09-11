from __future__ import annotations

from datetime import UTC, datetime
import json

from src.operations import theta_watchdog


class Health:
    def __init__(self, ready: bool, state: str):
        self.ready = ready
        self.state = state
        self.detail = state

    def as_dict(self):
        return {
            "ready": self.ready,
            "state": self.state,
            "detail": self.detail,
        }


def test_watchdog_requires_two_consecutive_failures(tmp_path):
    first = theta_watchdog.evaluate_theta_watchdog(
        probe=lambda: Health(False, "HTTP_ERROR"),
        audit_dir=tmp_path,
        failure_threshold=2,
        now=datetime(2026, 9, 11, 19, 0, tzinfo=UTC),
    )
    assert first.state == "DEGRADED"
    assert first.recovery_required is False

    second = theta_watchdog.evaluate_theta_watchdog(
        probe=lambda: Health(False, "HTTP_ERROR"),
        audit_dir=tmp_path,
        failure_threshold=2,
        now=datetime(2026, 9, 11, 19, 1, tzinfo=UTC),
    )
    assert second.state == "RECOVERY_REQUIRED"
    assert second.recovery_required is True


def test_watchdog_success_resets_failure_counter(tmp_path):
    theta_watchdog.evaluate_theta_watchdog(
        probe=lambda: Health(False, "HTTP_ERROR"),
        audit_dir=tmp_path,
        failure_threshold=2,
    )
    result = theta_watchdog.evaluate_theta_watchdog(
        probe=lambda: Health(True, "READY"),
        audit_dir=tmp_path,
        failure_threshold=2,
    )
    assert result.state == "READY"
    assert result.consecutive_failures == 0

    payload = json.loads(
        (tmp_path / theta_watchdog.STATE_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["consecutive_failures"] == 0

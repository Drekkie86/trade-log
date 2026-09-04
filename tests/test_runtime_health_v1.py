from datetime import UTC, datetime, timedelta

from src.operations.runtime_health import (
    assess_daemon_health,
)


def test_daemon_health_is_healthy_for_recent_heartbeat():
    now = datetime(
        2026, 9, 5, 0, 0,
        tzinfo=UTC,
    )

    health = assess_daemon_health(
        {
            "heartbeat_at": (
                now - timedelta(seconds=45)
            ).isoformat().replace(
                "+00:00", "Z"
            )
        },
        now=now,
    )

    assert health.state == "HEALTHY"
    assert health.heartbeat_age_seconds == 45


def test_daemon_health_flags_stale_lease():
    now = datetime(
        2026, 9, 5, 0, 0,
        tzinfo=UTC,
    )

    health = assess_daemon_health(
        {
            "heartbeat_at": (
                now - timedelta(minutes=5)
            ).isoformat().replace(
                "+00:00", "Z"
            )
        },
        now=now,
    )

    assert health.state == "STALE_DAEMON_LEASE"


def test_daemon_health_flags_missing_lease():
    health = assess_daemon_health(None)

    assert health.state == "NO_DAEMON_LEASE"

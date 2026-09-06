from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from src.operations import rc0_supervisor


def test_atomic_status_model_healthy_property():
    snapshot = rc0_supervisor.SupervisorSnapshot(
        observed_at="2026-09-06T12:00:00Z",
        state="HEALTHY",
        checks=(),
        schema_version=27,
        daemon_state="HEALTHY",
        theta_state="READY",
        backup_file_count=1,
        latest_backup_metadata_age_hours=1.0,
        disk_free_bytes=100,
        disk_free_fraction=0.5,
    )
    assert snapshot.healthy is True
    assert snapshot.as_dict()["healthy"] is True


def test_check_fail_is_not_passed():
    check = rc0_supervisor.SupervisorCheck(
        "x", "FAIL", "bad"
    )
    assert check.passed is False


def test_persist_alert_only_on_state_transition(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(
        rc0_supervisor,
        "get_runtime_setting",
        lambda name: (
            "https://example.invalid/hook"
            if name == "CHRISTIANIA_ALERT_WEBHOOK_URL"
            else None
        ),
    )
    monkeypatch.setattr(
        rc0_supervisor,
        "_post_alert",
        lambda url, payload, timeout_seconds: sent.append((url, payload)),
    )

    snapshot = rc0_supervisor.SupervisorSnapshot(
        observed_at="2026-09-06T12:00:00Z",
        state="UNHEALTHY",
        checks=(
            rc0_supervisor.SupervisorCheck(
                "daemon", "FAIL", "stale"
            ),
        ),
        schema_version=27,
        daemon_state="STALE_DAEMON_LEASE",
        theta_state="READY",
        backup_file_count=1,
        latest_backup_metadata_age_hours=1.0,
        disk_free_bytes=100,
        disk_free_fraction=0.5,
    )

    first = rc0_supervisor.persist_and_alert(
        snapshot,
        audit_dir=tmp_path,
    )
    second = rc0_supervisor.persist_and_alert(
        snapshot,
        audit_dir=tmp_path,
    )

    assert first["transition"] is True
    assert first["alert_state"] == "SENT"
    assert second["transition"] is False
    assert len(sent) == 1


def test_disk_policy_requires_absolute_and_fractional_headroom(
    monkeypatch,
):
    monkeypatch.setattr(
        rc0_supervisor,
        "load_command_deck",
        lambda **kwargs: {
            "ready": True,
            "database": {
                "schema_version": 27,
                "journal_mode": "wal",
            },
            "daemon_health": {
                "state": "HEALTHY",
                "heartbeat_age_seconds": 1,
            },
            "theta_health": {
                "state": "READY",
                "ready": True,
                "latency_ms": 1,
            },
        },
    )
    monkeypatch.setattr(
        rc0_supervisor,
        "inventory_backups_fast",
        lambda: SimpleNamespace(
            as_dict=lambda: {
                "total_files": 1,
                "entries": [{"age_hours": 1.0}],
            }
        ),
    )
    monkeypatch.setattr(
        rc0_supervisor,
        "resolve_db_path",
        lambda: __import__("pathlib").Path("/tmp/test.db"),
    )
    monkeypatch.setattr(
        rc0_supervisor,
        "get_runtime_setting",
        lambda name: None,
    )

    snapshot = rc0_supervisor.collect_snapshot(
        now=datetime(2026, 9, 6, 12, tzinfo=UTC),
        service_state=lambda unit: "active",
        timer_state=lambda unit: "enabled",
        disk_usage=lambda path: SimpleNamespace(
            total=100 * 1024**3,
            free=10 * 1024**3,
        ),
    )

    assert snapshot.state == "UNHEALTHY"
    assert any(
        c.name == "disk-headroom" and c.state == "FAIL"
        for c in snapshot.checks
    )

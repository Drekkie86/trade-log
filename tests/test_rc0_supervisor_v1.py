from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from src.operations import rc0_supervisor


def _healthy_deck():
    return {
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
    }


def _healthy_memory(unit: str) -> dict[str, str]:
    policy = rc0_supervisor.MEMORY_POLICY_BYTES[unit]
    return {
        "MemoryCurrent": str(policy["warning"] // 2),
        "MemoryPeak": str(policy["warning"] // 2),
        "NRestarts": "0",
        "MemoryHigh": str(policy["high"]),
        "MemoryMax": str(policy["max"]),
    }


def _prepare_collect_snapshot(monkeypatch):
    monkeypatch.setattr(
        rc0_supervisor,
        "load_command_deck",
        lambda **kwargs: _healthy_deck(),
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
        lambda: Path("/tmp/test.db"),
    )
    monkeypatch.setattr(
        rc0_supervisor,
        "get_runtime_setting",
        lambda name: None,
    )


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
    assert snapshot.as_dict()["service_memory"] == {}


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
    _prepare_collect_snapshot(monkeypatch)

    snapshot = rc0_supervisor.collect_snapshot(
        now=datetime(2026, 9, 6, 12, tzinfo=UTC),
        service_state=lambda unit: "active",
        timer_state=lambda unit: "enabled",
        service_properties=_healthy_memory,
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


def test_memory_warning_and_policy_drift_are_blocking(monkeypatch):
    _prepare_collect_snapshot(monkeypatch)

    def memory(unit: str) -> dict[str, str]:
        values = _healthy_memory(unit)
        if unit == "christiania-theta.service":
            values["MemoryCurrent"] = str(
                rc0_supervisor.MEMORY_POLICY_BYTES[unit]["warning"]
            )
        if unit == "christiania-app.service":
            values["MemoryHigh"] = str(
                rc0_supervisor.MEMORY_POLICY_BYTES[unit]["high"] + 1
            )
        return values

    snapshot = rc0_supervisor.collect_snapshot(
        now=datetime(2026, 9, 6, 12, tzinfo=UTC),
        service_state=lambda unit: "active",
        timer_state=lambda unit: "enabled",
        service_properties=memory,
        disk_usage=lambda path: SimpleNamespace(
            total=100 * 1024**3,
            free=50 * 1024**3,
        ),
    )

    assert snapshot.state == "UNHEALTHY"
    failed = {
        c.name: c.detail
        for c in snapshot.checks
        if c.state == "FAIL"
    }
    assert "memory:christiania-theta.service" in failed
    assert "reached warning" in failed["memory:christiania-theta.service"]
    assert "memory:christiania-app.service" in failed
    assert "expected=" in failed["memory:christiania-app.service"]


def test_missing_or_malformed_memory_values_fail_closed(monkeypatch):
    _prepare_collect_snapshot(monkeypatch)

    def memory(unit: str) -> dict[str, str]:
        values = _healthy_memory(unit)
        if unit == "christiania-daemon.service":
            values["MemoryCurrent"] = "not-a-number"
            values["MemoryMax"] = "infinity"
        return values

    snapshot = rc0_supervisor.collect_snapshot(
        now=datetime(2026, 9, 6, 12, tzinfo=UTC),
        service_state=lambda unit: "active",
        timer_state=lambda unit: "enabled",
        service_properties=memory,
        disk_usage=lambda path: SimpleNamespace(
            total=100 * 1024**3,
            free=50 * 1024**3,
        ),
    )

    assert snapshot.state == "UNHEALTHY"
    check = next(
        c for c in snapshot.checks
        if c.name == "memory:christiania-daemon.service"
    )
    assert check.state == "FAIL"
    assert "MemoryCurrent unavailable or malformed" in check.detail
    assert "MemoryMax=None" in check.detail


def test_memory_peak_and_restarts_are_telemetry_not_blockers(monkeypatch):
    _prepare_collect_snapshot(monkeypatch)

    def memory(unit: str) -> dict[str, str]:
        values = _healthy_memory(unit)
        values["MemoryPeak"] = str(
            rc0_supervisor.MEMORY_POLICY_BYTES[unit]["max"] + 1000
        )
        values["NRestarts"] = "7"
        return values

    snapshot = rc0_supervisor.collect_snapshot(
        now=datetime(2026, 9, 6, 12, tzinfo=UTC),
        service_state=lambda unit: "active",
        timer_state=lambda unit: "enabled",
        service_properties=memory,
        disk_usage=lambda path: SimpleNamespace(
            total=100 * 1024**3,
            free=50 * 1024**3,
        ),
    )

    assert snapshot.state == "HEALTHY"
    theta = snapshot.service_memory["christiania-theta.service"]
    assert theta["nrestarts"] == 7
    assert theta["peak_bytes"] > theta["expected_memory_max_bytes"]

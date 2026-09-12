from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from src.operations import rc0_supervisor
from src.operations.service_resources import (
    SERVICE_RESOURCE_POLICIES,
    service_resource_policy,
)


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


def _healthy_properties(
    unit: str,
) -> dict[str, str]:
    policy = service_resource_policy(
        unit
    )

    return {
        "MemoryCurrent": str(
            policy.memory_warning_bytes
            // 2
        ),
        "MemoryPeak": str(
            policy.memory_warning_bytes
            // 2
        ),
        "NRestarts": "0",
        "MemoryHigh": str(
            policy.memory_high_bytes
        ),
        "MemoryMax": str(
            policy.memory_max_bytes
        ),
        "TimeoutStartUSec": str(
            policy.timeout_start_seconds
            * 1_000_000
        ),
        "TimeoutStopUSec": str(
            policy.timeout_stop_seconds
            * 1_000_000
        ),
        "OOMPolicy": (
            policy.oom_policy
        ),
    }


def _expected_timer_state(
    unit: str,
) -> str:
    if (
        unit
        in rc0_supervisor.INTENTIONALLY_DISABLED_TIMERS
    ):
        return "disabled"

    return "enabled"


def _prepare_collect_snapshot(
    monkeypatch,
):
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
                "entries": [
                    {
                        "age_hours": 1.0,
                    }
                ],
            }
        ),
    )

    monkeypatch.setattr(
        rc0_supervisor,
        "resolve_db_path",
        lambda: Path(
            "/tmp/test.db"
        ),
    )

    monkeypatch.setattr(
        rc0_supervisor,
        "get_runtime_setting",
        lambda name: None,
    )

    monkeypatch.setattr(
        rc0_supervisor,
        "_research_progress_check",
        lambda db_path, observed: (
            rc0_supervisor.SupervisorCheck(
                "research-progress",
                "PASS",
                (
                    "test research "
                    "production healthy"
                ),
            )
        ),
    )


def _healthy_snapshot(
    monkeypatch,
):
    _prepare_collect_snapshot(
        monkeypatch
    )

    return rc0_supervisor.collect_snapshot(
        now=datetime(
            2026,
            9,
            6,
            12,
            tzinfo=UTC,
        ),
        service_state=lambda unit: (
            "active"
        ),
        timer_state=(
            _expected_timer_state
        ),
        service_properties=(
            _healthy_properties
        ),
        disk_usage=lambda path: (
            SimpleNamespace(
                total=100 * 1024**3,
                free=50 * 1024**3,
            )
        ),
    )


def test_atomic_status_model_healthy_property():
    snapshot = (
        rc0_supervisor.SupervisorSnapshot(
            observed_at=(
                "2026-09-06T12:00:00Z"
            ),
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
    )

    assert snapshot.healthy is True
    assert (
        snapshot.as_dict()[
            "healthy"
        ]
        is True
    )
    assert (
        snapshot.as_dict()[
            "service_memory"
        ]
        == {}
    )


def test_check_fail_is_not_passed():
    check = (
        rc0_supervisor.SupervisorCheck(
            "x",
            "FAIL",
            "bad",
        )
    )

    assert check.passed is False


def test_supervisor_uses_canonical_resource_policy():
    assert not hasattr(
        rc0_supervisor,
        "MEMORY_POLICY_BYTES",
    )

    assert (
        len(
            SERVICE_RESOURCE_POLICIES
        )
        == 14
    )


def test_all_14_effective_resource_policies_are_checked(
    monkeypatch,
):
    snapshot = _healthy_snapshot(
        monkeypatch
    )

    policy_checks = [
        check
        for check in snapshot.checks
        if check.name.startswith(
            "resource-policy:"
        )
    ]

    assert (
        len(
            policy_checks
        )
        == 14
    )

    assert all(
        check.state == "PASS"
        for check in policy_checks
    )


def test_runtime_memory_telemetry_is_only_for_core_services(
    monkeypatch,
):
    snapshot = _healthy_snapshot(
        monkeypatch
    )

    assert set(
        snapshot.service_memory
    ) == set(
        rc0_supervisor.CORE_SERVICES
    )


def test_intentionally_disabled_timers_are_healthy_when_disabled(
    monkeypatch,
):
    snapshot = _healthy_snapshot(
        monkeypatch
    )

    assert (
        snapshot.state
        == "HEALTHY"
    )

    checks = {
        check.name: check
        for check in snapshot.checks
    }

    for unit in (
        rc0_supervisor.INTENTIONALLY_DISABLED_TIMERS
    ):
        check = checks[
            f"timer:{unit}"
        ]

        assert (
            check.state
            == "PASS"
        )
        assert (
            "expected disabled"
            in check.detail
        )


def test_intentionally_disabled_timer_becoming_enabled_is_blocking(
    monkeypatch,
):
    _prepare_collect_snapshot(
        monkeypatch
    )

    def timer_state(
        unit: str,
    ) -> str:
        if (
            unit
            == "christiania-burn-in.timer"
        ):
            return "enabled"

        return _expected_timer_state(
            unit
        )

    snapshot = (
        rc0_supervisor.collect_snapshot(
            now=datetime(
                2026,
                9,
                6,
                12,
                tzinfo=UTC,
            ),
            service_state=(
                lambda unit: "active"
            ),
            timer_state=(
                timer_state
            ),
            service_properties=(
                _healthy_properties
            ),
            disk_usage=lambda path: (
                SimpleNamespace(
                    total=100 * 1024**3,
                    free=50 * 1024**3,
                )
            ),
        )
    )

    assert (
        snapshot.state
        == "UNHEALTHY"
    )

    check = next(
        check
        for check in snapshot.checks
        if (
            check.name
            == (
                "timer:"
                "christiania-burn-in.timer"
            )
        )
    )

    assert (
        check.state
        == "FAIL"
    )


def test_persist_alert_only_on_state_transition(
    tmp_path,
    monkeypatch,
):
    sent = []

    monkeypatch.setattr(
        rc0_supervisor,
        "get_runtime_setting",
        lambda name: (
            "https://example.invalid/hook"
            if (
                name
                == (
                    "CHRISTIANIA_"
                    "ALERT_WEBHOOK_URL"
                )
            )
            else None
        ),
    )

    monkeypatch.setattr(
        rc0_supervisor,
        "_post_alert",
        lambda url, payload, timeout_seconds: (
            sent.append(
                (
                    url,
                    payload,
                )
            )
        ),
    )

    snapshot = (
        rc0_supervisor.SupervisorSnapshot(
            observed_at=(
                "2026-09-06T12:00:00Z"
            ),
            state="UNHEALTHY",
            checks=(
                rc0_supervisor.SupervisorCheck(
                    "daemon",
                    "FAIL",
                    "stale",
                ),
            ),
            schema_version=27,
            daemon_state=(
                "STALE_DAEMON_LEASE"
            ),
            theta_state="READY",
            backup_file_count=1,
            latest_backup_metadata_age_hours=1.0,
            disk_free_bytes=100,
            disk_free_fraction=0.5,
        )
    )

    first = (
        rc0_supervisor.persist_and_alert(
            snapshot,
            audit_dir=tmp_path,
        )
    )

    second = (
        rc0_supervisor.persist_and_alert(
            snapshot,
            audit_dir=tmp_path,
        )
    )

    assert (
        first["transition"]
        is True
    )
    assert (
        first["alert_state"]
        == "SENT"
    )
    assert (
        second["transition"]
        is False
    )
    assert len(sent) == 1


def test_disk_policy_requires_absolute_and_fractional_headroom(
    monkeypatch,
):
    _prepare_collect_snapshot(
        monkeypatch
    )

    snapshot = (
        rc0_supervisor.collect_snapshot(
            now=datetime(
                2026,
                9,
                6,
                12,
                tzinfo=UTC,
            ),
            service_state=(
                lambda unit: "active"
            ),
            timer_state=(
                _expected_timer_state
            ),
            service_properties=(
                _healthy_properties
            ),
            disk_usage=lambda path: (
                SimpleNamespace(
                    total=100 * 1024**3,
                    free=10 * 1024**3,
                )
            ),
        )
    )

    assert (
        snapshot.state
        == "UNHEALTHY"
    )

    assert any(
        (
            check.name
            == "disk-headroom"
            and check.state
            == "FAIL"
        )
        for check in snapshot.checks
    )


def test_memory_warning_and_policy_drift_are_blocking(
    monkeypatch,
):
    _prepare_collect_snapshot(
        monkeypatch
    )

    def properties(
        unit: str,
    ) -> dict[str, str]:
        values = (
            _healthy_properties(
                unit
            )
        )

        policy = (
            service_resource_policy(
                unit
            )
        )

        if (
            unit
            == "christiania-theta.service"
        ):
            values[
                "MemoryCurrent"
            ] = str(
                policy.memory_warning_bytes
            )

        if (
            unit
            == "christiania-app.service"
        ):
            values[
                "MemoryHigh"
            ] = str(
                policy.memory_high_bytes
                + 1
            )

        return values

    snapshot = (
        rc0_supervisor.collect_snapshot(
            now=datetime(
                2026,
                9,
                6,
                12,
                tzinfo=UTC,
            ),
            service_state=(
                lambda unit: "active"
            ),
            timer_state=(
                _expected_timer_state
            ),
            service_properties=(
                properties
            ),
            disk_usage=lambda path: (
                SimpleNamespace(
                    total=100 * 1024**3,
                    free=50 * 1024**3,
                )
            ),
        )
    )

    assert (
        snapshot.state
        == "UNHEALTHY"
    )

    failed = {
        check.name: check.detail
        for check in snapshot.checks
        if check.state
        == "FAIL"
    }

    assert (
        "memory:"
        "christiania-theta.service"
        in failed
    )
    assert (
        "reached warning"
        in failed[
            "memory:"
            "christiania-theta.service"
        ]
    )

    assert (
        "memory:"
        "christiania-app.service"
        in failed
    )

    assert (
        "expected="
        in failed[
            "memory:"
            "christiania-app.service"
        ]
    )

    assert (
        "resource-policy:"
        "christiania-app.service"
        in failed
    )


def test_noncore_resource_policy_drift_is_blocking(
    monkeypatch,
):
    _prepare_collect_snapshot(
        monkeypatch
    )

    def properties(
        unit: str,
    ) -> dict[str, str]:
        values = (
            _healthy_properties(
                unit
            )
        )

        if (
            unit
            == "christiania-backup.service"
        ):
            values[
                "TimeoutStartUSec"
            ] = "infinity"

        return values

    snapshot = (
        rc0_supervisor.collect_snapshot(
            now=datetime(
                2026,
                9,
                6,
                12,
                tzinfo=UTC,
            ),
            service_state=(
                lambda unit: "active"
            ),
            timer_state=(
                _expected_timer_state
            ),
            service_properties=(
                properties
            ),
            disk_usage=lambda path: (
                SimpleNamespace(
                    total=100 * 1024**3,
                    free=50 * 1024**3,
                )
            ),
        )
    )

    assert (
        snapshot.state
        == "UNHEALTHY"
    )

    check = next(
        check
        for check in snapshot.checks
        if (
            check.name
            == (
                "resource-policy:"
                "christiania-backup.service"
            )
        )
    )

    assert (
        check.state
        == "FAIL"
    )

    assert (
        "TimeoutStartUSec"
        in check.detail
    )


def test_missing_or_malformed_memory_values_fail_closed(
    monkeypatch,
):
    _prepare_collect_snapshot(
        monkeypatch
    )

    def properties(
        unit: str,
    ) -> dict[str, str]:
        values = (
            _healthy_properties(
                unit
            )
        )

        if (
            unit
            == "christiania-daemon.service"
        ):
            values[
                "MemoryCurrent"
            ] = "not-a-number"
            values[
                "MemoryMax"
            ] = "infinity"

        return values

    snapshot = (
        rc0_supervisor.collect_snapshot(
            now=datetime(
                2026,
                9,
                6,
                12,
                tzinfo=UTC,
            ),
            service_state=(
                lambda unit: "active"
            ),
            timer_state=(
                _expected_timer_state
            ),
            service_properties=(
                properties
            ),
            disk_usage=lambda path: (
                SimpleNamespace(
                    total=100 * 1024**3,
                    free=50 * 1024**3,
                )
            ),
        )
    )

    assert (
        snapshot.state
        == "UNHEALTHY"
    )

    check = next(
        check
        for check in snapshot.checks
        if (
            check.name
            == (
                "memory:"
                "christiania-daemon.service"
            )
        )
    )

    assert (
        check.state
        == "FAIL"
    )

    assert (
        "MemoryCurrent unavailable "
        "or malformed"
        in check.detail
    )

    assert (
        "MemoryMax=None"
        in check.detail
    )


def test_memory_peak_and_restarts_are_telemetry_not_blockers(
    monkeypatch,
):
    _prepare_collect_snapshot(
        monkeypatch
    )

    def properties(
        unit: str,
    ) -> dict[str, str]:
        values = (
            _healthy_properties(
                unit
            )
        )

        policy = (
            service_resource_policy(
                unit
            )
        )

        values[
            "MemoryPeak"
        ] = str(
            policy.memory_max_bytes
            + 1000
        )

        values[
            "NRestarts"
        ] = "7"

        return values

    snapshot = (
        rc0_supervisor.collect_snapshot(
            now=datetime(
                2026,
                9,
                6,
                12,
                tzinfo=UTC,
            ),
            service_state=(
                lambda unit: "active"
            ),
            timer_state=(
                _expected_timer_state
            ),
            service_properties=(
                properties
            ),
            disk_usage=lambda path: (
                SimpleNamespace(
                    total=100 * 1024**3,
                    free=50 * 1024**3,
                )
            ),
        )
    )

    assert (
        snapshot.state
        == "HEALTHY"
    )

    theta = (
        snapshot.service_memory[
            "christiania-theta.service"
        ]
    )

    assert (
        theta["nrestarts"]
        == 7
    )

    assert (
        theta["peak_bytes"]
        > theta[
            "expected_memory_max_bytes"
        ]
    )


def _iteration_db(
    tmp_path: Path,
) -> Path:
    db = (
        tmp_path
        / "iterations.db"
    )

    conn = sqlite3.connect(
        db
    )

    try:
        conn.execute(
            """
            CREATE TABLE
            research_daemon_iterations (
                id INTEGER PRIMARY KEY,
                scheduled_for TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                error_type TEXT,
                error_message TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    return db


def test_research_progress_latest_failure_is_blocking(
    tmp_path,
    monkeypatch,
):
    db = _iteration_db(
        tmp_path
    )

    conn = sqlite3.connect(
        db
    )

    try:
        conn.execute(
            """
            INSERT INTO
            research_daemon_iterations (
                scheduled_for,
                started_at,
                completed_at,
                status,
                error_type,
                error_message
            )
            VALUES (
                ?,
                ?,
                ?,
                'FAILED',
                ?,
                ?
            );
            """,
            (
                "2026-09-11T18:15:00Z",
                "2026-09-11T18:15:00Z",
                "2026-09-11T18:15:01Z",
                (
                    "IndependentResearch"
                    "RunnerError"
                ),
                (
                    "Cannot determine "
                    "Git HEAD"
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        rc0_supervisor,
        "market_clock_snapshot",
        lambda now: SimpleNamespace(
            state=(
                "ACTIVE_SAMPLE_WINDOW"
            ),
            session=None,
        ),
    )

    check = (
        rc0_supervisor._research_progress_check(
            db,
            datetime(
                2026,
                9,
                11,
                18,
                20,
                tzinfo=UTC,
            ),
        )
    )

    assert (
        check.state
        == "FAIL"
    )

    assert (
        "Cannot determine Git HEAD"
        in check.detail
    )


def test_research_progress_recent_success_passes_active_window(
    tmp_path,
    monkeypatch,
):
    db = _iteration_db(
        tmp_path
    )

    conn = sqlite3.connect(
        db
    )

    try:
        conn.execute(
            """
            INSERT INTO
            research_daemon_iterations (
                scheduled_for,
                started_at,
                completed_at,
                status,
                error_type,
                error_message
            )
            VALUES (
                ?,
                ?,
                ?,
                'COMPLETED',
                NULL,
                NULL
            );
            """,
            (
                "2026-09-11T18:15:00Z",
                "2026-09-11T18:15:00Z",
                "2026-09-11T18:18:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        rc0_supervisor,
        "market_clock_snapshot",
        lambda now: SimpleNamespace(
            state=(
                "ACTIVE_SAMPLE_WINDOW"
            ),
            session=None,
        ),
    )

    check = (
        rc0_supervisor._research_progress_check(
            db,
            datetime(
                2026,
                9,
                11,
                18,
                20,
                tzinfo=UTC,
            ),
        )
    )

    assert (
        check.state
        == "PASS"
    )

    assert (
        "current"
        in check.detail.lower()
    )


def test_research_progress_stale_success_fails_active_window(
    tmp_path,
    monkeypatch,
):
    db = _iteration_db(
        tmp_path
    )

    conn = sqlite3.connect(
        db
    )

    try:
        conn.execute(
            """
            INSERT INTO
            research_daemon_iterations (
                scheduled_for,
                started_at,
                completed_at,
                status,
                error_type,
                error_message
            )
            VALUES (
                ?,
                ?,
                ?,
                'COMPLETED',
                NULL,
                NULL
            );
            """,
            (
                "2026-09-11T17:00:00Z",
                "2026-09-11T17:00:00Z",
                "2026-09-11T17:05:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        rc0_supervisor,
        "market_clock_snapshot",
        lambda now: SimpleNamespace(
            state=(
                "ACTIVE_SAMPLE_WINDOW"
            ),
            session=None,
        ),
    )

    check = (
        rc0_supervisor._research_progress_check(
            db,
            datetime(
                2026,
                9,
                11,
                18,
                20,
                tzinfo=UTC,
            ),
        )
    )

    assert (
        check.state
        == "FAIL"
    )

    assert (
        "stale"
        in check.detail.lower()
    )


def test_failed_unhealthy_alert_is_retried(
    tmp_path,
    monkeypatch,
):
    attempts = []

    def setting(
        name,
    ):
        if (
            name
            == (
                "CHRISTIANIA_"
                "ALERT_WEBHOOK_URL"
            )
        ):
            return (
                "https://example.invalid/hook"
            )

        return None

    monkeypatch.setattr(
        rc0_supervisor,
        "get_runtime_setting",
        setting,
    )

    def fail_alert(
        url,
        payload,
        timeout_seconds,
    ):
        attempts.append(
            (
                url,
                payload,
            )
        )
        raise ConnectionError(
            "test outage"
        )

    monkeypatch.setattr(
        rc0_supervisor,
        "_post_alert",
        fail_alert,
    )

    snapshot = (
        rc0_supervisor.SupervisorSnapshot(
            observed_at=(
                "2026-09-11T19:00:00Z"
            ),
            state="UNHEALTHY",
            checks=(
                rc0_supervisor.SupervisorCheck(
                    "x",
                    "FAIL",
                    "bad",
                ),
            ),
            schema_version=27,
            daemon_state="HEALTHY",
            theta_state="READY",
            backup_file_count=1,
            latest_backup_metadata_age_hours=1.0,
            disk_free_bytes=100,
            disk_free_fraction=0.5,
        )
    )

    first = (
        rc0_supervisor.persist_and_alert(
            snapshot,
            audit_dir=tmp_path,
        )
    )

    second = (
        rc0_supervisor.persist_and_alert(
            snapshot,
            audit_dir=tmp_path,
        )
    )

    assert (
        first["alert_state"]
        == "FAILED"
    )

    assert (
        second["alert_state"]
        == "FAILED"
    )

    assert (
        len(
            attempts
        )
        == 2
    )


def test_healthy_supervisor_sends_deadman_heartbeat(
    tmp_path,
    monkeypatch,
):
    pings = []

    def setting(
        name,
    ):
        if (
            name
            == (
                "CHRISTIANIA_"
                "HEARTBEAT_URL"
            )
        ):
            return (
                "https://heartbeat.invalid/ping"
            )

        return None

    monkeypatch.setattr(
        rc0_supervisor,
        "get_runtime_setting",
        setting,
    )

    monkeypatch.setattr(
        rc0_supervisor,
        "_ping_heartbeat",
        lambda url, timeout_seconds: (
            pings.append(
                url
            )
        ),
    )

    snapshot = (
        rc0_supervisor.SupervisorSnapshot(
            observed_at=(
                "2026-09-11T19:00:00Z"
            ),
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
    )

    state = (
        rc0_supervisor.persist_and_alert(
            snapshot,
            audit_dir=tmp_path,
        )
    )

    assert (
        state["heartbeat_state"]
        == "SENT"
    )

    assert pings == [
        "https://heartbeat.invalid/ping"
    ]
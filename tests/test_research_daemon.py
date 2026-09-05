from datetime import datetime
import json
from zoneinfo import ZoneInfo

import pytest

from src.database.repository import (
    get_connection,
)
from src.research.research_daemon import (
    ResearchDaemonError,
    acquire_daemon_lock,
    next_sampling_slot,
    release_daemon_lock,
)

NY = ZoneInfo("America/New_York")


def test_next_slot_inside_session():
    now = datetime(
        2026, 9, 1,
        10, 7,
        tzinfo=NY,
    )

    slot = next_sampling_slot(
        now
    )

    assert (
        slot.hour,
        slot.minute,
    ) == (
        10,
        15,
    )


def test_next_slot_before_open_is_0945():
    now = datetime(
        2026, 9, 1,
        8, 0,
        tzinfo=NY,
    )

    slot = next_sampling_slot(
        now
    )

    assert (
        slot.hour,
        slot.minute,
    ) == (
        9,
        45,
    )


def test_next_slot_after_session_skips_exchange_holiday():
    now = datetime(
        2026, 9, 4,
        16, 0,
        tzinfo=NY,
    )

    slot = next_sampling_slot(
        now
    )

    assert slot.date().isoformat() == "2026-09-08"
    assert (
        slot.hour,
        slot.minute,
    ) == (
        9,
        45,
    )


def test_daemon_lock_refuses_second_owner(
    db_path,
):
    acquire_daemon_lock(
        owner_token="owner-a",
        db_path=db_path,
    )

    try:
        with pytest.raises(
            ResearchDaemonError,
            match="active lease",
        ):
            acquire_daemon_lock(
                owner_token="owner-b",
                db_path=db_path,
            )
    finally:
        release_daemon_lock(
            owner_token="owner-a",
            db_path=db_path,
        )

    conn = get_connection(db_path)
    try:
        assert conn.execute(
            """
            SELECT COUNT(*)
            FROM research_daemon_lock;
            """
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_reconcile_orphaned_iterations_marks_only_stale_running(
    db_path,
    monkeypatch,
):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import src.research.research_daemon as daemon_module
    from src.research.research_daemon import (
        reconcile_orphaned_iterations,
    )

    UTC = ZoneInfo("UTC")
    fixed_now = datetime(
        2026, 9, 1,
        14, 0,
        tzinfo=UTC,
    )

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(
        daemon_module,
        "datetime",
        FixedDateTime,
    )

    conn = get_connection(db_path)

    try:
        conn.execute(
            """
            INSERT INTO research_daemon_iterations (
                owner_token,
                scheduled_for,
                started_at,
                status
            )
            VALUES (
                'old-owner',
                '2026-09-01T13:00:00Z',
                '2026-09-01T13:00:00Z',
                'RUNNING'
            );
            """
        )

        conn.execute(
            """
            INSERT INTO research_daemon_iterations (
                owner_token,
                scheduled_for,
                started_at,
                status
            )
            VALUES (
                'fresh-owner',
                '2026-09-01T13:50:00Z',
                '2026-09-01T13:50:00Z',
                'RUNNING'
            );
            """
        )

        conn.commit()
    finally:
        conn.close()

    changed = reconcile_orphaned_iterations(
        db_path=db_path,
    )

    assert changed == 1

    conn = get_connection(db_path)

    try:
        rows = conn.execute(
            """
            SELECT owner_token, status, error_type
            FROM research_daemon_iterations
            ORDER BY id;
            """
        ).fetchall()

        assert rows[0]["status"] == "ORPHANED"
        assert rows[0]["error_type"] == "INTERRUPTED_PROCESS"
        assert rows[1]["status"] == "RUNNING"
    finally:
        conn.close()



def test_reconcile_orphaned_research_runs_terminalizes_stale_children(
    db_path,
    monkeypatch,
):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import src.research.research_daemon as daemon_module
    from src.research.research_daemon import (
        reconcile_orphaned_research_runs,
    )

    UTC = ZoneInfo("UTC")
    fixed_now = datetime(
        2026, 9, 2,
        22, 0,
        tzinfo=UTC,
    )

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(
        daemon_module,
        "datetime",
        FixedDateTime,
    )

    conn = get_connection(db_path)
    try:
        stale = conn.execute(
            """
            INSERT INTO research_runs (
                cohort_id,
                preregistration_hash,
                code_git_sha,
                started_at,
                us_session_date,
                us_session_state,
                status,
                attempted_underlyings,
                notes
            )
            VALUES (
                'INDEPENDENT_RESEARCH_RUNNER_V1',
                'hash-stale',
                'sha-stale',
                '2026-09-02T15:00:00Z',
                '2026-09-02',
                'INTRADAY',
                'COLLECTING',
                1,
                'original note'
            );
            """
        ).lastrowid

        fresh = conn.execute(
            """
            INSERT INTO research_runs (
                cohort_id,
                preregistration_hash,
                code_git_sha,
                started_at,
                us_session_date,
                us_session_state,
                status
            )
            VALUES (
                'INDEPENDENT_RESEARCH_RUNNER_V1',
                'hash-fresh',
                'sha-fresh',
                '2026-09-02T20:00:00Z',
                '2026-09-02',
                'INTRADAY',
                'COLLECTING'
            );
            """
        ).lastrowid

        conn.execute(
            """
            INSERT INTO research_run_underlyings (
                run_id,
                underlying,
                attempted_at,
                status,
                retry_count
            )
            VALUES (?, 'AAPL', '2026-09-02T15:00:01Z', 'ATTEMPTED', 0);
            """,
            (stale,),
        )
        conn.commit()
    finally:
        conn.close()

    changed = reconcile_orphaned_research_runs(
        db_path=db_path,
    )
    assert changed == 1

    # Idempotence: terminalized runs are not touched again.
    assert reconcile_orphaned_research_runs(
        db_path=db_path,
    ) == 0

    conn = get_connection(db_path)
    try:
        stale_row = conn.execute(
            "SELECT * FROM research_runs WHERE id = ?;",
            (stale,),
        ).fetchone()
        child = conn.execute(
            """
            SELECT * FROM research_run_underlyings
            WHERE run_id = ? AND underlying = 'AAPL';
            """,
            (stale,),
        ).fetchone()
        fresh_row = conn.execute(
            "SELECT * FROM research_runs WHERE id = ?;",
            (fresh,),
        ).fetchone()

        assert stale_row["status"] == "FAILED"
        assert stale_row["ended_at"] is not None
        assert stale_row["failed_underlyings"] == 1
        assert stale_row["underlying_observation_status"] == "FAILED"
        assert "Recovered stale COLLECTING" in stale_row["notes"]

        assert child["status"] == "FAILED"
        assert child["completed_at"] is not None
        assert child["failure_code"] == "INTERRUPTED_PROCESS"

        assert fresh_row["status"] == "COLLECTING"
        assert fresh_row["ended_at"] is None
    finally:
        conn.close()


def test_next_slot_early_close_uses_1245_last_sample():
    now = datetime(
        2026, 11, 27,
        12, 44,
        tzinfo=NY,
    )

    slot = next_sampling_slot(now)

    assert slot.date().isoformat() == "2026-11-27"
    assert (slot.hour, slot.minute) == (12, 45)


def test_next_slot_after_early_close_moves_to_next_session():
    now = datetime(
        2026, 11, 27,
        12, 50,
        tzinfo=NY,
    )

    slot = next_sampling_slot(now)

    assert slot.date().isoformat() == "2026-11-30"
    assert (slot.hour, slot.minute) == (9, 45)


def test_interrupted_iteration_is_terminalized_as_orphaned(
    db_path,
):
    from src.research.research_daemon import (
        run_one_iteration,
    )

    owner = "interrupt-owner"
    acquire_daemon_lock(
        owner_token=owner,
        db_path=db_path,
    )

    def interrupting_runner(**_kwargs):
        raise KeyboardInterrupt

    try:
        with pytest.raises(KeyboardInterrupt):
            run_one_iteration(
                scheduled_for=datetime(
                    2026, 9, 1,
                    10, 0,
                    tzinfo=NY,
                ),
                owner_token=owner,
                symbols=["AAPL"],
                massive_client=object(),
                theta_client=object(),
                db_path=db_path,
                full_cycle_runner=interrupting_runner,
            )

        conn = get_connection(db_path)
        try:
            row = conn.execute(
                """
                SELECT status, error_type, completed_at
                FROM research_daemon_iterations
                ORDER BY id DESC
                LIMIT 1;
                """
            ).fetchone()

            assert row["status"] == "ORPHANED"
            assert row["error_type"] == "INTERRUPTED_PROCESS"
            assert row["completed_at"] is not None
        finally:
            conn.close()
    finally:
        release_daemon_lock(
            owner_token=owner,
            db_path=db_path,
        )


def test_run_daemon_refuses_when_theta_not_ready(db_path, monkeypatch):
    import src.research.research_daemon as module

    monkeypatch.setenv("MASSIVE_API_KEY", "x")
    monkeypatch.setattr(
        module,
        "configured_theta_client",
        lambda: type(
            "Client",
            (),
            {"base_url": "http://127.0.0.1:25503/v3"},
        )(),
    )
    monkeypatch.setattr(
        module,
        "probe_theta_terminal",
        lambda **_kwargs: type(
            "Health",
            (),
            {
                "ready": False,
                "state": "UNREACHABLE",
                "detail": "refused",
            },
        )(),
    )

    with pytest.raises(
        module.ResearchDaemonError,
        match="Theta Terminal is not ready",
    ):
        module.run_daemon(
            symbols=["AAPL"],
            max_iterations=0,
            db_path=db_path,
        )


def test_daemon_blocks_slot_when_theta_becomes_unready(
    db_path,
    monkeypatch,
):
    import src.research.research_daemon as module

    monkeypatch.setenv("MASSIVE_API_KEY", "x")

    theta_client = type(
        "Client",
        (),
        {"base_url": "http://127.0.0.1:25503/v3"},
    )()

    monkeypatch.setattr(
        module,
        "configured_theta_client",
        lambda: theta_client,
    )

    states = iter(
        [
            type(
                "Health",
                (),
                {
                    "ready": True,
                    "state": "READY",
                    "detail": "ok",
                },
            )(),
            type(
                "Health",
                (),
                {
                    "ready": False,
                    "state": "UNREACHABLE",
                    "detail": "connection refused",
                },
            )(),
        ]
    )

    monkeypatch.setattr(
        module,
        "probe_theta_terminal",
        lambda **_kwargs: next(states),
    )

    monkeypatch.setattr(
        module,
        "MassiveClient",
        lambda _key: object(),
    )

    monkeypatch.setattr(
        module,
        "next_sampling_slot",
        lambda now, interval_minutes=15: now,
    )

    monkeypatch.setattr(
        module.time,
        "sleep",
        lambda _seconds: None,
    )

    def forbidden_collection(**_kwargs):
        raise AssertionError(
            "Research collection must not start when Theta is unhealthy."
        )

    monkeypatch.setattr(
        module,
        "run_one_iteration",
        forbidden_collection,
    )

    assert module.run_daemon(
        symbols=["AAPL"],
        max_iterations=1,
        db_path=db_path,
    ) == 0

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT
                status,
                research_run_id,
                error_type,
                error_message,
                evidence_json
            FROM research_daemon_iterations
            ORDER BY id DESC
            LIMIT 1;
            """
        ).fetchone()

        assert row["status"] == "FAILED"
        assert row["research_run_id"] is None
        assert row["error_type"] == "THETA_NOT_READY"
        assert "UNREACHABLE" in row["error_message"]

        evidence = json.loads(row["evidence_json"])
        assert evidence["provider"] == "THETADATA"
        assert evidence["provider_state"] == "UNREACHABLE"
        assert evidence["collection_started"] is False
    finally:
        conn.close()

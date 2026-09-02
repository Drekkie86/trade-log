from datetime import datetime
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


def test_next_slot_after_session_moves_to_next_weekday():
    now = datetime(
        2026, 9, 4,
        16, 0,
        tzinfo=NY,
    )

    slot = next_sampling_slot(
        now
    )

    assert slot.weekday() == 0
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

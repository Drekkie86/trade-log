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

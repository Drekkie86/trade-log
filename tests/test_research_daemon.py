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

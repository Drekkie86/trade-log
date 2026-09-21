from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.backup_policy import evaluate_backup_due


NOW = datetime(2026, 9, 21, 20, 0, tzinfo=UTC)


def _seed_db(
    path: Path,
    completed_at: list[str] | None,
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE schema_version(
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO schema_version(version, applied_at)
            VALUES(?, '2026-09-01T00:00:00Z');
            """,
            (EXPECTED_SCHEMA_VERSION,),
        )
        conn.execute(
            """
            CREATE TABLE research_daemon_iterations(
                id INTEGER PRIMARY KEY,
                completed_at TEXT,
                status TEXT NOT NULL
            );
            """
        )

        for completed in completed_at or []:
            conn.execute(
                """
                INSERT INTO research_daemon_iterations(
                    completed_at,
                    status
                )
                VALUES(?, 'COMPLETED');
                """,
                (completed,),
            )

        conn.commit()
    finally:
        conn.close()


def _backup_copy(
    source: Path,
    directory: Path,
    *,
    captured_at: datetime,
    modified_at: datetime | None = None,
) -> Path:
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    stamp = captured_at.astimezone(
        UTC
    ).strftime("%Y%m%dT%H%M%SZ")

    backup = (
        directory
        / f"christiania_backup_{stamp}.db"
    )
    shutil.copy2(source, backup)

    file_time = (
        captured_at
        if modified_at is None
        else modified_at
    ).timestamp()

    os.utime(
        backup,
        (file_time, file_time),
    )
    return backup


def _iso(moment: datetime) -> str:
    return (
        moment.astimezone(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def test_no_new_research_does_not_create_weekend_backup(
    tmp_path,
):
    db = tmp_path / "trade_log.db"
    backups = tmp_path / "backups"

    _seed_db(
        db,
        ["2026-09-18T19:00:00Z"],
    )
    _backup_copy(
        db,
        backups,
        captured_at=datetime(
            2026, 9, 18, 21, 0, tzinfo=UTC
        ),
    )

    decision = evaluate_backup_due(
        db_path=db,
        backup_dir=backups,
        now=NOW,
        max_age_hours=168,
        min_new_research_iterations=25,
    )

    assert decision.due is False
    assert (
        decision.reason
        == "NO_NEW_COMPLETED_RESEARCH"
    )
    assert (
        decision.completed_research_since_backup
        == 0
    )


def test_four_new_cycles_are_below_materiality_threshold(
    tmp_path,
):
    db = tmp_path / "trade_log.db"
    backups = tmp_path / "backups"

    completed = [
        "2026-09-21T19:02:48.042Z",
        "2026-09-21T19:17:37.453Z",
        "2026-09-21T19:32:41.092Z",
        "2026-09-21T19:47:39.442Z",
    ]

    _seed_db(db, completed)

    _backup_copy(
        db,
        backups,
        captured_at=datetime(
            2026, 9, 21, 19, 1, 33, tzinfo=UTC
        ),
        modified_at=datetime(
            2026, 9, 21, 19, 2, 31, tzinfo=UTC
        ),
    )

    decision = evaluate_backup_due(
        db_path=db,
        backup_dir=backups,
        now=NOW,
        max_age_hours=168,
        min_new_research_iterations=25,
    )

    assert decision.due is False
    assert (
        decision.reason
        == "NEW_RESEARCH_BELOW_MATERIALITY_THRESHOLD"
    )
    assert (
        decision.completed_research_since_backup
        == 4
    )
    assert decision.min_new_research_iterations == 25
    assert (
        decision.latest_backup_captured_at
        == "2026-09-21T19:01:33Z"
    )


def test_one_full_sample_window_makes_backup_due(
    tmp_path,
):
    db = tmp_path / "trade_log.db"
    backups = tmp_path / "backups"

    captured = datetime(
        2026, 9, 20, 12, 0, tzinfo=UTC
    )
    completed = [
        _iso(
            captured
            + timedelta(minutes=15 * (index + 1))
        )
        for index in range(25)
    ]

    _seed_db(db, completed)
    _backup_copy(
        db,
        backups,
        captured_at=captured,
    )

    decision = evaluate_backup_due(
        db_path=db,
        backup_dir=backups,
        now=NOW,
        max_age_hours=168,
        min_new_research_iterations=25,
    )

    assert decision.due is True
    assert (
        decision.reason
        == "MATERIAL_NEW_RESEARCH_ACCUMULATED"
    )
    assert (
        decision.completed_research_since_backup
        == 25
    )


def test_old_recovery_point_without_new_research_is_not_rewritten(
    tmp_path,
):
    db = tmp_path / "trade_log.db"
    backups = tmp_path / "backups"

    captured = NOW - timedelta(hours=200)

    _seed_db(
        db,
        [_iso(captured - timedelta(hours=1))],
    )
    _backup_copy(
        db,
        backups,
        captured_at=captured,
    )

    decision = evaluate_backup_due(
        db_path=db,
        backup_dir=backups,
        now=NOW,
        max_age_hours=168,
        min_new_research_iterations=25,
    )

    assert decision.due is False
    assert (
        decision.reason
        == "NO_NEW_COMPLETED_RESEARCH"
    )


def test_max_age_protects_small_amount_of_unbacked_research(
    tmp_path,
):
    db = tmp_path / "trade_log.db"
    backups = tmp_path / "backups"

    captured = NOW - timedelta(hours=169)

    _seed_db(
        db,
        [_iso(captured + timedelta(hours=1))],
    )
    _backup_copy(
        db,
        backups,
        captured_at=captured,
    )

    decision = evaluate_backup_due(
        db_path=db,
        backup_dir=backups,
        now=NOW,
        max_age_hours=168,
        min_new_research_iterations=25,
    )

    assert decision.due is True
    assert (
        decision.reason
        == "UNPROTECTED_RESEARCH_MAX_AGE_EXCEEDED"
    )
    assert (
        decision.completed_research_since_backup
        == 1
    )


def test_filename_snapshot_start_not_finish_mtime_is_boundary(
    tmp_path,
):
    db = tmp_path / "trade_log.db"
    backups = tmp_path / "backups"

    captured = datetime(
        2026, 9, 21, 19, 1, 33, tzinfo=UTC
    )
    finished = datetime(
        2026, 9, 21, 19, 3, 0, tzinfo=UTC
    )

    _seed_db(
        db,
        ["2026-09-21T19:02:00Z"],
    )
    _backup_copy(
        db,
        backups,
        captured_at=captured,
        modified_at=finished,
    )

    decision = evaluate_backup_due(
        db_path=db,
        backup_dir=backups,
        now=NOW,
        max_age_hours=168,
        min_new_research_iterations=1,
    )

    assert decision.due is True
    assert (
        decision.completed_research_since_backup
        == 1
    )


def test_missing_recovery_point_is_due(tmp_path):
    db = tmp_path / "trade_log.db"
    _seed_db(db, [])

    decision = evaluate_backup_due(
        db_path=db,
        backup_dir=tmp_path / "missing",
        now=NOW,
        max_age_hours=168,
        min_new_research_iterations=25,
    )

    assert decision.due is True
    assert decision.reason == "NO_RECOVERY_POINT"

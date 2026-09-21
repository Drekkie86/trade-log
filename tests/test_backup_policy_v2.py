from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.backup_policy import evaluate_backup_due


NOW = datetime(2026, 9, 21, 20, 0, tzinfo=UTC)


def _seed_db(path: Path, completed_at: str | None) -> None:
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
        if completed_at is not None:
            conn.execute(
                """
                INSERT INTO research_daemon_iterations(
                    completed_at,
                    status
                )
                VALUES(?, 'COMPLETED');
                """,
                (completed_at,),
            )
        conn.commit()
    finally:
        conn.close()


def _backup_copy(
    source: Path,
    directory: Path,
    *,
    modified_at: datetime,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    backup = directory / "christiania_backup_20260918T210000Z.db"
    shutil.copy2(source, backup)
    stamp = modified_at.timestamp()
    os.utime(backup, (stamp, stamp))
    return backup


def test_no_new_research_does_not_create_weekend_backup(tmp_path):
    db = tmp_path / "trade_log.db"
    backups = tmp_path / "backups"
    _seed_db(db, "2026-09-18T19:00:00Z")
    _backup_copy(
        db,
        backups,
        modified_at=datetime(
            2026, 9, 18, 21, 0, tzinfo=UTC
        ),
    )

    decision = evaluate_backup_due(
        db_path=db,
        backup_dir=backups,
        now=NOW,
        max_age_hours=168,
    )

    assert decision.due is False
    assert decision.reason == "NO_NEW_COMPLETED_RESEARCH"


def test_new_completed_research_makes_backup_due(tmp_path):
    db = tmp_path / "trade_log.db"
    backups = tmp_path / "backups"
    _seed_db(db, "2026-09-21T19:02:00Z")
    _backup_copy(
        db,
        backups,
        modified_at=datetime(
            2026, 9, 18, 21, 0, tzinfo=UTC
        ),
    )

    decision = evaluate_backup_due(
        db_path=db,
        backup_dir=backups,
        now=NOW,
        max_age_hours=168,
    )

    assert decision.due is True
    assert (
        decision.reason
        == "NEW_COMPLETED_RESEARCH_SINCE_BACKUP"
    )


def test_hard_max_age_forces_periodic_recovery_point(tmp_path):
    db = tmp_path / "trade_log.db"
    backups = tmp_path / "backups"
    _seed_db(db, None)
    _backup_copy(
        db,
        backups,
        modified_at=NOW - timedelta(hours=169),
    )

    decision = evaluate_backup_due(
        db_path=db,
        backup_dir=backups,
        now=NOW,
        max_age_hours=168,
    )

    assert decision.due is True
    assert (
        decision.reason
        == "MAXIMUM_RECOVERY_POINT_AGE_EXCEEDED"
    )


def test_missing_recovery_point_is_due(tmp_path):
    db = tmp_path / "trade_log.db"
    _seed_db(db, None)

    decision = evaluate_backup_due(
        db_path=db,
        backup_dir=tmp_path / "missing",
        now=NOW,
        max_age_hours=168,
    )

    assert decision.due is True
    assert decision.reason == "NO_RECOVERY_POINT"

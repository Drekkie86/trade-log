from __future__ import annotations

import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from src.database.repository import DB_PATH

ROOT = Path(__file__).resolve().parent
MIG = ROOT / "migrations" / "025_recovery_provenance_visibility.sql"


def version(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()[0]
    finally:
        conn.close()


def apply(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(MIG.read_text(encoding="utf-8"))
        conn.commit()
        assert conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()[0] == 25
        assert conn.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"
        assert not conn.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(research_run_underlyings)"
            ).fetchall()
        }
        assert "recovery_error_type" in columns
        assert "recovery_error_message" in columns

        assert conn.execute(
            """
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'view'
              AND name = 'v_local_surface_v2_prospective_partition_v2'
            """
        ).fetchone()[0] == 1
    finally:
        conn.close()


def main():
    print("Christiania - real database migration to v25")
    print("---------------------------------------------")
    db = Path(DB_PATH)

    if not db.exists():
        raise SystemExit("trade_log.db not found")

    current = version(db)
    print(f"Current schema version: v{current}")
    if current != 24:
        raise SystemExit(f"Expected v24 before migration, found v{current}")

    print("Rehearsing migration on a temporary copy...")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "trade_log.db"
        shutil.copy2(db, copy)
        apply(copy)
    print("Rehearsal successful.")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / f"trade_log_before_v25_{stamp}.db"
    shutil.copy2(db, backup)
    print(f"Backup created: {backup.name}")

    apply(db)

    print("Migration successful.")
    print("Database schema: v25")
    print("SQLite integrity_check: ok")
    print("Foreign-key check: clean")
    print(
        "Recovery provenance is structured and queryable "
        "in prospective partition v2."
    )


if __name__ == "__main__":
    main()

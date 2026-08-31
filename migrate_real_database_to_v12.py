from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from migrate_real_database_to_v11 import (
    connect,
    sqlite_backup,
    stamp,
)

ROOT = Path(__file__).resolve().parent
DB = ROOT / "trade_log.db"
MIGRATION = (
    ROOT
    / "migrations"
    / "012_shadow_admission.sql"
)

EXPECTED_BEFORE = 11
EXPECTED_AFTER = 12


def version(
    conn: sqlite3.Connection,
) -> int:
    row = conn.execute(
        "SELECT MAX(version) AS version "
        "FROM schema_version;"
    ).fetchone()

    if row is None or row["version"] is None:
        raise RuntimeError(
            "schema_version contains no version."
        )

    return int(row["version"])


def verify(
    conn: sqlite3.Connection,
) -> None:
    if version(conn) != EXPECTED_AFTER:
        raise RuntimeError(
            "Database did not reach v12."
        )

    names = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master;"
        )
    }

    required = {
        "fx_observations",
        "shadow_admission_decisions",
        "trg_fx_observations_no_update",
        "trg_shadow_admission_decisions_no_update",
    }

    missing = required - names

    if missing:
        raise RuntimeError(
            f"Missing v12 objects: {sorted(missing)}"
        )

    if conn.execute(
        "PRAGMA integrity_check;"
    ).fetchone()[0] != "ok":
        raise RuntimeError(
            "integrity_check failed."
        )

    fk = conn.execute(
        "PRAGMA foreign_key_check;"
    ).fetchall()

    if fk:
        raise RuntimeError(
            f"foreign_key_check returned {len(fk)} row(s)."
        )


def main() -> int:
    print(
        "Christiania - real database migration to v12"
    )
    print(
        "-------------------------------------------"
    )
    print()

    if not DB.exists():
        print(
            f"Database not found: {DB}"
        )
        return 1

    sql = MIGRATION.read_text(
        encoding="utf-8"
    )

    conn = connect(DB)
    try:
        current = version(conn)
    finally:
        conn.close()

    print(
        f"Current schema version: v{current}"
    )

    if current == EXPECTED_AFTER:
        conn = connect(DB)
        try:
            verify(conn)
        finally:
            conn.close()

        print(
            "Database already valid v12."
        )
        return 0

    if current != EXPECTED_BEFORE:
        print(
            f"Expected v{EXPECTED_BEFORE}; "
            f"found v{current}."
        )
        return 1

    rehearsal = (
        ROOT / "trade_log_v12_rehearsal.db"
    )

    rehearsal.unlink(
        missing_ok=True
    )

    sqlite_backup(
        DB,
        rehearsal,
    )

    rehearsal_conn = connect(
        rehearsal
    )

    try:
        rehearsal_conn.executescript(
            sql
        )
        verify(
            rehearsal_conn
        )
        rehearsal_conn.commit()
    finally:
        rehearsal_conn.close()
        rehearsal.unlink(
            missing_ok=True
        )

    print(
        "Rehearsal successful."
    )

    backup = (
        ROOT
        / f"trade_log_before_v12_{stamp()}.db"
    )

    sqlite_backup(
        DB,
        backup,
    )

    print(
        f"Backup created: {backup.name}"
    )

    conn = connect(DB)

    try:
        conn.executescript(
            sql
        )
        verify(conn)
        conn.commit()
    except Exception:
        conn.close()

        sqlite_backup(
            backup,
            DB,
        )

        print(
            "Migration failed. Database restored."
        )
        raise
    else:
        conn.close()

    print(
        "Migration successful."
    )
    print(
        "Database schema: v12"
    )
    print(
        "SQLite integrity_check: ok"
    )
    print(
        "Foreign-key check: clean"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())

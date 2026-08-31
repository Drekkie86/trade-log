from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "trade_log.db"
MIGRATION_PATH = PROJECT_ROOT / "migrations" / "009_hostile_review_hardening.sql"
EXPECTED_BEFORE = 8
EXPECTED_AFTER = 9


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection



def sqlite_backup(source: Path, destination: Path) -> None:
    """
    WAL-safe SQLite backup using the SQLite backup API.
    """

    source_connection = connect(source)
    try:
        destination_connection = connect(destination)
        try:
            source_connection.backup(destination_connection)
            destination_connection.commit()
        finally:
            destination_connection.close()
    finally:
        source_connection.close()


def version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT MAX(version) AS version FROM schema_version;"
    ).fetchone()
    if row is None or row["version"] is None:
        raise RuntimeError("schema_version contains no version.")
    return int(row["version"])


def verify(connection: sqlite3.Connection) -> None:
    if version(connection) != EXPECTED_AFTER:
        raise RuntimeError("Schema did not reach v9.")

    objects = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master;"
        )
    }
    for required in {
        "unmatched_provider_contract_observations",
        "trg_shadow_state_transition_guard",
        "trg_underlying_pin_first_event",
        "v_active_underlying_pins",
    }:
        if required not in objects:
            raise RuntimeError(f"Missing v9 schema object: {required}")

    if connection.execute("PRAGMA integrity_check;").fetchone()[0] != "ok":
        raise RuntimeError("integrity_check failed.")

    fk = connection.execute("PRAGMA foreign_key_check;").fetchall()
    if fk:
        raise RuntimeError(
            f"foreign_key_check returned {len(fk)} row(s)."
        )


def rehearse(source: Path, sql: str) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        copy = Path(temp_dir) / "trade_log_rehearsal.db"
        sqlite_backup(source, copy)
        connection = connect(copy)
        try:
            if version(connection) != EXPECTED_BEFORE:
                raise RuntimeError(
                    f"Rehearsal expected v{EXPECTED_BEFORE}."
                )
            connection.executescript(sql)
            verify(connection)
        finally:
            connection.close()


def main() -> int:
    print("Christiania - real database migration to v9")
    print("------------------------------------------")
    print()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return 1

    if not MIGRATION_PATH.exists():
        print(f"Migration not found: {MIGRATION_PATH}")
        return 1

    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    connection = connect(DB_PATH)
    try:
        current = version(connection)
    finally:
        connection.close()

    print(f"Current schema version: v{current}")

    if current == EXPECTED_AFTER:
        connection = connect(DB_PATH)
        try:
            verify(connection)
        finally:
            connection.close()
        print("Database is already valid v9.")
        return 0

    if current != EXPECTED_BEFORE:
        print(
            f"Expected v{EXPECTED_BEFORE} before migration; "
            f"found v{current}."
        )
        return 1

    print("Rehearsing migration on a temporary copy...")
    rehearse(DB_PATH, sql)
    print("Rehearsal successful.")

    backup = PROJECT_ROOT / f"trade_log_before_v9_{stamp()}.db"
    sqlite_backup(DB_PATH, backup)
    print(f"Backup created: {backup.name}")

    connection = connect(DB_PATH)
    try:
        connection.executescript(sql)
        verify(connection)
        connection.commit()
    except Exception:
        connection.close()
        sqlite_backup(backup, DB_PATH)
        print("Migration failed. Original database restored from backup.")
        raise
    else:
        connection.close()

    print("Migration successful.")
    print("Database schema: v9")
    print("SQLite integrity_check: ok")
    print("Foreign-key check: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())

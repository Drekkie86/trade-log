from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "trade_log.db"
MIGRATION_PATH = (
    PROJECT_ROOT
    / "migrations"
    / "008_shadow_persistence.sql"
)
EXPECTED_BEFORE = 7
EXPECTED_AFTER = 8


def stamp() -> str:
    return datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        """
        SELECT MAX(version) AS version
        FROM schema_version;
        """
    ).fetchone()
    if row is None or row["version"] is None:
        raise RuntimeError("schema_version contains no version.")
    return int(row["version"])


def verify(connection: sqlite3.Connection) -> None:
    if version(connection) != EXPECTED_AFTER:
        raise RuntimeError("Schema did not reach v8.")

    objects = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master;"
        )
    }

    for required in {
        "listing_reference_contracts",
        "provider_observation_availability",
        "shadow_candidates",
        "shadow_state_events",
        "shadow_outcome_observations",
        "underlying_pin_events",
        "v_reference_snapshot_reconciliation",
        "v_shadow_current_state",
        "v_underlying_pin_state",
    }:
        if required not in objects:
            raise RuntimeError(
                f"Missing v8 schema object: {required}"
            )

    integrity = connection.execute(
        "PRAGMA integrity_check;"
    ).fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(
            f"integrity_check failed: {integrity}"
        )

    fk = connection.execute(
        "PRAGMA foreign_key_check;"
    ).fetchall()
    if fk:
        raise RuntimeError(
            f"foreign_key_check returned {len(fk)} row(s)."
        )


def migrate_copy(
    source: Path,
    migration_sql: str,
) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        rehearsal = Path(temp_dir) / "trade_log_rehearsal.db"
        shutil.copy2(source, rehearsal)
        connection = connect(rehearsal)
        try:
            if version(connection) != EXPECTED_BEFORE:
                raise RuntimeError(
                    f"Rehearsal expected v{EXPECTED_BEFORE}."
                )
            connection.executescript(migration_sql)
            verify(connection)
        finally:
            connection.close()


def main() -> int:
    print("Christiania - real database migration to v8")
    print("------------------------------------------")
    print()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return 1

    if not MIGRATION_PATH.exists():
        print(f"Migration not found: {MIGRATION_PATH}")
        return 1

    migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")

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
        print("Database is already valid v8.")
        return 0

    if current != EXPECTED_BEFORE:
        print(
            f"Expected v{EXPECTED_BEFORE} before migration; "
            f"found v{current}."
        )
        return 1

    print("Rehearsing migration on a temporary copy...")
    migrate_copy(DB_PATH, migration_sql)
    print("Rehearsal successful.")

    backup = PROJECT_ROOT / (
        f"trade_log_before_v8_{stamp()}.db"
    )
    shutil.copy2(DB_PATH, backup)
    print(f"Backup created: {backup.name}")

    connection = connect(DB_PATH)
    try:
        connection.executescript(migration_sql)
        verify(connection)
        connection.commit()
    except Exception:
        connection.close()
        shutil.copy2(backup, DB_PATH)
        print("Migration failed. Original database restored from backup.")
        raise
    else:
        connection.close()

    print("Migration successful.")
    print("Database schema: v8")
    print("SQLite integrity_check: ok")
    print("Foreign-key check: clean")
    print()
    print("Keep the backup until the full test suite is green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

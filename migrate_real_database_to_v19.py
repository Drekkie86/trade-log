from __future__ import annotations

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
    / "019_local_surface_residual_v2_observational.sql"
)
EXPECTED_BEFORE = 18
EXPECTED_AFTER = 19


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


def verify_index(
    connection: sqlite3.Connection,
    *,
    name: str,
    expected_columns: list[str],
) -> None:
    objects = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master;"
        )
    }

    if name not in objects:
        raise RuntimeError(
            f"Missing v16 schema object: {name}"
        )

    index_info = connection.execute(
        f"PRAGMA index_info({name});"
    ).fetchall()
    indexed_columns = [
        row["name"]
        for row in index_info
    ]

    if indexed_columns != expected_columns:
        raise RuntimeError(
            f"{name} does not cover the expected columns "
            f"in order. Found: {indexed_columns}"
        )


def verify(connection: sqlite3.Connection) -> None:
    if version(connection) != EXPECTED_AFTER:
        raise RuntimeError("Schema did not reach v19.")

    objects = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('view', 'table', 'index');"
        ).fetchall()
    }
    required = {
        "local_surface_residual_v2_runs",
        "local_surface_residual_v2_observations",
        "v_local_surface_residual_v2_discovery_dataset",
        "idx_surface_v2_run_underlying_expiry_right",
        "idx_surface_v2_quote",
    }
    missing = required - objects
    if missing:
        raise RuntimeError(f"Missing v19 schema objects: {sorted(missing)}")

    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(local_surface_residual_v2_runs);"
        ).fetchall()
    }
    for name in {"surfaced_count", "decision_enabled"}:
        if name not in columns:
            raise RuntimeError(f"Missing v19 firewall column: {name}")

    connection.execute(
        "SELECT COUNT(*) FROM v_local_surface_residual_v2_discovery_dataset;"
    ).fetchone()

    if connection.execute("PRAGMA integrity_check;").fetchone()[0] != "ok":
        raise RuntimeError("integrity_check failed.")
    fk = connection.execute("PRAGMA foreign_key_check;").fetchall()
    if fk:
        raise RuntimeError(f"foreign_key_check returned {len(fk)} row(s).")


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
    print("Christiania - real database migration to v19")
    print("---------------------------------------------")
    print()
    print(
        "This migration adds observational LOCAL_SURFACE_RESIDUAL_V2 "
        "persistence and its discovery-dataset view. V2 cannot surface, "
        "create candidates, or affect admission."
    )
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
        print("Database is already valid v19.")
        return 0
    if current != EXPECTED_BEFORE:
        print(f"Expected v{EXPECTED_BEFORE} before migration; found v{current}.")
        return 1

    print("Rehearsing migration on a temporary copy...")
    rehearse(DB_PATH, sql)
    print("Rehearsal successful.")

    backup = PROJECT_ROOT / f"trade_log_before_v19_{stamp()}.db"
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
    print("Database schema: v19")
    print("SQLite integrity_check: ok")
    print("Foreign-key check: clean")
    print("LOCAL_SURFACE_RESIDUAL_V2: observational persistence available")
    print("V2 decision path: hard-disabled")
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


class MigrationError(RuntimeError):
    pass


def get_schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT MAX(version) FROM schema_version;").fetchone()
    if row is None or row[0] is None:
        raise MigrationError("Database does not contain a schema version.")
    return int(row[0])


def iter_sql_statements(sql: str) -> Iterable[str]:
    buffer: list[str] = []
    for line in sql.splitlines(keepends=True):
        buffer.append(line)
        candidate = "".join(buffer)
        if sqlite3.complete_statement(candidate):
            statement = candidate.strip()
            if statement:
                yield statement
            buffer = []
    remainder = "".join(buffer).strip()
    if remainder:
        raise MigrationError("Migration contains an incomplete SQL statement.")


def _normalized(statement: str) -> str:
    return " ".join(statement.strip().upper().split())


def apply_migration_sql(
    connection: sqlite3.Connection,
    sql: str,
    *,
    expected_from: int,
    target_version: int,
) -> int:
    if connection.in_transaction:
        raise MigrationError("Migration connection already has an open transaction.")

    actual = get_schema_version(connection)
    if actual != expected_from:
        raise MigrationError(
            f"Migration expected schema v{expected_from}; found v{actual}."
        )

    connection.execute("PRAGMA foreign_keys = ON;")
    if connection.execute("PRAGMA foreign_keys;").fetchone()[0] != 1:
        raise MigrationError("SQLite foreign-key enforcement is not enabled.")

    statements = tuple(iter_sql_statements(sql))
    for statement in statements:
        normalized = _normalized(statement)
        if normalized.startswith("BEGIN ") or normalized in {"BEGIN;", "COMMIT;", "ROLLBACK;"}:
            raise MigrationError(
                "Migration scripts applied by the atomic runner may not contain outer transaction control."
            )

    try:
        connection.execute("BEGIN IMMEDIATE;")
        for statement in statements:
            normalized = _normalized(statement)
            if normalized.startswith("PRAGMA FOREIGN_KEYS"):
                # Already enabled before BEGIN. Changing this PRAGMA inside a transaction is a no-op.
                continue
            connection.execute(statement)

        actual_after = get_schema_version(connection)
        if actual_after != target_version:
            raise MigrationError(
                f"Migration did not advance schema to v{target_version}; found v{actual_after}."
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    return target_version


def apply_migration_file(
    connection: sqlite3.Connection,
    path: str | Path,
    *,
    expected_from: int,
    target_version: int,
) -> int:
    migration_path = Path(path)
    return apply_migration_sql(
        connection,
        migration_path.read_text(encoding="utf-8"),
        expected_from=expected_from,
        target_version=target_version,
    )


def apply_pending_migrations(
    connection: sqlite3.Connection,
    migrations_dir: str | Path,
) -> int:
    current = get_schema_version(connection)
    for path in sorted(Path(migrations_dir).glob("*.sql")):
        try:
            version = int(path.name.split("_", 1)[0])
        except ValueError as exc:
            raise MigrationError(f"Invalid migration filename: {path.name}") from exc
        if version <= current:
            continue
        if version != current + 1:
            raise MigrationError(
                f"Migration sequence gap: current v{current}, next file is v{version}."
            )
        current = apply_migration_file(
            connection,
            path,
            expected_from=current,
            target_version=version,
        )
    return current

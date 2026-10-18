"""Bounded migration-delta validation: prove what an additive schema release changes.

This is NOT a substitute for periodic full-database integrity and referential
audits. A release adding tables/indexes can verify those exact structures; a
release altering/dropping existing tables MUST use a separately reviewed
migration path rather than silently skip a full validation.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class SchemaDelta:
    new_tables: tuple[str, ...]
    affected_existing_tables: tuple[str, ...]
    touched_existing_tables: tuple[str, ...]


def _schema(conn: sqlite3.Connection) -> dict[tuple[str, str], tuple[str, str]]:
    return {
        (str(kind), str(name)): (str(tbl_name), str(sql))
        for kind, name, tbl_name, sql in conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%' "
            "AND sql IS NOT NULL;"
        ).fetchall()
    }


def capture_migration_schema(conn: sqlite3.Connection) -> dict[tuple[str, str], tuple[str, str]]:
    return _schema(conn)


def verify_additive_schema_migration(
    conn: sqlite3.Connection,
    before: dict[tuple[str, str], tuple[str, str]],
) -> SchemaDelta:
    """Check newly created tables and changed indexes, refuse destructive DDL.

    Existing-table content has not been changed by additive DDL, and SQLite
    enforces new tables' constraints as they are written. We do not repeat an
    unbounded FK scan of unrelated historical tables for each release.
    """
    after = _schema(conn)
    old_tables = {k for k in before if k[0] == "table"}
    new_tables = {k for k in after if k[0] == "table"}
    existing = old_tables & new_tables

    touched = sorted(
        name for kind, name in existing if before[(kind, name)] != after[(kind, name)]
    )
    dropped = sorted(name for _, name in old_tables - new_tables)
    if touched or dropped:
        raise RuntimeError(
            "MIGRATION_EXISTING_TABLE_DDL_REQUIRES_DEEP_AUDIT: "
            f"altered={touched} dropped={dropped}"
        )

    affected: set[str] = set()
    for key in set(before) | set(after):
        if key[0] != "index" or before.get(key) == after.get(key):
            continue
        for contents in (before.get(key), after.get(key)):
            if contents is not None:
                table_name = contents[0]
                if ("table", table_name) in existing:
                    affected.add(table_name)

    created = sorted(name for _, name in new_tables - old_tables)
    to_verify = sorted(set(created) | affected)
    for name in to_verify:
        identifier = '"' + name.replace('"', '""') + '"'
        check = conn.execute(f"PRAGMA quick_check({identifier})").fetchone()
        if check is None or str(check[0]) != "ok":
            raise RuntimeError(f"MIGRATION_TABLE_QUICK_CHECK_FAILED:{name}:{check}")
        foreign_violation = conn.execute(
            f"PRAGMA foreign_key_check({identifier})"
        ).fetchone()
        if foreign_violation is not None:
            raise RuntimeError(
                f"MIGRATION_TABLE_FOREIGN_KEY_CHECK_FAILED:{name}:{tuple(foreign_violation)}"
            )
    return SchemaDelta(tuple(created), tuple(sorted(affected)), tuple(touched))

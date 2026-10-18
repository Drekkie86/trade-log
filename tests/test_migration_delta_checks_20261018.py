from __future__ import annotations

import sqlite3

import pytest

from src.operations.migration_delta_checks import (
    capture_migration_schema,
    verify_additive_schema_migration,
)


def test_additive_new_table_passes_without_scanning_unmodified_tables():
    with sqlite3.connect(":memory:") as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("CREATE TABLE history(id INTEGER PRIMARY KEY)")
        db.executemany("INSERT INTO history(id) VALUES (?)", [(i,) for i in range(50)])
        before = capture_migration_schema(db)
        db.execute(
            "CREATE TABLE new_outcomes("
            "id INTEGER PRIMARY KEY, historical_id INTEGER REFERENCES history(id))"
        )
        delta = verify_additive_schema_migration(db, before)
        assert delta.new_tables == ("new_outcomes",)
        assert delta.affected_existing_tables == ()
        assert delta.touched_existing_tables == ()


def test_additive_fk_violation_is_not_allowed():
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE history(id INTEGER PRIMARY KEY)")
        before = capture_migration_schema(db)
        db.execute(
            "CREATE TABLE new_outcomes("
            "id INTEGER PRIMARY KEY, historical_id INTEGER REFERENCES history(id))"
        )
        db.execute("INSERT INTO new_outcomes VALUES (1, 9999)")
        with pytest.raises(RuntimeError, match="FOREIGN_KEY_CHECK_FAILED"):
            verify_additive_schema_migration(db, before)


def test_altering_an_existing_table_fails_closed():
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE history(id INTEGER PRIMARY KEY)")
        before = capture_migration_schema(db)
        db.execute("ALTER TABLE history ADD COLUMN payload TEXT")
        with pytest.raises(RuntimeError, match="EXISTING_TABLE_DDL_REQUIRES_DEEP_AUDIT"):
            verify_additive_schema_migration(db, before)


def test_dropping_existing_table_fails_closed():
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE history(id INTEGER PRIMARY KEY)")
        before = capture_migration_schema(db)
        db.execute("DROP TABLE history")
        with pytest.raises(RuntimeError, match="EXISTING_TABLE_DDL_REQUIRES_DEEP_AUDIT"):
            verify_additive_schema_migration(db, before)


def test_added_index_on_historical_table_is_scoped_for_verification():
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE history(id INTEGER PRIMARY KEY, value TEXT)")
        before = capture_migration_schema(db)
        db.execute("CREATE INDEX idx_history_value ON history(value)")
        delta = verify_additive_schema_migration(db, before)
        assert delta.new_tables == ()
        assert delta.affected_existing_tables == ("history",)

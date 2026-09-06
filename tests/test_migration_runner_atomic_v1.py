import sqlite3

import pytest

from src.database.migration_runner import MigrationError, apply_migration_sql


def _base(conn):
    conn.execute("CREATE TABLE schema_version(version INTEGER PRIMARY KEY, applied_at TEXT)")
    conn.execute("INSERT INTO schema_version VALUES(26, 'x')")
    conn.commit()


def test_failed_migration_rolls_back_all_prior_statements():
    conn = sqlite3.connect(":memory:")
    _base(conn)
    bad = """
    CREATE TABLE should_not_survive(id INTEGER PRIMARY KEY);
    INSERT INTO definitely_missing_table VALUES(1);
    INSERT INTO schema_version VALUES(27, 'x');
    """
    with pytest.raises(sqlite3.OperationalError):
        apply_migration_sql(conn, bad, expected_from=26, target_version=27)
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 26
    assert conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='should_not_survive'"
    ).fetchone()[0] == 0


def test_migration_requires_exact_target_schema_version():
    conn = sqlite3.connect(":memory:")
    _base(conn)
    bad = "CREATE TABLE x(id INTEGER);"
    with pytest.raises(MigrationError, match="did not advance"):
        apply_migration_sql(conn, bad, expected_from=26, target_version=27)
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='x'").fetchone()[0] == 0

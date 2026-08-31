import sqlite3
from pathlib import Path

from migrate_real_database_to_v9 import sqlite_backup


def test_sqlite_backup_preserves_committed_wal_data(tmp_path):
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"

    source_conn = sqlite3.connect(source)
    try:
        source_conn.execute("PRAGMA journal_mode=WAL;")
        source_conn.execute(
            "CREATE TABLE evidence (id INTEGER PRIMARY KEY, value TEXT);"
        )
        source_conn.execute(
            "INSERT INTO evidence(value) VALUES ('committed');"
        )
        source_conn.commit()

        sqlite_backup(source, backup)

        backup_conn = sqlite3.connect(backup)
        try:
            row = backup_conn.execute(
                "SELECT value FROM evidence;"
            ).fetchone()
            assert row[0] == "committed"
        finally:
            backup_conn.close()
    finally:
        source_conn.close()

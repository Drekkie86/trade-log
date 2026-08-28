import sqlite3

from migrate_real_database_to_v7 import version


def test_version_returns_highest_applied_schema_version(
    tmp_path,
):
    db_path = tmp_path / "history.db"

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    try:
        connection.execute(
            """
            CREATE TABLE schema_version (
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL
            );
            """
        )

        connection.executemany(
            """
            INSERT INTO schema_version (
                version,
                applied_at
            )
            VALUES (?, ?);
            """,
            [
                (1, "t1"),
                (2, "t2"),
                (3, "t3"),
                (4, "t4"),
                (5, "t5"),
                (6, "t6"),
            ],
        )

        assert version(connection) == 6

    finally:
        connection.close()

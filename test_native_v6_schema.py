from __future__ import annotations

from pathlib import Path
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parent

SCHEMA_FILE = (
    PROJECT_ROOT
    / "trade_log_schema_v6_generated.sql"
)

TEST_DATABASE = (
    PROJECT_ROOT
    / "trade_log_fresh_v6_test.db"
)


def latest_version(
    connection: sqlite3.Connection,
) -> int:
    row = connection.execute(
        """
        SELECT version
        FROM schema_version
        ORDER BY version DESC
        LIMIT 1;
        """
    ).fetchone()

    if row is None:
        raise RuntimeError(
            "schema_version is empty."
        )

    return int(row[0])


def main() -> None:
    print()
    print(
        "Christiania - fresh v6 schema test"
    )
    print(
        "----------------------------------"
    )
    print()

    if not SCHEMA_FILE.exists():
        raise RuntimeError(
            "Run export_native_v6_schema.py "
            "first."
        )

    if TEST_DATABASE.exists():
        TEST_DATABASE.unlink()

    connection = sqlite3.connect(
        TEST_DATABASE
    )

    try:
        connection.execute(
            "PRAGMA foreign_keys = ON;"
        )

        sql = SCHEMA_FILE.read_text(
            encoding="utf-8"
        )

        connection.executescript(
            sql
        )

        connection.commit()

        version = latest_version(
            connection
        )

        if version != 6:
            raise RuntimeError(
                f"Expected schema v6, got v{version}."
            )

        integrity = connection.execute(
            "PRAGMA integrity_check;"
        ).fetchone()[0]

        if integrity != "ok":
            raise RuntimeError(
                "Fresh database failed "
                f"integrity_check: {integrity}"
            )

        foreign_keys = (
            connection.execute(
                "PRAGMA foreign_key_check;"
            ).fetchall()
        )

        if foreign_keys:
            raise RuntimeError(
                "Fresh database has foreign-key "
                f"violations: {foreign_keys}"
            )

        required_tables = {
            "trades",
            "trade_legs",
            "annotations",
            "market_snapshots",
            "option_quotes",
            "candidates",
            "candidate_legs",
            "candidate_controls",
            "provider_model_observations",
            "saxo_underlying_observations",
            "saxo_option_observations",
            "saxo_resolution_failures",
            "research_runs",
            "research_run_underlyings",
            "research_provider_attempts",
            "normalization_drops",
            "research_selections",
        }

        actual_tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%';
                """
            )
        }

        missing = (
            required_tables
            - actual_tables
        )

        if missing:
            raise RuntimeError(
                "Fresh schema is missing tables: "
                + ", ".join(
                    sorted(missing)
                )
            )

        print(
            "Fresh database created successfully."
        )
        print(
            "Schema version: v6"
        )
        print(
            "SQLite integrity_check: ok"
        )
        print(
            "Foreign-key check: clean"
        )
        print(
            f"Tables present: {len(actual_tables)}"
        )
        print()
        print(
            "Generated test database:"
        )
        print(
            f"  {TEST_DATABASE.name}"
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()

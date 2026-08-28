from pathlib import Path
import shutil
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parent

SOURCE_DATABASE = (
    PROJECT_ROOT
    / "trade_log.db"
)

TEST_DATABASE = (
    PROJECT_ROOT
    / "trade_log_v6_test.db"
)

MIGRATION_005 = (
    PROJECT_ROOT
    / "migrations"
    / "005_provider_evidence_hardening.sql"
)

MIGRATION_006 = (
    PROJECT_ROOT
    / "migrations"
    / "006_cohort_research_integrity.sql"
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
            "Database has no schema version."
        )

    return int(row[0])


def main():
    print()
    print("Christiania - v6 migration rehearsal")
    print("------------------------------------")
    print()

    if not SOURCE_DATABASE.exists():
        raise RuntimeError(
            f"Missing source database: "
            f"{SOURCE_DATABASE}"
        )

    shutil.copy2(
        SOURCE_DATABASE,
        TEST_DATABASE,
    )

    connection = sqlite3.connect(
        TEST_DATABASE
    )

    try:
        connection.execute(
            "PRAGMA foreign_keys = ON;"
        )

        version = latest_version(
            connection
        )

        print(
            f"Disposable copy starts at "
            f"schema v{version}."
        )

        if version == 4:
            sql_005 = (
                MIGRATION_005
                .read_text(
                    encoding="utf-8"
                )
            )

            connection.executescript(
                sql_005
            )

            version = latest_version(
                connection
            )

            print(
                f"Migration 005 -> "
                f"schema v{version}."
            )

        if version != 5:
            raise RuntimeError(
                "Migration 006 expects a "
                f"v5 database, got v{version}."
            )

        sql_006 = (
            MIGRATION_006
            .read_text(
                encoding="utf-8"
            )
        )

        connection.executescript(
            sql_006
        )

        connection.commit()

        version = latest_version(
            connection
        )

        if version != 6:
            raise RuntimeError(
                "Expected schema v6, "
                f"got v{version}."
            )

        expected_tables = {
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
                WHERE type = 'table';
                """
            )
        }

        missing = (
            expected_tables
            - actual_tables
        )

        if missing:
            raise RuntimeError(
                "Missing v6 tables: "
                + ", ".join(
                    sorted(missing)
                )
            )

        print(
            "Migration 006 -> schema v6."
        )

        print()
        print(
            "V6 migration rehearsal "
            "successful."
        )
        print()
        print(
            "Real trade_log.db was NOT "
            "modified."
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()

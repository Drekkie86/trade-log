from pathlib import Path
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parent

DATABASE_PATH = (
    PROJECT_ROOT
    / "trade_log_v5_test.db"
)

MIGRATION_PATH = (
    PROJECT_ROOT
    / "migrations"
    / "005_provider_evidence_hardening.sql"
)


def main():
    print()
    print("Christiania - v5 migration test")
    print("--------------------------------")
    print()

    if not DATABASE_PATH.exists():
        raise RuntimeError(
            f"Test database does not exist: "
            f"{DATABASE_PATH}"
        )

    if not MIGRATION_PATH.exists():
        raise RuntimeError(
            f"Migration file does not exist: "
            f"{MIGRATION_PATH}"
        )

    connection = sqlite3.connect(
        DATABASE_PATH
    )

    try:
        connection.execute(
            "PRAGMA foreign_keys = ON;"
        )

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
                "Test database has no "
                "schema_version row."
            )

        current_version = row[0]

        print(
            f"Current schema version: "
            f"{current_version}"
        )

        if current_version != 4:
            raise RuntimeError(
                "Migration 005 requires "
                "schema version 4, "
                f"got {current_version}."
            )

        sql = MIGRATION_PATH.read_text(
            encoding="utf-8"
        )

        connection.executescript(
            sql
        )

        connection.commit()

        versions = (
            connection.execute(
                """
                SELECT
                    version,
                    applied_at
                FROM schema_version
                ORDER BY version;
                """
            )
            .fetchall()
        )

        print()
        print("Schema versions:")
        print()

        for version, applied_at in versions:
            print(
                f"  {version}  "
                f"{applied_at}"
            )

        print()

        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table';
                """
            )
        }

        expected_tables = {
            "provider_model_observations",
            "saxo_underlying_observations",
            "saxo_option_observations",
            "saxo_resolution_failures",
        }

        missing_tables = (
            expected_tables
            - tables
        )

        if missing_tables:
            raise RuntimeError(
                "Migration completed but "
                "expected tables are missing: "
                + ", ".join(
                    sorted(
                        missing_tables
                    )
                )
            )

        latest_version = (
            versions[-1][0]
            if versions
            else None
        )

        if latest_version != 5:
            raise RuntimeError(
                "Expected schema version 5, "
                f"got {latest_version}."
            )

        print(
            "Migration test successful."
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()
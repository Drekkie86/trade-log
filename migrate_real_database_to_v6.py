from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parent

DATABASE = PROJECT_ROOT / "trade_log.db"
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"

MIGRATION_005 = (
    MIGRATIONS_DIR
    / "005_provider_evidence_hardening.sql"
)

MIGRATION_006 = (
    MIGRATIONS_DIR
    / "006_cohort_research_integrity.sql"
)


def utc_timestamp_for_filename() -> str:
    return (
        datetime.now(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )


def latest_schema_version(
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


def verify_v6(
    connection: sqlite3.Connection,
) -> None:
    version = latest_schema_version(
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
            "SQLite integrity_check failed: "
            f"{integrity}"
        )

    foreign_key_rows = (
        connection.execute(
            "PRAGMA foreign_key_check;"
        ).fetchall()
    )

    if foreign_key_rows:
        raise RuntimeError(
            "Foreign-key violations found "
            f"after migration: {foreign_key_rows}"
        )

    expected_tables = {
        "research_runs",
        "research_run_underlyings",
        "research_provider_attempts",
        "normalization_drops",
        "research_selections",
        "provider_model_observations",
        "saxo_underlying_observations",
        "saxo_option_observations",
        "saxo_resolution_failures",
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

    missing_tables = (
        expected_tables
        - actual_tables
    )

    if missing_tables:
        raise RuntimeError(
            "Missing expected v6 tables: "
            + ", ".join(
                sorted(missing_tables)
            )
        )

    option_quote_columns = {
        row[1]
        for row in connection.execute(
            """
            PRAGMA table_info(
                option_quotes
            );
            """
        )
    }

    for required in {
        "shares_per_contract",
        "open_interest_as_of_date",
        "volume_trading_date",
    }:
        if required not in option_quote_columns:
            raise RuntimeError(
                "option_quotes is missing "
                f"required column: {required}"
            )

    saxo_option_columns = {
        row[1]
        for row in connection.execute(
            """
            PRAGMA table_info(
                saxo_option_observations
            );
            """
        )
    }

    for required in {
        "quote_quality_version",
        "is_stale",
        "is_indicative",
        "is_delayed",
        "is_locked",
        "is_crossed",
        "observation_gap_seconds",
        "retry_count",
        "resolution_sequence",
    }:
        if required not in saxo_option_columns:
            raise RuntimeError(
                "saxo_option_observations "
                "is missing required column: "
                f"{required}"
            )


def apply_sql_file(
    connection: sqlite3.Connection,
    path: Path,
) -> None:
    if not path.exists():
        raise RuntimeError(
            f"Missing migration file: {path}"
        )

    sql = path.read_text(
        encoding="utf-8"
    )

    connection.executescript(
        sql
    )


def main() -> None:
    print()
    print(
        "Christiania - real database migration"
    )
    print(
        "--------------------------------------"
    )
    print()

    if not DATABASE.exists():
        raise RuntimeError(
            f"Database not found: {DATABASE}"
        )

    backup = (
        PROJECT_ROOT
        / (
            "trade_log_before_v6_"
            + utc_timestamp_for_filename()
            + ".db"
        )
    )

    shutil.copy2(
        DATABASE,
        backup,
    )

    print("Backup created:")
    print(f"  {backup.name}")
    print()

    connection = sqlite3.connect(
        DATABASE
    )

    try:
        connection.execute(
            "PRAGMA foreign_keys = ON;"
        )

        current = latest_schema_version(
            connection
        )

        print(
            f"Current schema version: v{current}"
        )

        if current < 4:
            raise RuntimeError(
                "Automatic migration is only "
                "supported from schema v4 or v5."
            )

        if current > 6:
            raise RuntimeError(
                "Database is newer than this "
                "migration script understands."
            )

        if current == 4:
            print(
                "Applying migration 005..."
            )

            apply_sql_file(
                connection,
                MIGRATION_005,
            )

            current = latest_schema_version(
                connection
            )

            if current != 5:
                raise RuntimeError(
                    "Migration 005 did not "
                    "produce schema v5."
                )

            print(
                "Migration 005 complete."
            )

        if current == 5:
            print(
                "Applying migration 006..."
            )

            apply_sql_file(
                connection,
                MIGRATION_006,
            )

            current = latest_schema_version(
                connection
            )

            if current != 6:
                raise RuntimeError(
                    "Migration 006 did not "
                    "produce schema v6."
                )

            print(
                "Migration 006 complete."
            )

        if current == 6:
            print(
                "Verifying schema v6..."
            )

            verify_v6(
                connection
            )

            connection.commit()

            print()
            print(
                "Migration successful."
            )
            print(
                "Database schema: v6"
            )
            print(
                "SQLite integrity_check: ok"
            )
            print(
                "Foreign-key check: clean"
            )
            print()
            print(
                "Keep the backup until the "
                "next full test run is green."
            )

    except Exception:
        connection.rollback()

        print()
        print(
            "MIGRATION FAILED."
        )
        print(
            "The pre-migration backup was "
            "left untouched:"
        )
        print(
            f"  {backup.name}"
        )

        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()

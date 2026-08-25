import sqlite3
from pathlib import Path

import pytest

from src.database.repository import get_connection


BASE_DIR = Path(__file__).resolve().parents[1]

SCHEMA_PATH = (
    BASE_DIR
    / "trade_log_schema.sql"
)

MIGRATIONS_DIR = (
    BASE_DIR
    / "migrations"
)


def get_db_version(
    connection: sqlite3.Connection,
) -> int:
    row = connection.execute(
        """
        SELECT MAX(version)
        FROM schema_version;
        """
    ).fetchone()

    if row is None or row[0] is None:
        raise RuntimeError(
            "Test database has no schema version."
        )

    return int(row[0])


def apply_pending_migrations(
    connection: sqlite3.Connection,
) -> None:
    """
    Upgrade a freshly-created test DB to the newest
    available migration.

    This means our tests exercise the migration path too.
    """
    current_version = get_db_version(
        connection
    )

    migration_files = sorted(
        MIGRATIONS_DIR.glob("*.sql")
    )

    for migration_path in migration_files:
        migration_version = int(
            migration_path.name.split(
                "_",
                1,
            )[0]
        )

        if migration_version <= current_version:
            continue

        sql = migration_path.read_text(
            encoding="utf-8"
        )

        connection.executescript(sql)

        current_version = get_db_version(
            connection
        )


@pytest.fixture
def db_path(tmp_path):
    """
    Every test gets its own disposable database.

    Your real trade_log.db is never touched.
    """
    path = (
        tmp_path
        / "test_trade_log.db"
    )

    schema_sql = SCHEMA_PATH.read_text(
        encoding="utf-8"
    )

    connection = get_connection(path)

    try:
        connection.executescript(
            schema_sql
        )

        apply_pending_migrations(
            connection
        )

        connection.commit()

    finally:
        connection.close()

    return path


@pytest.fixture
def base_trade():
    return {
        "created_at":
            "2026-08-25T20:00:00Z",

        "underlying":
            "TEST",

        "currency":
            "USD",

        # Safe default used for development/tests.
        "is_paper":
            1,

        "status":
            "OPEN",

        "parent_trade_id":
            None,

        "strategy":
            "LONG_CALL",

        # Intentionally different from created_at.
        "entry_at":
            "2026-08-25T19:57:13Z",

        "entry_underlying":
            100.00,

        "entry_fx_rate":
            0.86,

        "entry_fees":
            100,

        "entry_cash":
            -220000,

        "thesis":
            "The underlying is likely to rise.",

        "prediction":
            "TEST closes above 105 before the horizon.",

        "horizon_date":
            "2026-09-30",

        "p_thesis":
            0.65,

        "p_profit":
            0.52,

        "invalidation":
            "Underlying closes below 90.",

        "max_loss":
            220000,

        "profit_target":
            "Close at 50% gain.",

        "stop_condition":
            "Exit if thesis is invalidated.",

        "rejection_reason":
            None,
    }


@pytest.fixture
def base_leg():
    return {
        "leg_no":
            1,

        "right":
            "C",

        "direction":
            "BUY",

        "strike":
            105.0,

        "expiration":
            "2026-09-30",

        "contracts":
            1,

        "multiplier":
            100,

        "entry_bid":
            21.90,

        "entry_ask":
            22.10,

        "entry_fill":
            22.00,
    }
import sqlite3
from pathlib import Path

import pytest

from src.database.repository import get_connection
from src.database.migration_runner import apply_pending_migrations as apply_migrations_atomically


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
    apply_migrations_atomically(connection, MIGRATIONS_DIR)


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

    connection = get_connection(
        path
    )

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

        "is_paper":
            1,

        "status":
            "OPEN",

        "parent_trade_id":
            None,

        "strategy":
            "LONG_CALL",

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

        "entry_iv_rank":
            42.0,

        "next_earnings_date":
            "2026-10-20",

        "thesis":
            "The underlying is likely to rise.",

        "prediction":
            "TEST closes above 105 before the horizon.",

        "horizon_date":
            "2026-09-30",

        "p_thesis_initial":
            0.65,

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

        "entry_quote_at":
            "2026-08-25T19:56:50Z",

        "entry_iv":
            0.31,

        "entry_delta":
            0.38,

        "entry_bid":
            21.90,

        "entry_ask":
            22.10,

        "entry_fill":
            22.00,
    }
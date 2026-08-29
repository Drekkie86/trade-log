from __future__ import annotations

import sqlite3

from src.research.thetadata_history_staging import (
    create_run,
    initialize_staging_db,
    insert_rows,
)


def test_initialize_and_bulk_insert(tmp_path):
    db = tmp_path / "stage.db"
    initialize_staging_db(db)

    with sqlite3.connect(db) as connection:
        run_id = create_run(
            connection,
            symbol="AAPL",
            trading_date=__import__("datetime").date(2026, 8, 28),
            max_dte=45,
            started_at_utc="2026-08-29T10:00:00Z",
        )

        count = insert_rows(
            connection,
            run_id=run_id,
            rows=[
                {
                    "provider": "THETADATA",
                    "underlying": "AAPL",
                    "expiration": "2026-09-25",
                    "strike": 225.0,
                    "right": "PUT",
                    "bid": 0.01,
                    "ask": 0.09,
                    "bid_size": 111,
                    "ask_size": 98,
                    "created": "2026-08-28T17:15:16.204",
                    "last_trade": "2026-08-28T14:46:50.983",
                }
            ],
        )

        assert count == 1

        row = connection.execute(
            """
            SELECT
                underlying,
                expiration,
                strike,
                right,
                bid,
                ask,
                provider_created,
                provider_last_trade
            FROM thetadata_eod_option_rows
            """
        ).fetchone()

        assert row == (
            "AAPL",
            "2026-09-25",
            225.0,
            "PUT",
            0.01,
            0.09,
            "2026-08-28T17:15:16.204",
            "2026-08-28T14:46:50.983",
        )


def test_duplicate_identity_in_same_run_fails(tmp_path):
    db = tmp_path / "stage.db"
    initialize_staging_db(db)

    with sqlite3.connect(db) as connection:
        run_id = create_run(
            connection,
            symbol="AAPL",
            trading_date=__import__("datetime").date(2026, 8, 28),
            max_dte=45,
            started_at_utc="2026-08-29T10:00:00Z",
        )

        row = {
            "provider": "THETADATA",
            "underlying": "AAPL",
            "expiration": "2026-09-25",
            "strike": 225.0,
            "right": "PUT",
        }

        import pytest

        with pytest.raises(sqlite3.IntegrityError):
            insert_rows(
                connection,
                run_id=run_id,
                rows=[row, row],
            )

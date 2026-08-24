import sqlite3
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "trade_log.db"


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def get_table_names() -> list[str]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name;
            """
        ).fetchall()

    return [row["name"] for row in rows]


def create_trade(
    trade: dict[str, Any],
    legs: list[dict[str, Any]] | None = None,
) -> int:
    legs = legs or []

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO trades (
                created_at,
                underlying,
                currency,
                status,
                parent_trade_id,
                strategy,
                entry_at,
                entry_underlying,
                entry_fx_rate,
                entry_fees,
                entry_cash,
                thesis,
                prediction,
                horizon_date,
                p_thesis,
                p_profit,
                invalidation,
                max_loss,
                profit_target,
                stop_condition,
                rejection_reason
            )
            VALUES (
                :created_at,
                :underlying,
                :currency,
                :status,
                :parent_trade_id,
                :strategy,
                :entry_at,
                :entry_underlying,
                :entry_fx_rate,
                :entry_fees,
                :entry_cash,
                :thesis,
                :prediction,
                :horizon_date,
                :p_thesis,
                :p_profit,
                :invalidation,
                :max_loss,
                :profit_target,
                :stop_condition,
                :rejection_reason
            );
            """,
            trade,
        )

        trade_id = cursor.lastrowid

        for leg in legs:
            leg_data = dict(leg)
            leg_data["trade_id"] = trade_id

            connection.execute(
                """
                INSERT INTO trade_legs (
                    trade_id,
                    leg_no,
                    right,
                    direction,
                    strike,
                    expiration,
                    contracts,
                    multiplier,
                    entry_bid,
                    entry_ask,
                    entry_fill
                )
                VALUES (
                    :trade_id,
                    :leg_no,
                    :right,
                    :direction,
                    :strike,
                    :expiration,
                    :contracts,
                    :multiplier,
                    :entry_bid,
                    :entry_ask,
                    :entry_fill
                );
                """,
                leg_data,
            )

        return trade_id

def get_trade(trade_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        trade_row = connection.execute(
            """
            SELECT *
            FROM trades
            WHERE id = ?;
            """,
            (trade_id,),
        ).fetchone()

        if trade_row is None:
            return None

        leg_rows = connection.execute(
            """
            SELECT *
            FROM trade_legs
            WHERE trade_id = ?
            ORDER BY leg_no;
            """,
            (trade_id,),
        ).fetchall()

    return {
        "trade": dict(trade_row),
        "legs": [dict(row) for row in leg_rows],
    }
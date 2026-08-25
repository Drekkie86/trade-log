import sqlite3
from contextlib import closing, contextmanager
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "trade_log.db"

EXPECTED_SCHEMA_VERSION = 3


def to_minor(amount) -> int:
    """
    Convert a major currency amount into integer minor units.

    Examples:
        22.00 -> 2200
        2.20  -> 220
    """
    value = (
        amount
        if isinstance(amount, Decimal)
        else Decimal(str(amount))
    )

    return int(
        (value * 100).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def get_connection(db_path=None) -> sqlite3.Connection:
    path = db_path or DB_PATH

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row

    # Foreign-key enforcement is per SQLite connection.
    connection.execute("PRAGMA foreign_keys = ON;")

    return connection


@contextmanager
def transaction(db_path=None, conn=None):
    """
    Reuse an existing connection if supplied.

    Otherwise own the connection and transaction.
    """
    if conn is not None:
        yield conn
        return

    own_connection = get_connection(db_path)

    try:
        with own_connection:
            yield own_connection
    finally:
        own_connection.close()


def get_schema_version(db_path=None) -> int:
    with closing(
        get_connection(db_path)
    ) as connection:

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

    return row["version"]


def assert_schema_version(db_path=None) -> None:
    actual_version = get_schema_version(
        db_path
    )

    if actual_version != EXPECTED_SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {actual_version} "
            f"does not match expected version "
            f"{EXPECTED_SCHEMA_VERSION}."
        )


def get_table_names(db_path=None) -> list[str]:
    with closing(
        get_connection(db_path)
    ) as connection:

        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name;
            """
        ).fetchall()

    return [
        row["name"]
        for row in rows
    ]


def create_trade(
    trade: dict[str, Any],
    legs: list[dict[str, Any]] | None = None,
    db_path=None,
    conn=None,
) -> int:
    """
    Create one trade decision and all its option legs atomically.
    """
    legs = legs or []

    required_fields = [
        "created_at",
        "underlying",
        "currency",
        "status",
        "thesis",
        "prediction",
        "horizon_date",
        "p_thesis_initial",
        "p_thesis",
        "p_profit",
        "invalidation",
        "max_loss",
        "profit_target",
        "stop_condition",
    ]

    missing = [
        field
        for field in required_fields
        if field not in trade
        or trade[field] is None
    ]

    if missing:
        raise ValueError(
            "Missing required trade fields: "
            + ", ".join(missing)
        )

    trade_data = {
        "created_at":
            trade["created_at"],

        "underlying":
            trade["underlying"],

        "currency":
            trade["currency"],

        "is_paper":
            trade.get(
                "is_paper",
                1,
            ),

        "status":
            trade["status"],

        "parent_trade_id":
            trade.get(
                "parent_trade_id"
            ),

        "strategy":
            trade.get(
                "strategy"
            ),

        "entry_at":
            trade.get(
                "entry_at"
            ),

        "entry_underlying":
            trade.get(
                "entry_underlying"
            ),

        "entry_fx_rate":
            trade.get(
                "entry_fx_rate"
            ),

        "entry_fees":
            trade.get(
                "entry_fees"
            ),

        "entry_cash":
            trade.get(
                "entry_cash"
            ),

        "entry_iv_rank":
            trade.get(
                "entry_iv_rank"
            ),

        "next_earnings_date":
            trade.get(
                "next_earnings_date"
            ),

        "thesis":
            trade["thesis"],

        "prediction":
            trade["prediction"],

        "horizon_date":
            trade["horizon_date"],

        "p_thesis_initial":
            trade["p_thesis_initial"],

        "p_thesis":
            trade["p_thesis"],

        "p_profit":
            trade["p_profit"],

        "invalidation":
            trade["invalidation"],

        "max_loss":
            trade["max_loss"],

        "profit_target":
            trade["profit_target"],

        "stop_condition":
            trade["stop_condition"],

        "rejection_reason":
            trade.get(
                "rejection_reason"
            ),
    }

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:

        cursor = connection.execute(
            """
            INSERT INTO trades (
                created_at,
                underlying,
                currency,
                is_paper,
                status,
                parent_trade_id,
                strategy,

                entry_at,
                entry_underlying,
                entry_fx_rate,
                entry_fees,
                entry_cash,

                entry_iv_rank,
                next_earnings_date,

                thesis,
                prediction,
                horizon_date,
                p_thesis_initial,
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
                :is_paper,
                :status,
                :parent_trade_id,
                :strategy,

                :entry_at,
                :entry_underlying,
                :entry_fx_rate,
                :entry_fees,
                :entry_cash,

                :entry_iv_rank,
                :next_earnings_date,

                :thesis,
                :prediction,
                :horizon_date,
                :p_thesis_initial,
                :p_thesis,
                :p_profit,
                :invalidation,

                :max_loss,
                :profit_target,
                :stop_condition,

                :rejection_reason
            );
            """,
            trade_data,
        )

        trade_id = cursor.lastrowid

        for leg in legs:
            leg_data = {
                "trade_id":
                    trade_id,

                "leg_no":
                    leg["leg_no"],

                "right":
                    leg["right"],

                "direction":
                    leg["direction"],

                "strike":
                    leg["strike"],

                "expiration":
                    leg["expiration"],

                "contracts":
                    leg["contracts"],

                "multiplier":
                    leg.get(
                        "multiplier",
                        100,
                    ),

                "entry_quote_at":
                    leg.get(
                        "entry_quote_at"
                    ),

                "entry_iv":
                    leg.get(
                        "entry_iv"
                    ),

                "entry_delta":
                    leg.get(
                        "entry_delta"
                    ),

                "entry_bid":
                    leg["entry_bid"],

                "entry_ask":
                    leg["entry_ask"],

                "entry_fill":
                    leg["entry_fill"],
            }

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

                    entry_quote_at,
                    entry_iv,
                    entry_delta,

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

                    :entry_quote_at,
                    :entry_iv,
                    :entry_delta,

                    :entry_bid,
                    :entry_ask,
                    :entry_fill
                );
                """,
                leg_data,
            )

        return trade_id


def get_trade(
    trade_id: int,
    db_path=None,
    conn=None,
) -> dict[str, Any] | None:
    own_connection = conn is None

    connection = (
        conn
        or get_connection(db_path)
    )

    try:
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
            "trade":
                dict(trade_row),

            "legs":
                [
                    dict(row)
                    for row in leg_rows
                ],
        }

    finally:
        if own_connection:
            connection.close()


def close_trade(
    trade_id: int,
    *,
    status: str,
    exit_at: str,
    exit_underlying: float,
    exit_fx_rate: float | None,
    exit_fees: int,
    exit_cash: int,
    exit_reason: str,
    leg_exits: list[dict[str, Any]] | None = None,
    db_path=None,
    conn=None,
) -> None:
    allowed_statuses = {
        "CLOSED",
        "EXPIRED",
        "ASSIGNED",
        "ROLLED",
    }

    if status not in allowed_statuses:
        raise ValueError(
            f"Invalid closing status: {status}"
        )

    leg_exits = leg_exits or []

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:

        row = connection.execute(
            """
            SELECT id, status
            FROM trades
            WHERE id = ?;
            """,
            (trade_id,),
        ).fetchone()

        if row is None:
            raise ValueError(
                f"Trade {trade_id} does not exist."
            )

        connection.execute(
            """
            UPDATE trades
            SET
                status = ?,
                exit_at = ?,
                exit_underlying = ?,
                exit_fx_rate = ?,
                exit_fees = ?,
                exit_cash = ?,
                exit_reason = ?
            WHERE id = ?;
            """,
            (
                status,
                exit_at,
                exit_underlying,
                exit_fx_rate,
                exit_fees,
                exit_cash,
                exit_reason,
                trade_id,
            ),
        )

        for leg_exit in leg_exits:
            connection.execute(
                """
                UPDATE trade_legs
                SET
                    exit_bid = ?,
                    exit_ask = ?,
                    exit_fill = ?
                WHERE trade_id = ?
                  AND leg_no = ?;
                """,
                (
                    leg_exit.get(
                        "exit_bid"
                    ),
                    leg_exit.get(
                        "exit_ask"
                    ),
                    leg_exit.get(
                        "exit_fill"
                    ),
                    trade_id,
                    leg_exit["leg_no"],
                ),
            )


def resolve_trade(
    trade_id: int,
    *,
    thesis_correct: bool,
    was_profitable: bool | None,
    resolved_at: str,
    db_path=None,
    conn=None,
) -> None:
    allowed_statuses = {
        "CLOSED",
        "EXPIRED",
        "ASSIGNED",
        "ROLLED",
        "REJECTED",
    }

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:

        row = connection.execute(
            """
            SELECT status, resolved_at
            FROM trades
            WHERE id = ?;
            """,
            (trade_id,),
        ).fetchone()

        if row is None:
            raise ValueError(
                f"Trade {trade_id} does not exist."
            )

        if row["resolved_at"] is not None:
            raise ValueError(
                "This trade has already been resolved."
            )

        if row["status"] not in allowed_statuses:
            raise ValueError(
                f"Cannot resolve a "
                f"{row['status']} trade. "
                f"Close or reject it first."
            )

        if (
            row["status"] == "REJECTED"
            and was_profitable is not None
        ):
            raise ValueError(
                "Rejected decisions cannot be "
                "scored for profitability."
            )

        if (
            row["status"] != "REJECTED"
            and was_profitable is None
        ):
            raise ValueError(
                "Completed trades require a "
                "profitability outcome."
            )

        connection.execute(
            """
            UPDATE trades
            SET
                thesis_correct = ?,
                was_profitable = ?,
                resolved_at = ?
            WHERE id = ?;
            """,
            (
                int(thesis_correct),
                (
                    None
                    if was_profitable is None
                    else int(was_profitable)
                ),
                resolved_at,
                trade_id,
            ),
        )


def add_annotation(
    trade_id: int,
    *,
    created_at: str,
    body: str,
    db_path=None,
    conn=None,
) -> int:
    if not body.strip():
        raise ValueError(
            "Annotation body cannot be blank."
        )

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:

        cursor = connection.execute(
            """
            INSERT INTO annotations (
                trade_id,
                created_at,
                body
            )
            VALUES (?, ?, ?);
            """,
            (
                trade_id,
                created_at,
                body,
            ),
        )

        return cursor.lastrowid


def get_realized_pnl_minor(
    trade_id: int,
    db_path=None,
) -> int | None:
    with closing(
        get_connection(db_path)
    ) as connection:

        row = connection.execute(
            """
            SELECT pnl_minor
            FROM v_realized_pnl
            WHERE id = ?;
            """,
            (trade_id,),
        ).fetchone()

    if row is None:
        return None

    return row["pnl_minor"]
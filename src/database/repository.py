import sqlite3
from contextlib import closing, contextmanager
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from src.config import get_runtime_setting


BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "trade_log.db"


def resolve_db_path(db_path=None) -> Path:
    if db_path is not None:
        return Path(db_path).expanduser()

    configured = get_runtime_setting(
        "CHRISTIANIA_DB_PATH"
    )

    if configured:
        return Path(configured).expanduser()

    return DB_PATH

EXPECTED_SCHEMA_VERSION = 25


PROVENANCE_VALUES = {
    "MANUAL",
    "FETCHED",
    "DERIVED",
    "UNKNOWN",
}

CANDIDATE_STATUSES = {
    "TRACKING",
    "WATCH",
    "PAPER",
    "LIVE",
    "REJECTED",
    "RESOLVED",
}


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
    path = resolve_db_path(db_path)

    connection = sqlite3.connect(path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")

    current_journal_mode = connection.execute(
        "PRAGMA journal_mode;"
    ).fetchone()[0]

    if str(current_journal_mode).lower() != "wal":
        connection.execute("PRAGMA journal_mode = WAL;")

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


# =====================================================================
# EXISTING TRADE LAYER
# =====================================================================


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


# =====================================================================
# CHRISTIANIA RESEARCH LAYER
# =====================================================================


def _require_fields(
    data: dict[str, Any],
    required_fields: list[str],
    object_name: str,
) -> None:
    missing = [
        field
        for field in required_fields
        if field not in data
        or data[field] is None
    ]

    if missing:
        raise ValueError(
            f"Missing required {object_name} fields: "
            + ", ".join(missing)
        )


def _validate_source(
    source: str,
    field_name: str,
) -> None:
    if source not in PROVENANCE_VALUES:
        raise ValueError(
            f"Invalid provenance for {field_name}: "
            f"{source}"
        )


def _validate_value_source_pair(
    value,
    source: str,
    field_name: str,
) -> None:
    _validate_source(
        source,
        field_name,
    )

    if value is None and source != "UNKNOWN":
        raise ValueError(
            f"{field_name} is missing, so its source "
            f"must be UNKNOWN."
        )

    if value is not None and source == "UNKNOWN":
        raise ValueError(
            f"{field_name} has a value, so its source "
            f"cannot be UNKNOWN."
        )


def _validate_snapshot(
    snapshot: dict[str, Any],
) -> None:
    _require_fields(
        snapshot,
        [
            "captured_at",
            "underlying",
            "provider",
            "underlying_source",
            "fx_source",
        ],
        "snapshot",
    )

    if not str(
        snapshot["underlying"]
    ).strip():
        raise ValueError(
            "Snapshot underlying cannot be blank."
        )

    if not str(
        snapshot["provider"]
    ).strip():
        raise ValueError(
            "Snapshot provider cannot be blank."
        )

    _validate_value_source_pair(
        snapshot.get(
            "underlying_price"
        ),
        snapshot["underlying_source"],
        "underlying_price",
    )

    _validate_value_source_pair(
        snapshot.get(
            "fx_to_eur"
        ),
        snapshot["fx_source"],
        "fx_to_eur",
    )


def _validate_quote(
    quote: dict[str, Any],
) -> None:
    _require_fields(
        quote,
        [
            "right",
            "strike",
            "expiration",
            "bid_source",
            "ask_source",
            "last_source",
            "iv_source",
            "delta_source",
            "gamma_source",
            "theta_source",
            "vega_source",
            "volume_source",
            "open_interest_source",
        ],
        "quote",
    )

    if quote["right"] not in {
        "C",
        "P",
    }:
        raise ValueError(
            "Quote right must be C or P."
        )

    if float(
        quote["strike"]
    ) <= 0:
        raise ValueError(
            "Quote strike must be positive."
        )

    source_pairs = [
        (
            "bid",
            "bid_source",
        ),
        (
            "ask",
            "ask_source",
        ),
        (
            "last",
            "last_source",
        ),
        (
            "implied_volatility",
            "iv_source",
        ),
        (
            "delta",
            "delta_source",
        ),
        (
            "gamma",
            "gamma_source",
        ),
        (
            "theta",
            "theta_source",
        ),
        (
            "vega",
            "vega_source",
        ),
        (
            "volume",
            "volume_source",
        ),
        (
            "open_interest",
            "open_interest_source",
        ),
    ]

    for value_field, source_field in source_pairs:
        _validate_value_source_pair(
            quote.get(
                value_field
            ),
            quote[source_field],
            value_field,
        )


def create_market_snapshot(
    snapshot: dict[str, Any],
    quotes: list[dict[str, Any]],
    db_path=None,
    conn=None,
) -> int:
    """
    Store one normalized market snapshot and all its option quotes.

    The operation is atomic:
    either the snapshot and every quote are stored,
    or nothing is stored.
    """
    _validate_snapshot(
        snapshot
    )

    for quote in quotes:
        _validate_quote(
            quote
        )

    snapshot_data = {
        "captured_at":
            snapshot["captured_at"],

        "underlying":
            snapshot["underlying"],

        "provider":
            snapshot["provider"],

        "provider_snapshot_id":
            snapshot.get(
                "provider_snapshot_id"
            ),

        "research_run_id":
            snapshot.get(
                "research_run_id"
            ),

        "us_session_date":
            snapshot.get(
                "us_session_date"
            ),

        "us_session_state":
            snapshot.get(
                "us_session_state"
            ),

        "underlying_price":
            snapshot.get(
                "underlying_price"
            ),

        "underlying_source":
            snapshot["underlying_source"],

        "underlying_at":
            snapshot.get(
                "underlying_at"
            ),

        "fx_to_eur":
            snapshot.get(
                "fx_to_eur"
            ),

        "fx_source":
            snapshot["fx_source"],

        "fx_at":
            snapshot.get(
                "fx_at"
            ),

        "notes":
            snapshot.get(
                "notes"
            ),
    }

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:

        cursor = connection.execute(
            """
            INSERT INTO market_snapshots (
                captured_at,
                underlying,
                provider,
                provider_snapshot_id,
                research_run_id,
                us_session_date,
                us_session_state,
                underlying_price,
                underlying_source,
                underlying_at,
                fx_to_eur,
                fx_source,
                fx_at,
                notes
            )
            VALUES (
                :captured_at,
                :underlying,
                :provider,
                :provider_snapshot_id,
                :research_run_id,
                :us_session_date,
                :us_session_state,
                :underlying_price,
                :underlying_source,
                :underlying_at,
                :fx_to_eur,
                :fx_source,
                :fx_at,
                :notes
            );
            """,
            snapshot_data,
        )

        snapshot_id = cursor.lastrowid

        for quote in quotes:
            quote_data = {
                "snapshot_id":
                    snapshot_id,

                "provider_contract_id":
                    quote.get(
                        "provider_contract_id"
                    ),

                "option_symbol":
                    quote.get(
                        "option_symbol"
                    ),

                "right":
                    quote["right"],

                "strike":
                    quote["strike"],

                "expiration":
                    quote["expiration"],

                "quote_at":
                    quote.get(
                        "quote_at"
                    ),

                "bid":
                    quote.get(
                        "bid"
                    ),

                "bid_source":
                    quote["bid_source"],

                "bid_at":
                    quote.get(
                        "bid_at"
                    ),

                "ask":
                    quote.get(
                        "ask"
                    ),

                "ask_source":
                    quote["ask_source"],

                "ask_at":
                    quote.get(
                        "ask_at"
                    ),

                "last":
                    quote.get(
                        "last"
                    ),

                "last_source":
                    quote["last_source"],

                "last_at":
                    quote.get(
                        "last_at"
                    ),

                "implied_volatility":
                    quote.get(
                        "implied_volatility"
                    ),

                "iv_source":
                    quote["iv_source"],

                "iv_at":
                    quote.get(
                        "iv_at"
                    ),

                "delta":
                    quote.get(
                        "delta"
                    ),

                "delta_source":
                    quote["delta_source"],

                "delta_at":
                    quote.get(
                        "delta_at"
                    ),

                "gamma":
                    quote.get(
                        "gamma"
                    ),

                "gamma_source":
                    quote["gamma_source"],

                "gamma_at":
                    quote.get(
                        "gamma_at"
                    ),

                "theta":
                    quote.get(
                        "theta"
                    ),

                "theta_source":
                    quote["theta_source"],

                "theta_at":
                    quote.get(
                        "theta_at"
                    ),

                "vega":
                    quote.get(
                        "vega"
                    ),

                "vega_source":
                    quote["vega_source"],

                "vega_at":
                    quote.get(
                        "vega_at"
                    ),

                "volume":
                    quote.get(
                        "volume"
                    ),

                "volume_trading_date":
                    quote.get(
                        "volume_trading_date"
                    ),

                "volume_source":
                    quote["volume_source"],

                "volume_at":
                    quote.get(
                        "volume_at"
                    ),

                "open_interest":
                    quote.get(
                        "open_interest"
                    ),

                "open_interest_as_of_date":
                    quote.get(
                        "open_interest_as_of_date"
                    ),

                "open_interest_source":
                    quote[
                        "open_interest_source"
                    ],

                "open_interest_at":
                    quote.get(
                        "open_interest_at"
                    ),

                "shares_per_contract":
                    quote.get(
                        "shares_per_contract"
                    ),
            }

            connection.execute(
                """
                INSERT INTO option_quotes (
                    snapshot_id,
                    provider_contract_id,
                    option_symbol,
                    right,
                    strike,
                    expiration,
                    quote_at,

                    bid,
                    bid_source,
                    bid_at,

                    ask,
                    ask_source,
                    ask_at,

                    last,
                    last_source,
                    last_at,

                    implied_volatility,
                    iv_source,
                    iv_at,

                    delta,
                    delta_source,
                    delta_at,

                    gamma,
                    gamma_source,
                    gamma_at,

                    theta,
                    theta_source,
                    theta_at,

                    vega,
                    vega_source,
                    vega_at,

                    volume,
                    volume_trading_date,
                    volume_source,
                    volume_at,

                    open_interest,
                    open_interest_as_of_date,
                    open_interest_source,
                    open_interest_at,

                    shares_per_contract
                )
                VALUES (
                    :snapshot_id,
                    :provider_contract_id,
                    :option_symbol,
                    :right,
                    :strike,
                    :expiration,
                    :quote_at,

                    :bid,
                    :bid_source,
                    :bid_at,

                    :ask,
                    :ask_source,
                    :ask_at,

                    :last,
                    :last_source,
                    :last_at,

                    :implied_volatility,
                    :iv_source,
                    :iv_at,

                    :delta,
                    :delta_source,
                    :delta_at,

                    :gamma,
                    :gamma_source,
                    :gamma_at,

                    :theta,
                    :theta_source,
                    :theta_at,

                    :vega,
                    :vega_source,
                    :vega_at,

                    :volume,
                    :volume_trading_date,
                    :volume_source,
                    :volume_at,

                    :open_interest,
                    :open_interest_as_of_date,
                    :open_interest_source,
                    :open_interest_at,

                    :shares_per_contract
                );
                """,
                quote_data,
            )

        return snapshot_id


def get_market_snapshot(
    snapshot_id: int,
    db_path=None,
    conn=None,
) -> dict[str, Any] | None:
    own_connection = conn is None

    connection = (
        conn
        or get_connection(db_path)
    )

    try:
        snapshot_row = connection.execute(
            """
            SELECT *
            FROM market_snapshots
            WHERE id = ?;
            """,
            (snapshot_id,),
        ).fetchone()

        if snapshot_row is None:
            return None

        quote_rows = connection.execute(
            """
            SELECT *
            FROM option_quotes
            WHERE snapshot_id = ?
            ORDER BY
                expiration,
                strike,
                right,
                id;
            """,
            (snapshot_id,),
        ).fetchall()

        return {
            "snapshot":
                dict(snapshot_row),

            "quotes":
                [
                    dict(row)
                    for row in quote_rows
                ],
        }

    finally:
        if own_connection:
            connection.close()


def create_candidate(
    candidate: dict[str, Any],
    legs: list[dict[str, Any]],
    controls: list[dict[str, Any]] | None = None,
    db_path=None,
    conn=None,
) -> int:
    """
    Create one frozen candidate definition, its legs,
    and its matched controls atomically.
    """
    controls = controls or []

    _require_fields(
        candidate,
        [
            "created_at",
            "snapshot_id",
            "underlying",
            "candidate_source",
            "candidate_class",
            "scanner_version",
            "rule_set_version",
            "rule_id",
            "outcome_definition_version",
            "rationale",
        ],
        "candidate",
    )

    if not legs:
        raise ValueError(
            "A candidate requires at least one leg."
        )

    candidate_data = {
        "created_at":
            candidate["created_at"],

        "snapshot_id":
            candidate["snapshot_id"],

        "underlying":
            candidate["underlying"],

        "candidate_source":
            candidate["candidate_source"],

        "candidate_class":
            candidate["candidate_class"],

        "scanner_version":
            candidate["scanner_version"],

        "rule_set_version":
            candidate["rule_set_version"],

        "rule_id":
            candidate["rule_id"],

        "outcome_definition_version":
            candidate[
                "outcome_definition_version"
            ],

        "rationale":
            candidate["rationale"],

        "model_probability_profit":
            candidate.get(
                "model_probability_profit"
            ),

        "model_expected_value_minor":
            candidate.get(
                "model_expected_value_minor"
            ),

        "model_max_loss_minor":
            candidate.get(
                "model_max_loss_minor"
            ),

        "model_confidence":
            candidate.get(
                "model_confidence"
            ),

        "status":
            candidate.get(
                "status",
                "TRACKING",
            ),
    }

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:

        cursor = connection.execute(
            """
            INSERT INTO candidates (
                created_at,
                snapshot_id,
                underlying,
                candidate_source,
                candidate_class,
                scanner_version,
                rule_set_version,
                rule_id,
                outcome_definition_version,
                rationale,
                model_probability_profit,
                model_expected_value_minor,
                model_max_loss_minor,
                model_confidence,
                status
            )
            VALUES (
                :created_at,
                :snapshot_id,
                :underlying,
                :candidate_source,
                :candidate_class,
                :scanner_version,
                :rule_set_version,
                :rule_id,
                :outcome_definition_version,
                :rationale,
                :model_probability_profit,
                :model_expected_value_minor,
                :model_max_loss_minor,
                :model_confidence,
                :status
            );
            """,
            candidate_data,
        )

        candidate_id = cursor.lastrowid

        for leg in legs:
            _require_fields(
                leg,
                [
                    "leg_no",
                    "option_quote_id",
                    "direction",
                ],
                "candidate leg",
            )

            connection.execute(
                """
                INSERT INTO candidate_legs (
                    candidate_id,
                    leg_no,
                    option_quote_id,
                    direction,
                    contracts
                )
                VALUES (?, ?, ?, ?, ?);
                """,
                (
                    candidate_id,
                    leg["leg_no"],
                    leg["option_quote_id"],
                    leg["direction"],
                    leg.get(
                        "contracts",
                        1,
                    ),
                ),
            )

        for control in controls:
            _require_fields(
                control,
                [
                    "control_quote_id",
                    "matching_version",
                    "match_rank",
                    "created_at",
                ],
                "candidate control",
            )

            connection.execute(
                """
                INSERT INTO candidate_controls (
                    candidate_id,
                    control_quote_id,
                    matching_version,
                    match_rank,
                    match_distance,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    candidate_id,
                    control["control_quote_id"],
                    control["matching_version"],
                    control["match_rank"],
                    control.get(
                        "match_distance"
                    ),
                    control["created_at"],
                ),
            )

        return candidate_id


def get_candidate(
    candidate_id: int,
    db_path=None,
    conn=None,
) -> dict[str, Any] | None:
    own_connection = conn is None

    connection = (
        conn
        or get_connection(db_path)
    )

    try:
        candidate_row = connection.execute(
            """
            SELECT *
            FROM candidates
            WHERE id = ?;
            """,
            (candidate_id,),
        ).fetchone()

        if candidate_row is None:
            return None

        leg_rows = connection.execute(
            """
            SELECT
                cl.*,
                oq.option_symbol,
                oq.provider_contract_id,
                oq.right,
                oq.strike,
                oq.expiration,
                oq.bid,
                oq.ask,
                oq.implied_volatility,
                oq.delta
            FROM candidate_legs AS cl
            JOIN option_quotes AS oq
              ON oq.id = cl.option_quote_id
            WHERE cl.candidate_id = ?
            ORDER BY cl.leg_no;
            """,
            (candidate_id,),
        ).fetchall()

        control_rows = connection.execute(
            """
            SELECT
                cc.*,
                oq.option_symbol,
                oq.provider_contract_id,
                oq.right,
                oq.strike,
                oq.expiration,
                oq.bid,
                oq.ask,
                oq.implied_volatility,
                oq.delta
            FROM candidate_controls AS cc
            JOIN option_quotes AS oq
              ON oq.id = cc.control_quote_id
            WHERE cc.candidate_id = ?
            ORDER BY cc.match_rank, cc.id;
            """,
            (candidate_id,),
        ).fetchall()

        return {
            "candidate":
                dict(candidate_row),

            "legs":
                [
                    dict(row)
                    for row in leg_rows
                ],

            "controls":
                [
                    dict(row)
                    for row in control_rows
                ],
        }

    finally:
        if own_connection:
            connection.close()


def set_candidate_status(
    candidate_id: int,
    status: str,
    db_path=None,
    conn=None,
) -> None:
    """
    Change only the candidate lifecycle status.

    The candidate's original research definition remains immutable.
    """
    if status not in CANDIDATE_STATUSES:
        raise ValueError(
            f"Invalid candidate status: {status}"
        )

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:

        row = connection.execute(
            """
            SELECT id
            FROM candidates
            WHERE id = ?;
            """,
            (candidate_id,),
        ).fetchone()

        if row is None:
            raise ValueError(
                f"Candidate {candidate_id} does not exist."
            )

        connection.execute(
            """
            UPDATE candidates
            SET status = ?
            WHERE id = ?;
            """,
            (
                status,
                candidate_id,
            ),
        )
# =====================================================================
# CHRISTIANIA SHADOW / REFERENCE PERSISTENCE LAYER — SCHEMA V8
# =====================================================================


SHADOW_STATES = {
    "SURFACED",
    "INVESTIGATED",
    "DECIDED",
    "SHADOW_TRACKED",
    "CLOSED_OR_EXPIRED",
    "SCORED",
    "REJECTED",
}

SHADOW_OUTCOME_HORIZONS = {
    "NEXT_ELIGIBLE_SESSION",
    "PLUS_3_SESSIONS",
    "PLUS_5_SESSIONS",
    "TERMINAL_EXPIRY",
    "MFE",
    "MAE",
}

OBSERVATION_STATES = {
    "PRESENT",
    "ABSENT",
    "INVALID",
    "DUPLICATE",
    "ERROR",
}

UNIVERSE_STATUSES = {
    "CONSISTENT",
    "DISAGREEMENT_RECORDED",
    "UNUSABLE",
}



_LISTING_REFERENCE_INSERT_SQL = """
INSERT INTO listing_reference_contracts (
    research_run_id,
    provider,
    underlying,
    provider_contract_id,
    option_symbol,
    expiration,
    strike,
    right,
    exercise_style,
    shares_per_contract,
    primary_exchange,
    additional_underlyings_json,
    observed_at,
    ingested_at
)
VALUES (
    :research_run_id,
    :provider,
    :underlying,
    :provider_contract_id,
    :option_symbol,
    :expiration,
    :strike,
    :right,
    :exercise_style,
    :shares_per_contract,
    :primary_exchange,
    :additional_underlyings_json,
    :observed_at,
    :ingested_at
);
"""


def _normalize_listing_reference_contract(
    contract: dict[str, Any],
) -> dict[str, Any]:
    _require_fields(
        contract,
        [
            "research_run_id",
            "provider",
            "underlying",
            "provider_contract_id",
            "expiration",
            "strike",
            "right",
            "observed_at",
        ],
        "listing reference contract",
    )

    if contract["right"] not in {"C", "P"}:
        raise ValueError(
            "Listing reference contract right must be C or P."
        )

    shares_per_contract = contract.get(
        "shares_per_contract"
    )
    if (
        shares_per_contract is not None
        and shares_per_contract <= 0
    ):
        raise ValueError(
            "shares_per_contract must be positive when present."
        )

    return {
        "research_run_id":
            contract["research_run_id"],
        "provider":
            contract["provider"],
        "underlying":
            contract["underlying"],
        "provider_contract_id":
            contract["provider_contract_id"],
        "option_symbol":
            contract.get("option_symbol"),
        "expiration":
            contract["expiration"],
        "strike":
            contract["strike"],
        "right":
            contract["right"],
        "exercise_style":
            contract.get("exercise_style"),
        "shares_per_contract":
            shares_per_contract,
        "primary_exchange":
            contract.get("primary_exchange"),
        "additional_underlyings_json":
            contract.get(
                "additional_underlyings_json"
            ),
        "observed_at":
            contract["observed_at"],
        "ingested_at":
            contract.get(
                "ingested_at",
                contract["observed_at"],
            ),
    }


def create_listing_reference_contracts(
    contracts: list[dict[str, Any]],
    *,
    db_path=None,
    conn=None,
) -> dict[tuple[int, str, str], int]:
    """
    Batch-insert listing-reference contracts with one transaction.

    Returns IDs keyed by:
    (research_run_id, provider, provider_contract_id).
    """

    if not contracts:
        return {}

    normalized = [
        _normalize_listing_reference_contract(contract)
        for contract in contracts
    ]

    requested_keys = {
        (
            int(row["research_run_id"]),
            str(row["provider"]),
            str(row["provider_contract_id"]),
        )
        for row in normalized
    }

    if len(requested_keys) != len(normalized):
        raise ValueError(
            "Duplicate listing-reference identity inside batch."
        )

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:
        connection.executemany(
            _LISTING_REFERENCE_INSERT_SQL,
            normalized,
        )

        result: dict[
            tuple[int, str, str],
            int,
        ] = {}

        groups: dict[
            tuple[int, str],
            set[str],
        ] = {}

        for run_id, provider, provider_contract_id in requested_keys:
            groups.setdefault(
                (run_id, provider),
                set(),
            ).add(provider_contract_id)

        for (run_id, provider), provider_ids in groups.items():
            rows = connection.execute(
                """
                SELECT
                    id,
                    research_run_id,
                    provider,
                    provider_contract_id
                FROM listing_reference_contracts
                WHERE research_run_id = ?
                  AND provider = ?;
                """,
                (run_id, provider),
            ).fetchall()

            for row in rows:
                key = (
                    int(row["research_run_id"]),
                    str(row["provider"]),
                    str(row["provider_contract_id"]),
                )
                if key[2] in provider_ids:
                    result[key] = int(row["id"])

        if set(result) != requested_keys:
            missing = requested_keys - set(result)
            raise RuntimeError(
                "Batch insert completed but not every inserted "
                f"reference identity could be reloaded: {sorted(missing)}"
            )

        return result


_PROVIDER_OBSERVATION_INSERT_SQL = """
INSERT INTO provider_observation_availability (
    reference_contract_id,
    provider,
    evidence_family,
    state,
    provider_observation_id,
    reason_code,
    reason_detail,
    observed_at,
    raw_timestamp,
    ingested_at
)
VALUES (
    :reference_contract_id,
    :provider,
    :evidence_family,
    :state,
    :provider_observation_id,
    :reason_code,
    :reason_detail,
    :observed_at,
    :raw_timestamp,
    :ingested_at
);
"""


def _normalize_provider_observation(
    observation: dict[str, Any],
) -> dict[str, Any]:
    _require_fields(
        observation,
        [
            "reference_contract_id",
            "provider",
            "evidence_family",
            "state",
            "observed_at",
        ],
        "provider observation",
    )

    if observation["state"] not in OBSERVATION_STATES:
        raise ValueError(
            f"Invalid observation state: {observation['state']}"
        )

    return {
        "reference_contract_id":
            observation["reference_contract_id"],
        "provider":
            observation["provider"],
        "evidence_family":
            observation["evidence_family"],
        "state":
            observation["state"],
        "provider_observation_id":
            observation.get(
                "provider_observation_id"
            ),
        "reason_code":
            observation.get("reason_code"),
        "reason_detail":
            observation.get("reason_detail"),
        "observed_at":
            observation["observed_at"],
        "raw_timestamp":
            observation.get("raw_timestamp"),
        "ingested_at":
            observation.get(
                "ingested_at",
                observation["observed_at"],
            ),
    }


def record_provider_observation_availabilities(
    observations: list[dict[str, Any]],
    *,
    db_path=None,
    conn=None,
) -> int:
    """
    Batch-insert provider observation-availability rows.
    """

    if not observations:
        return 0

    normalized = [
        _normalize_provider_observation(observation)
        for observation in observations
    ]

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:
        connection.executemany(
            _PROVIDER_OBSERVATION_INSERT_SQL,
            normalized,
        )

    return len(normalized)


def create_listing_reference_contract(
    contract: dict[str, Any],
    *,
    db_path=None,
    conn=None,
) -> int:
    normalized = _normalize_listing_reference_contract(
        contract
    )

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:
        cursor = connection.execute(
            _LISTING_REFERENCE_INSERT_SQL,
            normalized,
        )
        return int(cursor.lastrowid)


def record_provider_observation_availability(
    observation: dict[str, Any],
    *,
    db_path=None,
    conn=None,
) -> int:
    normalized = _normalize_provider_observation(
        observation
    )

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:
        cursor = connection.execute(
            _PROVIDER_OBSERVATION_INSERT_SQL,
            normalized,
        )
        return int(cursor.lastrowid)


def record_unmatched_provider_contract_observation(
    observation: dict[str, Any],
    *,
    db_path=None,
    conn=None,
) -> int:
    _require_fields(
        observation,
        [
            "research_run_id",
            "provider",
            "evidence_family",
            "anomaly_type",
            "underlying",
            "observed_at",
        ],
        "unmatched provider contract observation",
    )

    allowed = {
        "SNAPSHOT_ONLY",
        "THETA_QUOTE_ONLY",
        "THETA_GREEK_ONLY",
        "SAXO_REFERENCE_ONLY",
        "PROVIDER_ONLY",
    }
    if observation["anomaly_type"] not in allowed:
        raise ValueError(
            f"Invalid unmatched anomaly type: {observation['anomaly_type']}"
        )

    provider_contract_id = observation.get("provider_contract_id")
    expiration = observation.get("expiration")
    strike = observation.get("strike")
    right = observation.get("right")

    if not provider_contract_id and not (
        expiration is not None
        and strike is not None
        and right is not None
    ):
        raise ValueError(
            "Unmatched provider evidence requires either a provider_contract_id "
            "or expiration/strike/right."
        )

    if right is not None and right not in {"C", "P"}:
        raise ValueError(
            "Unmatched provider option right must be C or P."
        )

    with transaction(db_path=db_path, conn=conn) as connection:
        cursor = connection.execute(
            """
            INSERT INTO unmatched_provider_contract_observations (
                research_run_id,
                provider,
                evidence_family,
                anomaly_type,
                underlying,
                provider_contract_id,
                expiration,
                strike,
                right,
                reason_code,
                observed_at,
                raw_timestamp,
                raw_payload_json,
                ingested_at
            )
            VALUES (
                :research_run_id,
                :provider,
                :evidence_family,
                :anomaly_type,
                :underlying,
                :provider_contract_id,
                :expiration,
                :strike,
                :right,
                :reason_code,
                :observed_at,
                :raw_timestamp,
                :raw_payload_json,
                :ingested_at
            );
            """,
            {
                "research_run_id": observation["research_run_id"],
                "provider": observation["provider"],
                "evidence_family": observation["evidence_family"],
                "anomaly_type": observation["anomaly_type"],
                "underlying": observation["underlying"],
                "provider_contract_id": provider_contract_id,
                "expiration": expiration,
                "strike": strike,
                "right": right,
                "reason_code": observation.get("reason_code"),
                "observed_at": observation["observed_at"],
                "raw_timestamp": observation.get("raw_timestamp"),
                "raw_payload_json": observation.get("raw_payload_json"),
                "ingested_at": observation.get(
                    "ingested_at",
                    observation["observed_at"],
                ),
            },
        )
        return int(cursor.lastrowid)


def create_shadow_candidate(
    candidate: dict[str, Any],
    *,
    db_path=None,
    conn=None,
) -> int:
    _require_fields(
        candidate,
        [
            "research_run_id",
            "reference_contract_id",
            "underlying",
            "scanner_family_id",
            "scanner_version",
            "scanner_rule_version",
            "surfaced_at",
            "structure_id",
            "structure_version",
            "hypothesis_family",
            "hypothesis_version",
            "sizing_policy_version",
            "max_theoretical_loss_minor",
            "universe_status",
        ],
        "shadow candidate",
    )

    if candidate["universe_status"] not in UNIVERSE_STATUSES:
        raise ValueError(
            f"Invalid universe status: {candidate['universe_status']}"
        )

    if candidate["max_theoretical_loss_minor"] < 0:
        raise ValueError(
            "max_theoretical_loss_minor cannot be negative."
        )

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:
        cursor = connection.execute(
            """
            INSERT INTO shadow_candidates (
                research_run_id,
                reference_contract_id,
                underlying,
                scanner_family_id,
                scanner_version,
                scanner_rule_version,
                surfaced_at,
                entry_quote_observation_id,
                entry_greek_observation_id,
                quote_freshness_class,
                greek_quality_class,
                universe_status,
                structure_id,
                structure_version,
                structure_json,
                hypothesis_family,
                hypothesis_version,
                sizing_policy_version,
                max_theoretical_loss_minor,
                cost_model_version,
                cost_provenance,
                admission_label
            )
            VALUES (
                :research_run_id,
                :reference_contract_id,
                :underlying,
                :scanner_family_id,
                :scanner_version,
                :scanner_rule_version,
                :surfaced_at,
                :entry_quote_observation_id,
                :entry_greek_observation_id,
                :quote_freshness_class,
                :greek_quality_class,
                :universe_status,
                :structure_id,
                :structure_version,
                :structure_json,
                :hypothesis_family,
                :hypothesis_version,
                :sizing_policy_version,
                :max_theoretical_loss_minor,
                :cost_model_version,
                :cost_provenance,
                'CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING'
            );
            """,
            {
                **candidate,
                "entry_quote_observation_id":
                    candidate.get(
                        "entry_quote_observation_id"
                    ),
                "entry_greek_observation_id":
                    candidate.get(
                        "entry_greek_observation_id"
                    ),
                "quote_freshness_class":
                    candidate.get(
                        "quote_freshness_class"
                    ),
                "greek_quality_class":
                    candidate.get(
                        "greek_quality_class"
                    ),
                "structure_json":
                    candidate.get("structure_json"),
                "cost_model_version":
                    candidate.get(
                        "cost_model_version"
                    ),
                "cost_provenance":
                    candidate.get("cost_provenance"),
            },
        )
        candidate_id = int(cursor.lastrowid)

        connection.execute(
            """
            INSERT INTO shadow_state_events (
                candidate_id,
                from_state,
                to_state,
                occurred_at,
                actor,
                reason_code,
                note
            )
            VALUES (?, NULL, 'SURFACED', ?, ?, ?, ?);
            """,
            (
                candidate_id,
                candidate["surfaced_at"],
                candidate.get(
                    "actor",
                    "SYSTEM",
                ),
                candidate.get(
                    "reason_code",
                    "SCANNER_SURFACED",
                ),
                candidate.get("note"),
            ),
        )

        return candidate_id


def append_shadow_state_event(
    candidate_id: int,
    *,
    to_state: str,
    occurred_at: str,
    actor: str,
    reason_code: str | None = None,
    note: str | None = None,
    db_path=None,
    conn=None,
) -> int:
    if to_state not in SHADOW_STATES:
        raise ValueError(
            f"Invalid shadow state: {to_state}"
        )

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:
        row = connection.execute(
            """
            SELECT to_state
            FROM shadow_state_events
            WHERE candidate_id = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (candidate_id,),
        ).fetchone()

        if row is None:
            raise ValueError(
                f"Shadow candidate {candidate_id} has no lifecycle state."
            )

        cursor = connection.execute(
            """
            INSERT INTO shadow_state_events (
                candidate_id,
                from_state,
                to_state,
                occurred_at,
                actor,
                reason_code,
                note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                candidate_id,
                row["to_state"],
                to_state,
                occurred_at,
                actor,
                reason_code,
                note,
            ),
        )
        return int(cursor.lastrowid)


def append_shadow_outcome_observation(
    observation: dict[str, Any],
    *,
    db_path=None,
    conn=None,
) -> int:
    _require_fields(
        observation,
        [
            "candidate_id",
            "horizon",
            "provider",
            "observed_at",
        ],
        "shadow outcome observation",
    )

    if observation["horizon"] not in SHADOW_OUTCOME_HORIZONS:
        raise ValueError(
            f"Invalid shadow outcome horizon: {observation['horizon']}"
        )

    bid = observation.get("bid")
    ask = observation.get("ask")
    if (
        bid is not None
        and ask is not None
        and ask < bid
    ):
        raise ValueError(
            "Shadow outcome ask cannot be below bid."
        )

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:
        cursor = connection.execute(
            """
            INSERT INTO shadow_outcome_observations (
                candidate_id,
                horizon,
                provider,
                observed_at,
                raw_timestamp,
                bid,
                ask,
                mid,
                underlying_price,
                pnl_minor,
                return_fraction,
                quality_state,
                evidence_json
            )
            VALUES (
                :candidate_id,
                :horizon,
                :provider,
                :observed_at,
                :raw_timestamp,
                :bid,
                :ask,
                :mid,
                :underlying_price,
                :pnl_minor,
                :return_fraction,
                :quality_state,
                :evidence_json
            );
            """,
            {
                **observation,
                "raw_timestamp":
                    observation.get("raw_timestamp"),
                "bid":
                    bid,
                "ask":
                    ask,
                "mid":
                    observation.get("mid"),
                "underlying_price":
                    observation.get(
                        "underlying_price"
                    ),
                "pnl_minor":
                    observation.get("pnl_minor"),
                "return_fraction":
                    observation.get(
                        "return_fraction"
                    ),
                "quality_state":
                    observation.get("quality_state"),
                "evidence_json":
                    observation.get("evidence_json"),
            },
        )
        return int(cursor.lastrowid)


def append_underlying_pin_event(
    *,
    underlying: str,
    candidate_id: int,
    action: str,
    occurred_at: str,
    reason: str,
    db_path=None,
    conn=None,
) -> int:
    if action not in {"PIN", "UNPIN"}:
        raise ValueError(
            "Pin action must be PIN or UNPIN."
        )

    with transaction(
        db_path=db_path,
        conn=conn,
    ) as connection:
        cursor = connection.execute(
            """
            INSERT INTO underlying_pin_events (
                underlying,
                candidate_id,
                action,
                occurred_at,
                reason
            )
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                underlying,
                candidate_id,
                action,
                occurred_at,
                reason,
            ),
        )
        return int(cursor.lastrowid)


def get_shadow_candidate(
    candidate_id: int,
    *,
    db_path=None,
    conn=None,
) -> dict[str, Any] | None:
    own_connection = conn is None
    connection = conn or get_connection(db_path)

    try:
        candidate = connection.execute(
            """
            SELECT *
            FROM shadow_candidates
            WHERE id = ?;
            """,
            (candidate_id,),
        ).fetchone()

        if candidate is None:
            return None

        state_events = connection.execute(
            """
            SELECT *
            FROM shadow_state_events
            WHERE candidate_id = ?
            ORDER BY id;
            """,
            (candidate_id,),
        ).fetchall()

        outcomes = connection.execute(
            """
            SELECT *
            FROM shadow_outcome_observations
            WHERE candidate_id = ?
            ORDER BY id;
            """,
            (candidate_id,),
        ).fetchall()

        pins = connection.execute(
            """
            SELECT *
            FROM underlying_pin_events
            WHERE candidate_id = ?
            ORDER BY id;
            """,
            (candidate_id,),
        ).fetchall()

        return {
            "candidate": dict(candidate),
            "state_events": [
                dict(row)
                for row in state_events
            ],
            "outcomes": [
                dict(row)
                for row in outcomes
            ],
            "pin_events": [
                dict(row)
                for row in pins
            ],
        }

    finally:
        if own_connection:
            connection.close()

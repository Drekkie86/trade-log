from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from src.database.repository import (
    create_trade,
    to_minor,
)


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def date_to_iso(
    value: date | str | None,
) -> str | None:
    if value is None:
        return None

    if isinstance(value, date):
        return value.isoformat()

    return str(value)


def probability_to_decimal(
    percentage: float | int,
) -> float:
    value = float(percentage)

    if value < 0 or value > 100:
        raise ValueError(
            "Probability must be between 0 and 100."
        )

    return value / 100.0


def validate_text(
    value: str,
    field_name: str,
) -> str:
    cleaned = value.strip()

    if not cleaned:
        raise ValueError(
            f"{field_name} cannot be blank."
        )

    return cleaned


def validate_leg(
    leg: dict[str, Any],
) -> None:
    if leg["right"] not in {
        "C",
        "P",
    }:
        raise ValueError(
            "Option right must be C or P."
        )

    if leg["direction"] not in {
        "BUY",
        "SELL",
    }:
        raise ValueError(
            "Direction must be BUY or SELL."
        )

    if float(leg["strike"]) <= 0:
        raise ValueError(
            "Strike must be positive."
        )

    if int(leg["contracts"]) <= 0:
        raise ValueError(
            "Contracts must be positive."
        )

    multiplier = int(
        leg.get(
            "multiplier",
            100,
        )
    )

    if multiplier <= 0:
        raise ValueError(
            "Multiplier must be positive."
        )

    bid = float(
        leg["entry_bid"]
    )

    ask = float(
        leg["entry_ask"]
    )

    fill = float(
        leg["entry_fill"]
    )

    if bid < 0:
        raise ValueError(
            "Option bid cannot be negative."
        )

    if ask < 0:
        raise ValueError(
            "Option ask cannot be negative."
        )

    if fill < 0:
        raise ValueError(
            "Option fill cannot be negative."
        )

    if ask < bid:
        raise ValueError(
            "Option ask cannot be below bid."
        )

    entry_iv = leg.get(
        "entry_iv"
    )

    if (
        entry_iv is not None
        and float(entry_iv) < 0
    ):
        raise ValueError(
            "Entry IV cannot be negative."
        )

    entry_delta = leg.get(
        "entry_delta"
    )

    if (
        entry_delta is not None
        and not (
            -1.0
            <= float(entry_delta)
            <= 1.0
        )
    ):
        raise ValueError(
            "Entry delta must be between -1 and 1."
        )


def calculate_entry_cash(
    legs: list[dict[str, Any]],
) -> float:
    """
    Calculate gross trade cash flow from all option legs.

    BUY  -> negative cash flow
    SELL -> positive cash flow

    Decimal is used internally to avoid accumulating
    binary floating-point errors across multiple legs.
    """
    if not legs:
        raise ValueError(
            "At least one trade leg is required."
        )

    total = Decimal("0")

    for leg in legs:
        validate_leg(leg)

        fill = Decimal(
            str(
                leg["entry_fill"]
            )
        )

        contracts = Decimal(
            str(
                int(
                    leg["contracts"]
                )
            )
        )

        multiplier = Decimal(
            str(
                int(
                    leg.get(
                        "multiplier",
                        100,
                    )
                )
            )
        )

        amount = (
            fill
            * contracts
            * multiplier
        )

        if leg["direction"] == "BUY":
            total -= amount
        else:
            total += amount

    return float(total)


def record_trade(
    *,
    underlying: str,
    currency: str,
    is_paper: bool,
    strategy: str,

    thesis: str,
    prediction: str,
    horizon_date: date | str,

    p_thesis_initial_percent: float,
    p_thesis_percent: float,
    p_profit_percent: float,

    invalidation: str,

    entry_at: str,
    entry_underlying: float,
    entry_fx_rate: float,

    entry_fees_major: float,

    entry_iv_rank: float | None,
    next_earnings_date: date | str | None,

    max_loss_major: float,
    profit_target: str,
    stop_condition: str,

    legs: list[dict[str, Any]],

    created_at: str | None = None,
    db_path=None,
) -> int:
    """
    Convert human-facing values into database values
    and record the trade.

    Important:
    entry_cash is derived from the option legs.
    The UI does not supply it.
    """

    underlying_clean = validate_text(
        underlying,
        "Underlying",
    ).upper()

    currency_clean = validate_text(
        currency,
        "Currency",
    ).upper()

    strategy_clean = validate_text(
        strategy,
        "Strategy",
    ).upper()

    thesis_clean = validate_text(
        thesis,
        "Thesis",
    )

    prediction_clean = validate_text(
        prediction,
        "Prediction",
    )

    invalidation_clean = validate_text(
        invalidation,
        "Invalidation",
    )

    profit_target_clean = validate_text(
        profit_target,
        "Profit target",
    )

    stop_condition_clean = validate_text(
        stop_condition,
        "Stop condition",
    )

    if entry_underlying <= 0:
        raise ValueError(
            "Entry underlying price must be positive."
        )

    if entry_fx_rate <= 0:
        raise ValueError(
            "Entry FX rate must be positive."
        )

    if entry_fees_major < 0:
        raise ValueError(
            "Entry fees cannot be negative."
        )

    if max_loss_major < 0:
        raise ValueError(
            "Maximum loss cannot be negative."
        )

    if (
        entry_iv_rank is not None
        and not (
            0
            <= float(entry_iv_rank)
            <= 100
        )
    ):
        raise ValueError(
            "IV rank must be between 0 and 100."
        )

    if not legs:
        raise ValueError(
            "A taken trade must contain at least one leg."
        )

    for leg in legs:
        validate_leg(leg)

    entry_cash_major = calculate_entry_cash(
        legs
    )

    trade = {
        "created_at":
            created_at or utc_now_iso(),

        "underlying":
            underlying_clean,

        "currency":
            currency_clean,

        "is_paper":
            int(is_paper),

        "status":
            "OPEN",

        "parent_trade_id":
            None,

        "strategy":
            strategy_clean,

        "entry_at":
            entry_at,

        "entry_underlying":
            float(entry_underlying),

        "entry_fx_rate":
            float(entry_fx_rate),

        "entry_fees":
            to_minor(
                entry_fees_major
            ),

        "entry_cash":
            to_minor(
                entry_cash_major
            ),

        "entry_iv_rank":
            (
                None
                if entry_iv_rank is None
                else float(entry_iv_rank)
            ),

        "next_earnings_date":
            date_to_iso(
                next_earnings_date
            ),

        "thesis":
            thesis_clean,

        "prediction":
            prediction_clean,

        "horizon_date":
            date_to_iso(
                horizon_date
            ),

        "p_thesis_initial":
            probability_to_decimal(
                p_thesis_initial_percent
            ),

        "p_thesis":
            probability_to_decimal(
                p_thesis_percent
            ),

        "p_profit":
            probability_to_decimal(
                p_profit_percent
            ),

        "invalidation":
            invalidation_clean,

        "max_loss":
            to_minor(
                max_loss_major
            ),

        "profit_target":
            profit_target_clean,

        "stop_condition":
            stop_condition_clean,

        "rejection_reason":
            None,
    }

    return create_trade(
        trade,
        legs,
        db_path=db_path,
    )
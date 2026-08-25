from datetime import date, datetime, timezone
from typing import Any

from src.database.repository import (
    create_trade,
    to_minor,
)


def utc_now_iso() -> str:
    """
    Return the current UTC timestamp in the format used by the database.

    Example:
        2026-08-26T10:15:32Z
    """
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def date_to_iso(value: date | str) -> str:
    """
    Convert a date into YYYY-MM-DD.
    """
    if isinstance(value, date):
        return value.isoformat()

    return str(value)


def probability_to_decimal(
    percentage: float | int,
) -> float:
    """
    Convert a human percentage into database probability form.

    Example:
        65 -> 0.65
    """
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
    """
    Require meaningful non-empty text.
    """
    cleaned = value.strip()

    if not cleaned:
        raise ValueError(
            f"{field_name} cannot be blank."
        )

    return cleaned


def record_trade(
    *,
    underlying: str,
    currency: str,
    is_paper: bool,
    strategy: str,

    thesis: str,
    prediction: str,
    horizon_date: date | str,
    p_thesis_percent: float,
    p_profit_percent: float,
    invalidation: str,

    entry_at: str,
    entry_underlying: float,
    entry_fx_rate: float,

    entry_fees_major: float,
    entry_cash_major: float,

    max_loss_major: float,
    profit_target: str,
    stop_condition: str,

    legs: list[dict[str, Any]],

    created_at: str | None = None,
    db_path=None,
) -> int:
    """
    Record a taken trade.

    The UI works in human-friendly values:
    - probabilities as percentages
    - money in major currency units

    This service converts those values into the database representation.
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

    if max_loss_major < 0:
        raise ValueError(
            "Maximum loss cannot be negative."
        )

    if not legs:
        raise ValueError(
            "A taken trade must contain at least one leg."
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

        "thesis":
            thesis_clean,

        "prediction":
            prediction_clean,

        "horizon_date":
            date_to_iso(
                horizon_date
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
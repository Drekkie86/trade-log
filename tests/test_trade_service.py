from datetime import date

import pytest

from src.database.repository import get_trade
from src.services.trade_service import (
    date_to_iso,
    probability_to_decimal,
    record_trade,
    validate_text,
)


def test_probability_to_decimal():
    assert probability_to_decimal(65) == 0.65
    assert probability_to_decimal(0) == 0.0
    assert probability_to_decimal(100) == 1.0


def test_probability_rejects_out_of_range():
    with pytest.raises(ValueError):
        probability_to_decimal(-1)

    with pytest.raises(ValueError):
        probability_to_decimal(101)


def test_date_to_iso():
    assert (
        date_to_iso(date(2026, 9, 30))
        == "2026-09-30"
    )

    assert (
        date_to_iso("2026-09-30")
        == "2026-09-30"
    )


def test_validate_text_strips_whitespace():
    assert (
        validate_text(
            "  META  ",
            "Underlying",
        )
        == "META"
    )


def test_validate_text_rejects_blank():
    with pytest.raises(
        ValueError,
        match="cannot be blank",
    ):
        validate_text(
            "   ",
            "Thesis",
        )


def test_record_trade_round_trip(
    db_path,
):
    legs = [
        {
            "leg_no": 1,
            "right": "C",
            "direction": "BUY",
            "strike": 105.0,
            "expiration": "2026-09-30",
            "contracts": 1,
            "multiplier": 100,
            "entry_bid": 2.10,
            "entry_ask": 2.30,
            "entry_fill": 2.20,
        }
    ]

    trade_id = record_trade(
        underlying="meta",
        currency="usd",
        is_paper=True,
        strategy="long_call",

        thesis=
            "META is likely to rise.",

        prediction=
            "META trades above 105 "
            "before the horizon.",

        horizon_date=
            date(2026, 9, 30),

        p_thesis_percent=
            65,

        p_profit_percent=
            52,

        invalidation=
            "META closes below 90.",

        entry_at=
            "2026-08-26T12:00:00Z",

        entry_underlying=
            100.0,

        entry_fx_rate=
            0.86,

        entry_fees_major=
            1.00,

        entry_cash_major=
            -220.00,

        max_loss_major=
            220.00,

        profit_target=
            "Close at 50% gain.",

        stop_condition=
            "Exit if thesis is invalidated.",

        legs=
            legs,

        created_at=
            "2026-08-26T12:05:00Z",

        db_path=
            db_path,
    )

    result = get_trade(
        trade_id,
        db_path=db_path,
    )

    trade = result["trade"]

    assert trade["underlying"] == "META"
    assert trade["currency"] == "USD"
    assert trade["strategy"] == "LONG_CALL"

    assert trade["is_paper"] == 1

    assert trade["p_thesis"] == 0.65
    assert trade["p_profit"] == 0.52

    assert trade["entry_fees"] == 100
    assert trade["entry_cash"] == -22000
    assert trade["max_loss"] == 22000

    assert (
        trade["horizon_date"]
        == "2026-09-30"
    )


def test_record_trade_defaults_are_not_hidden(
    db_path,
):
    """
    Service requires the caller to explicitly supply
    probability values and trade evidence.
    """

    with pytest.raises(TypeError):
        record_trade(
            underlying="META",
            currency="USD",
            is_paper=True,
            strategy="LONG_CALL",
        )
from datetime import date

import pytest

from src.database.repository import get_trade
from src.services.trade_service import (
    calculate_entry_cash,
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
        date_to_iso(
            date(
                2026,
                9,
                30,
            )
        )
        == "2026-09-30"
    )

    assert (
        date_to_iso(
            "2026-09-30"
        )
        == "2026-09-30"
    )

    assert (
        date_to_iso(None)
        is None
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


def test_calculate_entry_cash_single_buy():
    legs = [
        {
            "leg_no": 1,
            "right": "C",
            "direction": "BUY",
            "strike": 100.0,
            "expiration": "2026-09-30",
            "contracts": 1,
            "multiplier": 100,
            "entry_quote_at":
                "2026-08-26T12:00:00Z",
            "entry_iv": 0.30,
            "entry_delta": 0.50,
            "entry_bid": 2.10,
            "entry_ask": 2.30,
            "entry_fill": 2.20,
        }
    ]

    assert (
        calculate_entry_cash(
            legs
        )
        == pytest.approx(
            -220.0
        )
    )


def test_calculate_entry_cash_multileg_debit():
    legs = [
        {
            "leg_no": 1,
            "right": "C",
            "direction": "BUY",
            "strike": 100.0,
            "expiration": "2026-09-30",
            "contracts": 1,
            "multiplier": 100,
            "entry_quote_at":
                "2026-08-26T12:00:00Z",
            "entry_iv": 0.30,
            "entry_delta": 0.55,
            "entry_bid": 2.40,
            "entry_ask": 2.60,
            "entry_fill": 2.50,
        },
        {
            "leg_no": 2,
            "right": "C",
            "direction": "SELL",
            "strike": 110.0,
            "expiration": "2026-09-30",
            "contracts": 1,
            "multiplier": 100,
            "entry_quote_at":
                "2026-08-26T12:00:00Z",
            "entry_iv": 0.29,
            "entry_delta": 0.30,
            "entry_bid": 1.00,
            "entry_ask": 1.20,
            "entry_fill": 1.10,
        },
    ]

    assert (
        calculate_entry_cash(
            legs
        )
        == pytest.approx(
            -140.0
        )
    )


def test_calculate_entry_cash_multileg_credit():
    legs = [
        {
            "leg_no": 1,
            "right": "C",
            "direction": "SELL",
            "strike": 100.0,
            "expiration": "2026-09-30",
            "contracts": 1,
            "multiplier": 100,
            "entry_quote_at":
                "2026-08-26T12:00:00Z",
            "entry_iv": 0.30,
            "entry_delta": 0.55,
            "entry_bid": 2.90,
            "entry_ask": 3.10,
            "entry_fill": 3.00,
        },
        {
            "leg_no": 2,
            "right": "C",
            "direction": "BUY",
            "strike": 110.0,
            "expiration": "2026-09-30",
            "contracts": 1,
            "multiplier": 100,
            "entry_quote_at":
                "2026-08-26T12:00:00Z",
            "entry_iv": 0.29,
            "entry_delta": 0.30,
            "entry_bid": 1.15,
            "entry_ask": 1.35,
            "entry_fill": 1.25,
        },
    ]

    assert (
        calculate_entry_cash(
            legs
        )
        == pytest.approx(
            175.0
        )
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

            "entry_quote_at":
                "2026-08-26T11:59:30Z",

            "entry_iv":
                0.31,

            "entry_delta":
                0.38,

            "entry_bid":
                2.10,

            "entry_ask":
                2.30,

            "entry_fill":
                2.20,
        }
    ]

    trade_id = record_trade(
        underlying=
            "meta",

        currency=
            "usd",

        is_paper=
            True,

        strategy=
            "long_call",

        thesis=
            "META is likely to rise.",

        prediction=
            "META trades above 105 "
            "before the horizon.",

        horizon_date=
            date(
                2026,
                9,
                30,
            ),

        p_thesis_initial_percent=
            65,

        p_thesis_percent=
            60,

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

        entry_iv_rank=
            42.0,

        next_earnings_date=
            date(
                2026,
                10,
                20,
            ),

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

    assert result is not None

    trade = result["trade"]
    leg = result["legs"][0]

    assert (
        trade["underlying"]
        == "META"
    )

    assert (
        trade["currency"]
        == "USD"
    )

    assert (
        trade["strategy"]
        == "LONG_CALL"
    )

    assert (
        trade["is_paper"]
        == 1
    )

    assert (
        trade["p_thesis_initial"]
        == 0.65
    )

    assert (
        trade["p_thesis"]
        == 0.60
    )

    assert (
        trade["p_profit"]
        == 0.52
    )

    assert (
        trade["entry_iv_rank"]
        == 42.0
    )

    assert (
        trade["next_earnings_date"]
        == "2026-10-20"
    )

    assert (
        trade["entry_fees"]
        == 100
    )

    assert (
        trade["entry_cash"]
        == -22000
    )

    assert (
        trade["max_loss"]
        == 22000
    )

    assert (
        leg["entry_iv"]
        == 0.31
    )

    assert (
        leg["entry_delta"]
        == 0.38
    )

    assert (
        leg["entry_quote_at"]
        == "2026-08-26T11:59:30Z"
    )


def test_record_trade_calculates_multileg_cash(
    db_path,
):
    legs = [
        {
            "leg_no": 1,
            "right": "C",
            "direction": "BUY",
            "strike": 100.0,
            "expiration": "2026-09-30",
            "contracts": 1,
            "multiplier": 100,
            "entry_quote_at":
                "2026-08-26T12:00:00Z",
            "entry_iv": 0.30,
            "entry_delta": 0.55,
            "entry_bid": 2.40,
            "entry_ask": 2.60,
            "entry_fill": 2.50,
        },
        {
            "leg_no": 2,
            "right": "C",
            "direction": "SELL",
            "strike": 110.0,
            "expiration": "2026-09-30",
            "contracts": 1,
            "multiplier": 100,
            "entry_quote_at":
                "2026-08-26T12:00:00Z",
            "entry_iv": 0.29,
            "entry_delta": 0.30,
            "entry_bid": 1.00,
            "entry_ask": 1.20,
            "entry_fill": 1.10,
        },
    ]

    trade_id = record_trade(
        underlying=
            "TEST",

        currency=
            "USD",

        is_paper=
            True,

        strategy=
            "DEBIT_SPREAD",

        thesis=
            "Underlying rises.",

        prediction=
            "Underlying closes above 105.",

        horizon_date=
            "2026-09-30",

        p_thesis_initial_percent=
            60,

        p_thesis_percent=
            60,

        p_profit_percent=
            50,

        invalidation=
            "Underlying falls below 90.",

        entry_at=
            "2026-08-26T12:00:00Z",

        entry_underlying=
            100.0,

        entry_fx_rate=
            0.86,

        entry_fees_major=
            2.00,

        entry_iv_rank=
            40.0,

        next_earnings_date=
            None,

        max_loss_major=
            140.0,

        profit_target=
            "Close at target.",

        stop_condition=
            "Exit if invalidated.",

        legs=
            legs,

        db_path=
            db_path,
    )

    result = get_trade(
        trade_id,
        db_path=db_path,
    )

    assert result is not None

    assert (
        result["trade"]["entry_cash"]
        == -14000
    )

    assert (
        len(result["legs"])
        == 2
    )


def test_delta_out_of_range_is_rejected(
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
            "entry_quote_at":
                "2026-08-26T12:00:00Z",
            "entry_iv": 0.30,
            "entry_delta": 1.20,
            "entry_bid": 2.10,
            "entry_ask": 2.30,
            "entry_fill": 2.20,
        }
    ]

    with pytest.raises(
        ValueError,
        match="delta",
    ):
        record_trade(
            underlying=
                "TEST",

            currency=
                "USD",

            is_paper=
                True,

            strategy=
                "LONG_CALL",

            thesis=
                "Rise.",

            prediction=
                "TEST rises.",

            horizon_date=
                "2026-09-30",

            p_thesis_initial_percent=
                60,

            p_thesis_percent=
                60,

            p_profit_percent=
                50,

            invalidation=
                "Falls.",

            entry_at=
                "2026-08-26T12:00:00Z",

            entry_underlying=
                100.0,

            entry_fx_rate=
                0.86,

            entry_fees_major=
                1.0,

            entry_iv_rank=
                40.0,

            next_earnings_date=
                None,

            max_loss_major=
                220.0,

            profit_target=
                "Target.",

            stop_condition=
                "Stop.",

            legs=
                legs,

            db_path=
                db_path,
        )


def test_iv_rank_out_of_range_is_rejected(
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
            "entry_quote_at":
                "2026-08-26T12:00:00Z",
            "entry_iv": 0.30,
            "entry_delta": 0.40,
            "entry_bid": 2.10,
            "entry_ask": 2.30,
            "entry_fill": 2.20,
        }
    ]

    with pytest.raises(
        ValueError,
        match="IV rank",
    ):
        record_trade(
            underlying=
                "TEST",

            currency=
                "USD",

            is_paper=
                True,

            strategy=
                "LONG_CALL",

            thesis=
                "Rise.",

            prediction=
                "TEST rises.",

            horizon_date=
                "2026-09-30",

            p_thesis_initial_percent=
                60,

            p_thesis_percent=
                60,

            p_profit_percent=
                50,

            invalidation=
                "Falls.",

            entry_at=
                "2026-08-26T12:00:00Z",

            entry_underlying=
                100.0,

            entry_fx_rate=
                0.86,

            entry_fees_major=
                1.0,

            entry_iv_rank=
                120.0,

            next_earnings_date=
                None,

            max_loss_major=
                220.0,

            profit_target=
                "Target.",

            stop_condition=
                "Stop.",

            legs=
                legs,

            db_path=
                db_path,
        )
import sqlite3

import pytest

from src.database.repository import (
    assert_schema_version,
    close_trade,
    create_trade,
    get_connection,
    get_realized_pnl_minor,
    get_schema_version,
    get_trade,
    resolve_trade,
    to_minor,
)


def test_schema_version_is_expected(
    db_path,
):
    assert (
        get_schema_version(
            db_path
        )
        == 3
    )

    assert_schema_version(
        db_path
    )


def test_create_and_read_trade(
    db_path,
    base_trade,
    base_leg,
):
    trade_id = create_trade(
        base_trade,
        [base_leg],
        db_path=db_path,
    )

    result = get_trade(
        trade_id,
        db_path=db_path,
    )

    assert result is not None

    assert (
        result["trade"]["underlying"]
        == "TEST"
    )

    assert (
        result["trade"]["strategy"]
        == "LONG_CALL"
    )

    assert (
        result["trade"]["entry_iv_rank"]
        == 42.0
    )

    assert (
        result["trade"]["p_thesis_initial"]
        == 0.65
    )

    assert (
        len(result["legs"])
        == 1
    )

    assert (
        result["legs"][0]["strike"]
        == 105.0
    )

    assert (
        result["legs"][0]["direction"]
        == "BUY"
    )

    assert (
        result["legs"][0]["entry_iv"]
        == 0.31
    )

    assert (
        result["legs"][0]["entry_delta"]
        == 0.38
    )


def test_created_at_and_fill_time_are_distinct(
    db_path,
    base_trade,
    base_leg,
):
    trade_id = create_trade(
        base_trade,
        [base_leg],
        db_path=db_path,
    )

    result = get_trade(
        trade_id,
        db_path=db_path,
    )

    assert (
        result["trade"]["created_at"]
        == "2026-08-25T20:00:00Z"
    )

    assert (
        result["trade"]["entry_at"]
        == "2026-08-25T19:57:13Z"
    )

    assert (
        result["trade"]["created_at"]
        != result["trade"]["entry_at"]
    )


def test_quote_and_fill_times_are_distinct(
    db_path,
    base_trade,
    base_leg,
):
    trade_id = create_trade(
        base_trade,
        [base_leg],
        db_path=db_path,
    )

    result = get_trade(
        trade_id,
        db_path=db_path,
    )

    assert (
        result["legs"][0]["entry_quote_at"]
        == "2026-08-25T19:56:50Z"
    )

    assert (
        result["trade"]["entry_at"]
        == "2026-08-25T19:57:13Z"
    )

    assert (
        result["legs"][0]["entry_quote_at"]
        != result["trade"]["entry_at"]
    )


def test_probabilities_land_in_separate_columns(
    db_path,
    base_trade,
    base_leg,
):
    trade = dict(
        base_trade
    )

    trade["p_thesis_initial"] = 0.80
    trade["p_thesis"] = 0.73
    trade["p_profit"] = 0.41

    trade_id = create_trade(
        trade,
        [base_leg],
        db_path=db_path,
    )

    result = get_trade(
        trade_id,
        db_path=db_path,
    )

    assert (
        result["trade"]["p_thesis_initial"]
        == 0.80
    )

    assert (
        result["trade"]["p_thesis"]
        == 0.73
    )

    assert (
        result["trade"]["p_profit"]
        == 0.41
    )


def test_missing_p_thesis_initial_is_rejected(
    db_path,
    base_trade,
    base_leg,
):
    trade = dict(
        base_trade
    )

    del trade["p_thesis_initial"]

    with pytest.raises(
        ValueError
    ):
        create_trade(
            trade,
            [base_leg],
            db_path=db_path,
        )


def test_missing_p_thesis_is_rejected(
    db_path,
    base_trade,
    base_leg,
):
    trade = dict(
        base_trade
    )

    del trade["p_thesis"]

    with pytest.raises(
        ValueError
    ):
        create_trade(
            trade,
            [base_leg],
            db_path=db_path,
        )


def test_missing_p_profit_is_rejected(
    db_path,
    base_trade,
    base_leg,
):
    trade = dict(
        base_trade
    )

    del trade["p_profit"]

    with pytest.raises(
        ValueError
    ):
        create_trade(
            trade,
            [base_leg],
            db_path=db_path,
        )


@pytest.mark.parametrize(
    (
        "amount",
        "expected",
    ),
    [
        ("22.00", 2200),
        ("2.20", 220),
        (2.20, 220),
        ("0.01", 1),
        ("10.005", 1001),
    ],
)
def test_to_minor_avoids_float_truncation(
    amount,
    expected,
):
    assert (
        to_minor(amount)
        == expected
    )


def test_trade_and_legs_are_atomic(
    db_path,
    base_trade,
    base_leg,
):
    good_leg = dict(
        base_leg
    )

    bad_leg = dict(
        base_leg
    )

    bad_leg["leg_no"] = 2

    bad_leg["entry_bid"] = 10.0
    bad_leg["entry_ask"] = 9.0

    with pytest.raises(
        sqlite3.IntegrityError
    ):
        create_trade(
            base_trade,
            [
                good_leg,
                bad_leg,
            ],
            db_path=db_path,
        )

    with get_connection(
        db_path
    ) as connection:

        trades = connection.execute(
            """
            SELECT COUNT(*) AS n
            FROM trades;
            """
        ).fetchone()["n"]

        legs = connection.execute(
            """
            SELECT COUNT(*) AS n
            FROM trade_legs;
            """
        ).fetchone()["n"]

    assert trades == 0
    assert legs == 0


def test_prediction_is_immutable(
    db_path,
    base_trade,
    base_leg,
):
    trade_id = create_trade(
        base_trade,
        [base_leg],
        db_path=db_path,
    )

    with get_connection(
        db_path
    ) as connection:

        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                UPDATE trades
                SET thesis = ?
                WHERE id = ?;
                """,
                (
                    "Changed after seeing result.",
                    trade_id,
                ),
            )


def test_initial_thesis_probability_is_immutable(
    db_path,
    base_trade,
    base_leg,
):
    trade_id = create_trade(
        base_trade,
        [base_leg],
        db_path=db_path,
    )

    with get_connection(
        db_path
    ) as connection:

        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                UPDATE trades
                SET p_thesis_initial = ?
                WHERE id = ?;
                """,
                (
                    0.10,
                    trade_id,
                ),
            )


def test_entry_data_is_immutable(
    db_path,
    base_trade,
    base_leg,
):
    trade_id = create_trade(
        base_trade,
        [base_leg],
        db_path=db_path,
    )

    with get_connection(
        db_path
    ) as connection:

        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                UPDATE trades
                SET entry_underlying = ?
                WHERE id = ?;
                """,
                (
                    999.0,
                    trade_id,
                ),
            )


def test_leg_iv_is_immutable(
    db_path,
    base_trade,
    base_leg,
):
    trade_id = create_trade(
        base_trade,
        [base_leg],
        db_path=db_path,
    )

    with get_connection(
        db_path
    ) as connection:

        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                UPDATE trade_legs
                SET entry_iv = ?
                WHERE trade_id = ?
                  AND leg_no = 1;
                """,
                (
                    0.99,
                    trade_id,
                ),
            )


def test_leg_delta_is_immutable(
    db_path,
    base_trade,
    base_leg,
):
    trade_id = create_trade(
        base_trade,
        [base_leg],
        db_path=db_path,
    )

    with get_connection(
        db_path
    ) as connection:

        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                UPDATE trade_legs
                SET entry_delta = ?
                WHERE trade_id = ?
                  AND leg_no = 1;
                """,
                (
                    0.99,
                    trade_id,
                ),
            )


def test_paper_trade_round_trip(
    db_path,
    base_trade,
    base_leg,
):
    trade = dict(
        base_trade
    )

    trade["is_paper"] = 1

    trade_id = create_trade(
        trade,
        [base_leg],
        db_path=db_path,
    )

    result = get_trade(
        trade_id,
        db_path=db_path,
    )

    assert (
        result["trade"]["is_paper"]
        == 1
    )


def test_live_trade_round_trip(
    db_path,
    base_trade,
    base_leg,
):
    trade = dict(
        base_trade
    )

    trade["is_paper"] = 0

    trade_id = create_trade(
        trade,
        [base_leg],
        db_path=db_path,
    )

    result = get_trade(
        trade_id,
        db_path=db_path,
    )

    assert (
        result["trade"]["is_paper"]
        == 0
    )


def test_paper_is_safe_default(
    db_path,
    base_trade,
    base_leg,
):
    trade = dict(
        base_trade
    )

    del trade["is_paper"]

    trade_id = create_trade(
        trade,
        [base_leg],
        db_path=db_path,
    )

    result = get_trade(
        trade_id,
        db_path=db_path,
    )

    assert (
        result["trade"]["is_paper"]
        == 1
    )


def test_is_paper_is_immutable(
    db_path,
    base_trade,
    base_leg,
):
    trade_id = create_trade(
        base_trade,
        [base_leg],
        db_path=db_path,
    )

    with get_connection(
        db_path
    ) as connection:

        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                UPDATE trades
                SET is_paper = 0
                WHERE id = ?;
                """,
                (trade_id,),
            )


def test_close_trade_does_not_modify_immutable_fields(
    db_path,
    base_trade,
    base_leg,
):
    trade_id = create_trade(
        base_trade,
        [base_leg],
        db_path=db_path,
    )

    before = get_trade(
        trade_id,
        db_path=db_path,
    )

    close_trade(
        trade_id,
        status="CLOSED",
        exit_at=
            "2026-09-01T15:00:00Z",
        exit_underlying=110.0,
        exit_fx_rate=0.86,
        exit_fees=100,
        exit_cash=250000,
        exit_reason="TARGET",
        leg_exits=[
            {
                "leg_no": 1,
                "exit_bid": 24.90,
                "exit_ask": 25.10,
                "exit_fill": 25.00,
            }
        ],
        db_path=db_path,
    )

    after = get_trade(
        trade_id,
        db_path=db_path,
    )

    immutable_trade_fields = [
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
        "entry_at",
        "entry_underlying",
        "entry_fx_rate",
        "entry_fees",
        "entry_cash",
        "entry_iv_rank",
        "next_earnings_date",
        "is_paper",
    ]

    for field in immutable_trade_fields:
        assert (
            before["trade"][field]
            == after["trade"][field]
        )

    immutable_leg_fields = [
        "entry_quote_at",
        "entry_iv",
        "entry_delta",
        "entry_bid",
        "entry_ask",
        "entry_fill",
    ]

    for field in immutable_leg_fields:
        assert (
            before["legs"][0][field]
            == after["legs"][0][field]
        )


def test_debit_trade_pnl_sign(
    db_path,
    base_trade,
    base_leg,
):
    trade = dict(
        base_trade
    )

    trade["entry_cash"] = -220000
    trade["entry_fees"] = 100

    trade_id = create_trade(
        trade,
        [base_leg],
        db_path=db_path,
    )

    close_trade(
        trade_id,
        status="CLOSED",
        exit_at=
            "2026-09-01T15:00:00Z",
        exit_underlying=110.0,
        exit_fx_rate=0.86,
        exit_fees=100,
        exit_cash=250000,
        exit_reason="TARGET",
        db_path=db_path,
    )

    assert (
        get_realized_pnl_minor(
            trade_id,
            db_path=db_path,
        )
        == 29800
    )


def test_credit_trade_pnl_sign(
    db_path,
    base_trade,
    base_leg,
):
    trade = dict(
        base_trade
    )

    leg = dict(
        base_leg
    )

    trade["strategy"] = "SHORT_CALL"
    trade["entry_cash"] = 100000
    trade["entry_fees"] = 100

    leg["direction"] = "SELL"
    leg["entry_bid"] = 9.90
    leg["entry_ask"] = 10.10
    leg["entry_fill"] = 10.00

    trade_id = create_trade(
        trade,
        [leg],
        db_path=db_path,
    )

    close_trade(
        trade_id,
        status="CLOSED",
        exit_at=
            "2026-09-01T15:00:00Z",
        exit_underlying=95.0,
        exit_fx_rate=0.86,
        exit_fees=100,
        exit_cash=-40000,
        exit_reason="TARGET",
        db_path=db_path,
    )

    assert (
        get_realized_pnl_minor(
            trade_id,
            db_path=db_path,
        )
        == 59800
    )


def test_resolution_is_write_once(
    db_path,
    base_trade,
    base_leg,
):
    trade_id = create_trade(
        base_trade,
        [base_leg],
        db_path=db_path,
    )

    close_trade(
        trade_id,
        status="CLOSED",
        exit_at=
            "2026-09-30T20:00:00Z",
        exit_underlying=110.0,
        exit_fx_rate=0.86,
        exit_fees=100,
        exit_cash=250000,
        exit_reason="TARGET",
        db_path=db_path,
    )

    resolve_trade(
        trade_id,
        thesis_correct=True,
        was_profitable=True,
        resolved_at=
            "2026-10-01T12:00:00Z",
        db_path=db_path,
    )

    with pytest.raises(
        ValueError,
        match="already been resolved",
    ):
        resolve_trade(
            trade_id,
            thesis_correct=False,
            was_profitable=False,
            resolved_at=
                "2026-10-02T12:00:00Z",
            db_path=db_path,
        )


def test_rejected_decision_cannot_have_legs(
    db_path,
    base_trade,
    base_leg,
):
    trade = dict(
        base_trade
    )

    trade["status"] = "REJECTED"

    trade["entry_at"] = None
    trade["entry_underlying"] = None
    trade["entry_fx_rate"] = None
    trade["entry_fees"] = None
    trade["entry_cash"] = None

    trade["entry_iv_rank"] = None
    trade["next_earnings_date"] = None

    trade["rejection_reason"] = (
        "Spread was too wide."
    )

    with pytest.raises(
        sqlite3.IntegrityError
    ):
        create_trade(
            trade,
            [base_leg],
            db_path=db_path,
        )


def test_entry_slippage_buy_is_positive_cost(
    db_path,
    base_trade,
    base_leg,
):
    leg = dict(
        base_leg
    )

    leg["entry_bid"] = 2.40
    leg["entry_ask"] = 2.60
    leg["entry_fill"] = 2.55

    trade_id = create_trade(
        base_trade,
        [leg],
        db_path=db_path,
    )

    with get_connection(
        db_path
    ) as connection:

        row = connection.execute(
            """
            SELECT entry_slip
            FROM v_slippage
            WHERE trade_id = ?
              AND leg_no = 1;
            """,
            (trade_id,),
        ).fetchone()

    assert (
        row["entry_slip"]
        == pytest.approx(0.05)
    )


def test_entry_slippage_sell_is_positive_cost(
    db_path,
    base_trade,
    base_leg,
):
    leg = dict(
        base_leg
    )

    leg["direction"] = "SELL"

    leg["entry_bid"] = 2.40
    leg["entry_ask"] = 2.60
    leg["entry_fill"] = 2.45

    trade_id = create_trade(
        base_trade,
        [leg],
        db_path=db_path,
    )

    with get_connection(
        db_path
    ) as connection:

        row = connection.execute(
            """
            SELECT entry_slip
            FROM v_slippage
            WHERE trade_id = ?
              AND leg_no = 1;
            """,
            (trade_id,),
        ).fetchone()

    assert (
        row["entry_slip"]
        == pytest.approx(0.05)
    )


def test_entry_trigger_contains_paper_provenance(
    db_path,
):
    with get_connection(
        db_path
    ) as connection:

        row = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'trigger'
              AND name =
                  'trg_trades_entry_immutable';
            """
        ).fetchone()

    assert row is not None

    trigger_sql = (
        row["sql"].lower()
    )

    assert (
        "is_paper"
        in trigger_sql
    )


def test_prediction_trigger_contains_initial_probability(
    db_path,
):
    with get_connection(
        db_path
    ) as connection:

        row = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'trigger'
              AND name =
                  'trg_trades_prediction_immutable';
            """
        ).fetchone()

    assert row is not None

    trigger_sql = (
        row["sql"].lower()
    )

    assert (
        "p_thesis_initial"
        in trigger_sql
    )


def test_leg_trigger_contains_new_market_evidence(
    db_path,
):
    with get_connection(
        db_path
    ) as connection:

        row = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'trigger'
              AND name =
                  'trg_legs_entry_immutable';
            """
        ).fetchone()

    assert row is not None

    trigger_sql = (
        row["sql"].lower()
    )

    assert (
        "entry_quote_at"
        in trigger_sql
    )

    assert (
        "entry_iv"
        in trigger_sql
    )

    assert (
        "entry_delta"
        in trigger_sql
    )
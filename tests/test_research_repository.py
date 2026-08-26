import sqlite3

import pytest

from src.database.repository import (
    create_candidate,
    create_market_snapshot,
    get_candidate,
    get_connection,
    get_market_snapshot,
    set_candidate_status,
)


def make_snapshot(
    underlying="AAPL",
):
    return {
        "captured_at":
            "2026-08-26T20:00:00Z",

        "underlying":
            underlying,

        "provider":
            "MASSIVE",

        "provider_snapshot_id":
            "test-snapshot-001",

        "underlying_price":
            225.50,

        "underlying_source":
            "FETCHED",

        "underlying_at":
            "2026-08-26T20:00:00Z",

        "fx_to_eur":
            None,

        "fx_source":
            "UNKNOWN",

        "fx_at":
            None,

        "notes":
            "Research repository test.",
    }


def make_quote(
    symbol="O:AAPL260918C00230000",
    strike=230.0,
    delta=0.42,
):
    return {
        "provider_contract_id":
            symbol,

        "option_symbol":
            symbol,

        "right":
            "C",

        "strike":
            strike,

        "expiration":
            "2026-09-18",

        "quote_at":
            "2026-08-26T20:00:00Z",

        "bid":
            4.10,

        "bid_source":
            "FETCHED",

        "bid_at":
            "2026-08-26T20:00:00Z",

        "ask":
            4.30,

        "ask_source":
            "FETCHED",

        "ask_at":
            "2026-08-26T20:00:00Z",

        "last":
            4.20,

        "last_source":
            "FETCHED",

        "last_at":
            "2026-08-26T19:59:00Z",

        "implied_volatility":
            0.31,

        "iv_source":
            "FETCHED",

        "iv_at":
            "2026-08-26T20:00:00Z",

        "delta":
            delta,

        "delta_source":
            (
                "UNKNOWN"
                if delta is None
                else "FETCHED"
            ),

        "delta_at":
            (
                None
                if delta is None
                else "2026-08-26T20:00:00Z"
            ),

        "gamma":
            0.025,

        "gamma_source":
            "FETCHED",

        "gamma_at":
            "2026-08-26T20:00:00Z",

        "theta":
            -0.08,

        "theta_source":
            "FETCHED",

        "theta_at":
            "2026-08-26T20:00:00Z",

        "vega":
            0.14,

        "vega_source":
            "FETCHED",

        "vega_at":
            "2026-08-26T20:00:00Z",

        "volume":
            1200,

        "volume_source":
            "FETCHED",

        "volume_at":
            "2026-08-26T20:00:00Z",

        "open_interest":
            5400,

        "open_interest_source":
            "FETCHED",

        "open_interest_at":
            "2026-08-26T20:00:00Z",
    }


def make_candidate(
    snapshot_id,
):
    return {
        "created_at":
            "2026-08-26T20:01:00Z",

        "snapshot_id":
            snapshot_id,

        "underlying":
            "AAPL",

        "candidate_source":
            "CHRISTIANIA_SCANNER",

        "candidate_class":
            "ASYMMETRIC",

        "scanner_version":
            "scanner_v0.1",

        "rule_set_version":
            "rules_v0.1",

        "rule_id":
            "ASYM_001",

        "outcome_definition_version":
            "outcome_v0.1",

        "rationale":
            (
                "Test candidate generated from "
                "a frozen market snapshot."
            ),

        "model_probability_profit":
            0.30,

        "model_expected_value_minor":
            1250,

        "model_max_loss_minor":
            43000,

        "model_confidence":
            0.55,

        "status":
            "TRACKING",
    }


def test_create_and_read_market_snapshot(
    db_path,
):
    quotes = [
        make_quote(),
        make_quote(
            symbol="O:AAPL260918C00235000",
            strike=235.0,
            delta=0.33,
        ),
    ]

    snapshot_id = create_market_snapshot(
        make_snapshot(),
        quotes,
        db_path=db_path,
    )

    result = get_market_snapshot(
        snapshot_id,
        db_path=db_path,
    )

    assert result is not None

    assert (
        result["snapshot"]["underlying"]
        == "AAPL"
    )

    assert (
        result["snapshot"]["provider"]
        == "MASSIVE"
    )

    assert len(
        result["quotes"]
    ) == 2


def test_missing_delta_is_null_and_unknown(
    db_path,
):
    quote = make_quote(
        delta=None
    )

    snapshot_id = create_market_snapshot(
        make_snapshot(),
        [quote],
        db_path=db_path,
    )

    result = get_market_snapshot(
        snapshot_id,
        db_path=db_path,
    )

    stored_quote = result["quotes"][0]

    assert stored_quote["delta"] is None

    assert (
        stored_quote["delta_source"]
        == "UNKNOWN"
    )


def test_real_zero_delta_is_not_missing(
    db_path,
):
    quote = make_quote(
        delta=0.0
    )

    snapshot_id = create_market_snapshot(
        make_snapshot(),
        [quote],
        db_path=db_path,
    )

    result = get_market_snapshot(
        snapshot_id,
        db_path=db_path,
    )

    stored_quote = result["quotes"][0]

    assert stored_quote["delta"] == 0.0

    assert (
        stored_quote["delta_source"]
        == "FETCHED"
    )


def test_missing_delta_cannot_claim_fetched(
    db_path,
):
    quote = make_quote(
        delta=None
    )

    quote["delta_source"] = "FETCHED"

    with pytest.raises(
        ValueError,
        match="must be UNKNOWN",
    ):
        create_market_snapshot(
            make_snapshot(),
            [quote],
            db_path=db_path,
        )


def test_value_cannot_claim_unknown_source(
    db_path,
):
    quote = make_quote()

    quote["gamma_source"] = "UNKNOWN"

    with pytest.raises(
        ValueError,
        match="cannot be UNKNOWN",
    ):
        create_market_snapshot(
            make_snapshot(),
            [quote],
            db_path=db_path,
        )


def test_market_snapshot_is_atomic(
    db_path,
):
    good_quote = make_quote()

    bad_quote = make_quote(
        symbol="O:AAPL260918C00235000",
        strike=235.0,
    )

    bad_quote["ask"] = 3.00
    bad_quote["bid"] = 4.00

    with pytest.raises(
        sqlite3.IntegrityError
    ):
        create_market_snapshot(
            make_snapshot(),
            [
                good_quote,
                bad_quote,
            ],
            db_path=db_path,
        )

    connection = get_connection(
        db_path
    )

    try:
        snapshot_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM market_snapshots;
            """
        ).fetchone()["count"]

        quote_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM option_quotes;
            """
        ).fetchone()["count"]

    finally:
        connection.close()

    assert snapshot_count == 0
    assert quote_count == 0


def test_market_evidence_is_immutable(
    db_path,
):
    snapshot_id = create_market_snapshot(
        make_snapshot(),
        [make_quote()],
        db_path=db_path,
    )

    connection = get_connection(
        db_path
    )

    try:
        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                UPDATE market_snapshots
                SET underlying_price = 999.0
                WHERE id = ?;
                """,
                (snapshot_id,),
            )

    finally:
        connection.close()


def test_create_candidate_with_matched_control(
    db_path,
):
    snapshot_id = create_market_snapshot(
        make_snapshot(),
        [
            make_quote(
                symbol="O:AAPL260918C00230000",
                strike=230.0,
                delta=0.42,
            ),
            make_quote(
                symbol="O:AAPL260918C00235000",
                strike=235.0,
                delta=0.34,
            ),
        ],
        db_path=db_path,
    )

    snapshot = get_market_snapshot(
        snapshot_id,
        db_path=db_path,
    )

    candidate_quote_id = (
        snapshot["quotes"][0]["id"]
    )

    control_quote_id = (
        snapshot["quotes"][1]["id"]
    )

    candidate_id = create_candidate(
        make_candidate(
            snapshot_id
        ),
        legs=[
            {
                "leg_no":
                    1,

                "option_quote_id":
                    candidate_quote_id,

                "direction":
                    "BUY",

                "contracts":
                    1,
            }
        ],
        controls=[
            {
                "control_quote_id":
                    control_quote_id,

                "matching_version":
                    "match_v0.1",

                "match_rank":
                    1,

                "match_distance":
                    0.08,

                "created_at":
                    "2026-08-26T20:01:00Z",
            }
        ],
        db_path=db_path,
    )

    result = get_candidate(
        candidate_id,
        db_path=db_path,
    )

    assert result is not None

    assert (
        result["candidate"]["rule_id"]
        == "ASYM_001"
    )

    assert (
        result["candidate"][
            "candidate_source"
        ]
        == "CHRISTIANIA_SCANNER"
    )

    assert len(
        result["legs"]
    ) == 1

    assert len(
        result["controls"]
    ) == 1

    assert (
        result["legs"][0][
            "option_quote_id"
        ]
        == candidate_quote_id
    )

    assert (
        result["controls"][0][
            "control_quote_id"
        ]
        == control_quote_id
    )


def test_candidate_leg_must_use_same_snapshot(
    db_path,
):
    first_snapshot_id = (
        create_market_snapshot(
            make_snapshot(
                underlying="AAPL"
            ),
            [make_quote()],
            db_path=db_path,
        )
    )

    second_snapshot_id = (
        create_market_snapshot(
            make_snapshot(
                underlying="MSFT"
            ),
            [
                make_quote(
                    symbol="O:MSFT260918C00500000",
                    strike=500.0,
                    delta=0.40,
                )
            ],
            db_path=db_path,
        )
    )

    second_snapshot = (
        get_market_snapshot(
            second_snapshot_id,
            db_path=db_path,
        )
    )

    wrong_quote_id = (
        second_snapshot["quotes"][0]["id"]
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="candidate snapshot",
    ):
        create_candidate(
            make_candidate(
                first_snapshot_id
            ),
            legs=[
                {
                    "leg_no":
                        1,

                    "option_quote_id":
                        wrong_quote_id,

                    "direction":
                        "BUY",

                    "contracts":
                        1,
                }
            ],
            db_path=db_path,
        )


def test_candidate_cannot_use_own_leg_as_control(
    db_path,
):
    snapshot_id = create_market_snapshot(
        make_snapshot(),
        [make_quote()],
        db_path=db_path,
    )

    snapshot = get_market_snapshot(
        snapshot_id,
        db_path=db_path,
    )

    quote_id = (
        snapshot["quotes"][0]["id"]
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="own matched control",
    ):
        create_candidate(
            make_candidate(
                snapshot_id
            ),
            legs=[
                {
                    "leg_no":
                        1,

                    "option_quote_id":
                        quote_id,

                    "direction":
                        "BUY",

                    "contracts":
                        1,
                }
            ],
            controls=[
                {
                    "control_quote_id":
                        quote_id,

                    "matching_version":
                        "match_v0.1",

                    "match_rank":
                        1,

                    "match_distance":
                        0.0,

                    "created_at":
                        "2026-08-26T20:01:00Z",
                }
            ],
            db_path=db_path,
        )


def test_candidate_definition_is_immutable(
    db_path,
):
    snapshot_id = create_market_snapshot(
        make_snapshot(),
        [make_quote()],
        db_path=db_path,
    )

    snapshot = get_market_snapshot(
        snapshot_id,
        db_path=db_path,
    )

    quote_id = (
        snapshot["quotes"][0]["id"]
    )

    candidate_id = create_candidate(
        make_candidate(
            snapshot_id
        ),
        legs=[
            {
                "leg_no":
                    1,

                "option_quote_id":
                    quote_id,

                "direction":
                    "BUY",

                "contracts":
                    1,
            }
        ],
        db_path=db_path,
    )

    connection = get_connection(
        db_path
    )

    try:
        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                UPDATE candidates
                SET rule_id = 'CHANGED_AFTER_FACT'
                WHERE id = ?;
                """,
                (candidate_id,),
            )

    finally:
        connection.close()


def test_candidate_status_can_change(
    db_path,
):
    snapshot_id = create_market_snapshot(
        make_snapshot(),
        [make_quote()],
        db_path=db_path,
    )

    snapshot = get_market_snapshot(
        snapshot_id,
        db_path=db_path,
    )

    quote_id = (
        snapshot["quotes"][0]["id"]
    )

    candidate_id = create_candidate(
        make_candidate(
            snapshot_id
        ),
        legs=[
            {
                "leg_no":
                    1,

                "option_quote_id":
                    quote_id,

                "direction":
                    "BUY",

                "contracts":
                    1,
            }
        ],
        db_path=db_path,
    )

    set_candidate_status(
        candidate_id,
        "WATCH",
        db_path=db_path,
    )

    result = get_candidate(
        candidate_id,
        db_path=db_path,
    )

    assert (
        result["candidate"]["status"]
        == "WATCH"
    )
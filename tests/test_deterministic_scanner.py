from datetime import datetime
from zoneinfo import ZoneInfo

from src.database.provider_evidence import (
    create_provider_model_observation,
)
from src.database.repository import (
    create_market_snapshot,
    get_connection,
)
from src.research.deterministic_scanner import (
    scan_research_run,
)

UTC = ZoneInfo("UTC")


def create_completed_run(db_path):
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO research_runs (
                cohort_id,
                preregistration_hash,
                code_git_sha,
                started_at,
                ended_at,
                us_session_date,
                us_session_state,
                status
            )
            VALUES (
                'INDEPENDENT_RESEARCH_RUNNER_V1',
                'hash',
                'sha',
                '2026-08-31T18:00:00Z',
                '2026-08-31T18:01:00Z',
                '2026-08-31',
                'INTRADAY',
                'COMPLETED'
            );
            """
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def add_quote_and_model(
    *,
    db_path,
    run_id,
    captured_at,
    quote_at,
    bid,
    ask,
    iv_error,
    delta,
):
    snapshot_id = create_market_snapshot(
        {
            "captured_at":
                captured_at,
            "underlying":
                "AAPL",
            "provider":
                "THETADATA",
            "research_run_id":
                run_id,
            "us_session_date":
                "2026-08-31",
            "us_session_state":
                "INTRADAY",
            "underlying_price":
                None,
            "underlying_source":
                "UNKNOWN",
            "underlying_at":
                None,
            "fx_to_eur":
                None,
            "fx_source":
                "UNKNOWN",
            "fx_at":
                None,
        },
        [
            {
                "provider_contract_id":
                    "THETA:AAPL:2026-09-18:100:C",
                "option_symbol":
                    None,
                "right":
                    "C",
                "strike":
                    100.0,
                "expiration":
                    "2026-09-18",
                "quote_at":
                    quote_at,
                "bid":
                    bid,
                "bid_source":
                    "FETCHED",
                "bid_at":
                    quote_at,
                "ask":
                    ask,
                "ask_source":
                    "FETCHED",
                "ask_at":
                    quote_at,
                "last":
                    None,
                "last_source":
                    "UNKNOWN",
                "last_at":
                    None,
                "implied_volatility":
                    None,
                "iv_source":
                    "UNKNOWN",
                "iv_at":
                    None,
                "delta":
                    None,
                "delta_source":
                    "UNKNOWN",
                "delta_at":
                    None,
                "gamma":
                    None,
                "gamma_source":
                    "UNKNOWN",
                "gamma_at":
                    None,
                "theta":
                    None,
                "theta_source":
                    "UNKNOWN",
                "theta_at":
                    None,
                "vega":
                    None,
                "vega_source":
                    "UNKNOWN",
                "vega_at":
                    None,
                "volume":
                    None,
                "volume_source":
                    "UNKNOWN",
                "volume_at":
                    None,
                "open_interest":
                    None,
                "open_interest_source":
                    "UNKNOWN",
                "open_interest_at":
                    None,
            }
        ],
        db_path=db_path,
    )

    conn = get_connection(db_path)
    try:
        quote_id = conn.execute(
            """
            SELECT id
            FROM option_quotes
            WHERE snapshot_id = ?;
            """,
            (snapshot_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    create_provider_model_observation(
        option_quote_id=quote_id,
        provider="THETADATA",
        implied_volatility=0.25,
        delta=delta,
        gamma=None,
        theta=None,
        vega=None,
        ingested_at=captured_at,
        observed_at=quote_at,
        model_name=
            "ThetaData first_order snapshot",
        model_underlying_price=101.0,
        model_input_notes=(
            '{"iv_error": '
            f"{iv_error}"
            "}"
        ),
        db_path=db_path,
    )


def test_fresh_tight_quote_with_good_greek_is_eligible(
    db_path,
):
    run_id = create_completed_run(
        db_path
    )

    add_quote_and_model(
        db_path=db_path,
        run_id=run_id,
        captured_at=
            "2026-08-31T18:00:05Z",
        quote_at=
            "2026-08-31T14:00:00",
        bid=5.0,
        ask=5.1,
        iv_error=0.001,
        delta=0.5,
    )

    result = scan_research_run(
        research_run_id=run_id,
        db_path=db_path,
    )

    assert result.total_quotes == 1
    assert result.eligible == 1
    assert (
        result.observations[0]
        .structurally_eligible
        is True
    )


def test_stale_quote_blocks(
    db_path,
):
    run_id = create_completed_run(
        db_path
    )

    add_quote_and_model(
        db_path=db_path,
        run_id=run_id,
        captured_at=
            "2026-08-31T18:02:00Z",
        quote_at=
            "2026-08-31T14:00:00",
        bid=5.0,
        ask=5.1,
        iv_error=0.001,
        delta=0.5,
    )

    result = scan_research_run(
        research_run_id=run_id,
        db_path=db_path,
    )

    assert result.eligible == 0
    assert "QUOTE_NOT_FRESH" in (
        result.observations[0]
        .blocking_reasons
    )


def test_wide_spread_blocks(
    db_path,
):
    run_id = create_completed_run(
        db_path
    )

    add_quote_and_model(
        db_path=db_path,
        run_id=run_id,
        captured_at=
            "2026-08-31T18:00:05Z",
        quote_at=
            "2026-08-31T14:00:00",
        bid=1.0,
        ask=2.0,
        iv_error=0.001,
        delta=0.5,
    )

    result = scan_research_run(
        research_run_id=run_id,
        max_spread_to_mid=0.20,
        db_path=db_path,
    )

    assert result.eligible == 0
    assert "SPREAD_TOO_WIDE" in (
        result.observations[0]
        .blocking_reasons
    )


def test_bad_greek_quality_blocks(
    db_path,
):
    run_id = create_completed_run(
        db_path
    )

    add_quote_and_model(
        db_path=db_path,
        run_id=run_id,
        captured_at=
            "2026-08-31T18:00:05Z",
        quote_at=
            "2026-08-31T14:00:00",
        bid=5.0,
        ask=5.1,
        iv_error=0.1,
        delta=0.5,
    )

    result = scan_research_run(
        research_run_id=run_id,
        db_path=db_path,
    )

    assert result.eligible == 0
    assert "GREEK_QUALITY_NOT_ACCEPTABLE" in (
        result.observations[0]
        .blocking_reasons
    )

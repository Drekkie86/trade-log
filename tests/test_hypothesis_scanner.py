import pytest

from src.database.provider_evidence import (
    create_provider_model_observation,
)
from src.database.repository import (
    create_market_snapshot,
    get_connection,
)
from src.research.hypothesis_scanner import (
    scan_local_iv_residuals,
)


def create_completed_run(
    db_path,
):
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


def add_contract(
    *,
    db_path,
    run_id,
    strike,
    iv,
    delta,
):
    conn = get_connection(db_path)

    try:
        conn.execute(
            """
            INSERT INTO listing_reference_contracts (
                research_run_id,
                provider,
                underlying,
                provider_contract_id,
                expiration,
                strike,
                right,
                observed_at,
                ingested_at
            )
            VALUES (
                ?,
                'MASSIVE',
                'AAPL',
                ?,
                '2026-09-18',
                ?,
                'C',
                '2026-08-31T18:00:00Z',
                '2026-08-31T18:00:00Z'
            );
            """,
            (
                run_id,
                f"O:TEST{strike}",
                strike,
            ),
        )

        conn.commit()

    finally:
        conn.close()

    snapshot_id = create_market_snapshot(
        {
            "captured_at":
                "2026-08-31T18:00:05Z",
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
                    f"THETA:AAPL:2026-09-18:{strike}:C",
                "option_symbol":
                    None,
                "right":
                    "C",
                "strike":
                    strike,
                "expiration":
                    "2026-09-18",
                "quote_at":
                    "2026-08-31T14:00:00",
                "bid":
                    5.0,
                "bid_source":
                    "FETCHED",
                "bid_at":
                    "2026-08-31T14:00:00",
                "ask":
                    5.1,
                "ask_source":
                    "FETCHED",
                "ask_at":
                    "2026-08-31T14:00:00",
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
        option_quote_id=
            quote_id,
        provider=
            "THETADATA",
        implied_volatility=
            iv,
        delta=
            delta,
        gamma=
            None,
        theta=
            None,
        vega=
            None,
        ingested_at=
            "2026-08-31T18:00:05Z",
        observed_at=
            "2026-08-31T14:00:00",
        model_name=
            "ThetaData first_order snapshot",
        model_underlying_price=
            101.0,
        model_input_notes=
            '{"iv_error": 0.001}',
        db_path=
            db_path,
    )


def test_local_iv_residual_surfaces_middle_spike(
    db_path,
):
    run_id = create_completed_run(
        db_path
    )

    add_contract(
        db_path=db_path,
        run_id=run_id,
        strike=95.0,
        iv=0.20,
        delta=0.60,
    )

    add_contract(
        db_path=db_path,
        run_id=run_id,
        strike=100.0,
        iv=0.28,
        delta=0.50,
    )

    add_contract(
        db_path=db_path,
        run_id=run_id,
        strike=105.0,
        iv=0.20,
        delta=0.40,
    )

    result = scan_local_iv_residuals(
        research_run_id=
            run_id,
        residual_threshold=
            0.03,
        persist=False,
        db_path=db_path,
    )

    assert result.structural_input_count == 3
    assert result.evaluable_count == 1
    assert result.surfaced_count == 1

    middle = [
        item
        for item in result.evaluations
        if item.strike == 100.0
    ][0]

    assert (
        middle.evaluation_state
        == "SURFACED"
    )

    assert (
        middle.surfaced_direction
        == "IV_RICH_LOCAL"
    )

    assert middle.iv_residual == pytest.approx(
        0.08
    )


def test_flat_local_surface_does_not_surface(
    db_path,
):
    run_id = create_completed_run(
        db_path
    )

    for strike, delta in (
        (95.0, 0.60),
        (100.0, 0.50),
        (105.0, 0.40),
    ):
        add_contract(
            db_path=db_path,
            run_id=run_id,
            strike=strike,
            iv=0.20,
            delta=delta,
        )

    result = scan_local_iv_residuals(
        research_run_id=
            run_id,
        persist=False,
        db_path=db_path,
    )

    assert result.surfaced_count == 0


def test_scanner_persists_full_selection_surface(
    db_path,
):
    run_id = create_completed_run(
        db_path
    )

    add_contract(
        db_path=db_path,
        run_id=run_id,
        strike=95.0,
        iv=0.20,
        delta=0.60,
    )

    add_contract(
        db_path=db_path,
        run_id=run_id,
        strike=100.0,
        iv=0.28,
        delta=0.50,
    )

    add_contract(
        db_path=db_path,
        run_id=run_id,
        strike=105.0,
        iv=0.20,
        delta=0.40,
    )

    result = scan_local_iv_residuals(
        research_run_id=
            run_id,
        persist=True,
        db_path=db_path,
    )

    assert (
        result.persisted_scanner_run_id
        is not None
    )

    conn = get_connection(db_path)

    try:
        run_row = conn.execute(
            """
            SELECT *
            FROM hypothesis_scanner_runs
            WHERE id = ?;
            """,
            (
                result.persisted_scanner_run_id,
            ),
        ).fetchone()

        assert (
            run_row["structural_input_count"]
            == 3
        )

        assert (
            run_row["evaluable_count"]
            == 1
        )

        assert (
            run_row["surfaced_count"]
            == 1
        )

        evaluations = conn.execute(
            """
            SELECT *
            FROM hypothesis_scanner_evaluations
            WHERE scanner_run_id = ?
            ORDER BY strike;
            """,
            (
                result.persisted_scanner_run_id,
            ),
        ).fetchall()

        assert len(evaluations) == 3

        assert [
            row["evaluation_state"]
            for row in evaluations
        ] == [
            "NOT_EVALUABLE",
            "SURFACED",
            "NOT_EVALUABLE",
        ]

    finally:
        conn.close()
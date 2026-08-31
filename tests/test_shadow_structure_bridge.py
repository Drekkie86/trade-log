import json

import pytest

from src.database.provider_evidence import (
    create_provider_model_observation,
)
from src.database.repository import (
    create_market_snapshot,
    get_connection,
)
from src.research.shadow_structure_bridge import (
    build_shadow_structure_proposals,
)


def seed_surface(
    db_path,
    *,
    direction="IV_RICH_LOCAL",
    lower=95.0,
    target=100.0,
    upper=105.0,
):
    conn = get_connection(db_path)

    try:
        run_id = conn.execute(
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
                '2026-09-01T18:00:00Z',
                '2026-09-01T18:01:00Z',
                '2026-09-01',
                'INTRADAY',
                'COMPLETED'
            );
            """
        ).lastrowid
        conn.commit()
    finally:
        conn.close()

    ref_ids = {}

    for strike in (
        lower,
        target,
        upper,
    ):
        conn = get_connection(db_path)
        try:
            ref_ids[strike] = int(
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
                        shares_per_contract,
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
                        100,
                        '2026-09-01T18:00:00Z',
                        '2026-09-01T18:00:00Z'
                    );
                    """,
                    (
                        run_id,
                        f"O:TEST{strike}",
                        strike,
                    ),
                ).lastrowid
            )
            conn.commit()
        finally:
            conn.close()

    quote_rows = []

    prices = {
        lower: (6.9, 7.0),
        target: (4.9, 5.0),
        upper: (2.9, 3.0),
    }

    for strike in (
        lower,
        target,
        upper,
    ):
        bid, ask = prices[
            strike
        ]

        quote_rows.append(
            {
                "provider_contract_id":
                    f"THETA:{strike}",
                "option_symbol":
                    None,
                "right":
                    "C",
                "strike":
                    strike,
                "expiration":
                    "2026-09-18",
                "quote_at":
                    "2026-09-01T14:00:00",
                "bid":
                    bid,
                "bid_source":
                    "FETCHED",
                "bid_at":
                    "2026-09-01T14:00:00",
                "ask":
                    ask,
                "ask_source":
                    "FETCHED",
                "ask_at":
                    "2026-09-01T14:00:00",
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
        )

    snapshot_id = create_market_snapshot(
        {
            "captured_at":
                "2026-09-01T18:00:05Z",
            "underlying":
                "AAPL",
            "provider":
                "THETADATA",
            "research_run_id":
                run_id,
            "us_session_date":
                "2026-09-01",
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
        quote_rows,
        db_path=db_path,
    )

    conn = get_connection(db_path)
    try:
        quote_ids = {
            float(row["strike"]):
                int(row["id"])
            for row in conn.execute(
                """
                SELECT id, strike
                FROM option_quotes
                WHERE snapshot_id = ?;
                """,
                (snapshot_id,),
            ).fetchall()
        }

        scanner_run_id = int(
            conn.execute(
                """
                INSERT INTO hypothesis_scanner_runs (
                    research_run_id,
                    scanner_family_id,
                    scanner_version,
                    rule_version,
                    hypothesis_family,
                    hypothesis_version,
                    config_hash,
                    config_json,
                    evaluated_at,
                    structural_input_count,
                    evaluable_count,
                    surfaced_count
                )
                VALUES (
                    ?,
                    'LOCAL_IV_RESIDUAL_V1',
                    '1.0.0',
                    'LOCAL_IV_RESIDUAL_RULES_V1',
                    'LOCAL_SURFACE_IV_RESIDUAL',
                    '1.0.0',
                    ?,
                    '{}',
                    '2026-09-01T18:00:06Z',
                    3,
                    1,
                    1
                );
                """,
                (
                    run_id,
                    "a" * 64,
                ),
            ).lastrowid
        )

        evaluation_id = int(
            conn.execute(
                """
                INSERT INTO hypothesis_scanner_evaluations (
                    scanner_run_id,
                    reference_contract_id,
                    option_quote_id,
                    underlying,
                    expiration,
                    strike,
                    right,
                    delta,
                    implied_volatility,
                    lower_strike,
                    lower_iv,
                    upper_strike,
                    upper_iv,
                    interpolated_iv,
                    iv_residual,
                    abs_iv_residual,
                    residual_threshold,
                    evaluation_state,
                    reason_code,
                    surfaced_direction,
                    evidence_json
                )
                VALUES (
                    ?,
                    ?,
                    ?,
                    'AAPL',
                    '2026-09-18',
                    ?,
                    'C',
                    0.50,
                    0.28,
                    ?,
                    0.20,
                    ?,
                    0.20,
                    0.20,
                    0.08,
                    0.08,
                    0.03,
                    'SURFACED',
                    'LOCAL_IV_RESIDUAL_ABOVE_THRESHOLD',
                    ?,
                    '{}'
                );
                """,
                (
                    scanner_run_id,
                    ref_ids[target],
                    quote_ids[target],
                    target,
                    lower,
                    upper,
                    direction,
                ),
            ).lastrowid
        )

        conn.commit()
    finally:
        conn.close()

    return (
        run_id,
        scanner_run_id,
        evaluation_id,
    )


def test_rich_local_anomaly_builds_long_butterfly(
    db_path,
):
    _, scanner_run_id, _ = seed_surface(
        db_path,
        direction="IV_RICH_LOCAL",
    )

    result = build_shadow_structure_proposals(
        hypothesis_scanner_run_id=
            scanner_run_id,
        persist=False,
        db_path=db_path,
    )

    assert result.surfaced_count == 1
    assert result.proposed_count == 1
    assert result.blocked_count == 0

    proposal = result.proposals[0]

    assert (
        proposal.structure_id
        == "LONG_1_2_1_BUTTERFLY"
    )

    assert [
        (
            leg.strike,
            leg.quantity,
            leg.side,
        )
        for leg in proposal.legs
    ] == [
        (95.0, 1, "BUY"),
        (100.0, 2, "SELL"),
        (105.0, 1, "BUY"),
    ]

    assert proposal.risk_currency == "USD"
    assert (
        proposal.max_theoretical_loss_minor
        is not None
    )
    assert (
        proposal.max_theoretical_loss_minor
        >= 0
    )


def test_cheap_local_anomaly_builds_reverse_butterfly(
    db_path,
):
    _, scanner_run_id, _ = seed_surface(
        db_path,
        direction="IV_CHEAP_LOCAL",
    )

    result = build_shadow_structure_proposals(
        hypothesis_scanner_run_id=
            scanner_run_id,
        persist=False,
        db_path=db_path,
    )

    proposal = result.proposals[0]

    assert (
        proposal.structure_id
        == "REVERSE_1_2_1_BUTTERFLY"
    )

    assert [
        leg.side
        for leg in proposal.legs
    ] == [
        "SELL",
        "BUY",
        "SELL",
    ]

    assert (
        proposal.max_theoretical_loss_minor
        is not None
    )


def test_unequal_wings_are_blocked(
    db_path,
):
    _, scanner_run_id, _ = seed_surface(
        db_path,
        lower=94.0,
        target=100.0,
        upper=105.0,
    )

    result = build_shadow_structure_proposals(
        hypothesis_scanner_run_id=
            scanner_run_id,
        persist=False,
        db_path=db_path,
    )

    proposal = result.proposals[0]

    assert proposal.proposal_state == "BLOCKED"
    assert (
        proposal.reason_code
        == "UNEQUAL_WING_WIDTHS"
    )


def test_full_proposal_surface_is_persisted_and_idempotent(
    db_path,
):
    _, scanner_run_id, evaluation_id = seed_surface(
        db_path,
    )

    first = build_shadow_structure_proposals(
        hypothesis_scanner_run_id=
            scanner_run_id,
        persist=True,
        db_path=db_path,
    )

    second = build_shadow_structure_proposals(
        hypothesis_scanner_run_id=
            scanner_run_id,
        persist=True,
        db_path=db_path,
    )

    assert (
        first.proposals[0]
        .persisted_proposal_id
        == second.proposals[0]
        .persisted_proposal_id
    )

    conn = get_connection(db_path)

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM shadow_structure_proposals
            WHERE hypothesis_evaluation_id = ?;
            """,
            (evaluation_id,),
        ).fetchall()

        assert len(rows) == 1
        assert rows[0]["proposal_state"] == "PROPOSED"

        structure = json.loads(
            rows[0]["structure_json"]
        )

        assert len(
            structure["legs"]
        ) == 3
    finally:
        conn.close()

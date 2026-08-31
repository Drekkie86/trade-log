import json

from src.database.repository import (
    get_connection,
)
from src.providers.ecb_fx import (
    EcbFxObservation,
)
from src.research.shadow_admission import (
    admit_shadow_proposals,
)


def seed_proposal(
    db_path,
    *,
    max_loss_usd_minor=20_000,
):
    conn = get_connection(db_path)

    try:
        run_id = int(
            conn.execute(
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
        )

        reference_id = int(
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
                    'O:TARGET',
                    '2026-09-18',
                    100,
                    'C',
                    100,
                    '2026-09-01T18:00:00Z',
                    '2026-09-01T18:00:00Z'
                );
                """,
                (run_id,),
            ).lastrowid
        )

        conn.execute(
            """
            INSERT INTO provider_observation_availability (
                reference_contract_id,
                provider,
                evidence_family,
                state,
                observed_at,
                ingested_at
            )
            VALUES (?, 'MASSIVE', 'MASSIVE_SNAPSHOT', 'PRESENT',
                    '2026-09-01T18:00:05Z',
                    '2026-09-01T18:00:05Z');
            """,
            (reference_id,),
        )

        quote_evidence_id = int(
            conn.execute(
                """
                INSERT INTO provider_observation_availability (
                    reference_contract_id,
                    provider,
                    evidence_family,
                    state,
                    observed_at,
                    ingested_at
                )
                VALUES (?, 'THETADATA', 'THETADATA_QUOTE', 'PRESENT',
                        '2026-09-01T18:00:05Z',
                        '2026-09-01T18:00:05Z');
                """,
                (reference_id,),
            ).lastrowid
        )

        greek_evidence_id = int(
            conn.execute(
                """
                INSERT INTO provider_observation_availability (
                    reference_contract_id,
                    provider,
                    evidence_family,
                    state,
                    observed_at,
                    ingested_at
                )
                VALUES (?, 'THETADATA', 'THETADATA_GREEKS', 'PRESENT',
                        '2026-09-01T18:00:05Z',
                        '2026-09-01T18:00:05Z');
                """,
                (reference_id,),
            ).lastrowid
        )

        snapshot_id = int(
            conn.execute(
                """
                INSERT INTO market_snapshots (
                    captured_at,
                    underlying,
                    provider,
                    research_run_id,
                    us_session_date,
                    us_session_state,
                    underlying_source,
                    fx_source
                )
                VALUES (
                    '2026-09-01T18:00:05Z',
                    'AAPL',
                    'THETADATA',
                    ?,
                    '2026-09-01',
                    'INTRADAY',
                    'UNKNOWN',
                    'UNKNOWN'
                );
                """,
                (run_id,),
            ).lastrowid
        )

        option_quote_id = int(
            conn.execute(
                """
                INSERT INTO option_quotes (
                    snapshot_id,
                    provider_contract_id,
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
                    last_source,
                    iv_source,
                    delta_source,
                    gamma_source,
                    theta_source,
                    vega_source,
                    volume_source,
                    open_interest_source
                )
                VALUES (
                    ?,
                    'THETA:TARGET',
                    'C',
                    100,
                    '2026-09-18',
                    '2026-09-01T14:00:00',
                    4.9,
                    'FETCHED',
                    '2026-09-01T14:00:00',
                    5.0,
                    'FETCHED',
                    '2026-09-01T14:00:00',
                    'UNKNOWN',
                    'UNKNOWN',
                    'UNKNOWN',
                    'UNKNOWN',
                    'UNKNOWN',
                    'UNKNOWN',
                    'UNKNOWN',
                    'UNKNOWN'
                );
                """,
                (snapshot_id,),
            ).lastrowid
        )

        conn.execute(
            """
            INSERT INTO provider_model_observations (
                option_quote_id,
                provider,
                implied_volatility,
                delta,
                ingested_at,
                observed_at,
                model_name,
                model_input_notes
            )
            VALUES (
                ?,
                'THETADATA',
                0.28,
                0.50,
                '2026-09-01T18:00:05Z',
                '2026-09-01T14:00:00',
                'ThetaData first_order snapshot',
                '{"iv_error": 0.001}'
            );
            """,
            (option_quote_id,),
        )

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
                    1,
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
                    100,
                    'C',
                    0.50,
                    0.28,
                    95,
                    0.20,
                    105,
                    0.20,
                    0.20,
                    0.08,
                    0.08,
                    0.03,
                    'SURFACED',
                    'LOCAL_IV_RESIDUAL_ABOVE_THRESHOLD',
                    'IV_RICH_LOCAL',
                    '{}'
                );
                """,
                (
                    scanner_run_id,
                    reference_id,
                    option_quote_id,
                ),
            ).lastrowid
        )

        proposal_id = int(
            conn.execute(
                """
                INSERT INTO shadow_structure_proposals (
                    hypothesis_evaluation_id,
                    research_run_id,
                    target_reference_contract_id,
                    underlying,
                    expiration,
                    right,
                    target_strike,
                    builder_family_id,
                    builder_version,
                    builder_rule_version,
                    anomaly_direction,
                    proposal_state,
                    reason_code,
                    structure_id,
                    structure_version,
                    structure_json,
                    entry_pricing_json,
                    risk_currency,
                    max_theoretical_loss_minor,
                    risk_basis,
                    created_at
                )
                VALUES (
                    ?,
                    ?,
                    ?,
                    'AAPL',
                    '2026-09-18',
                    'C',
                    100,
                    'LOCAL_IV_BUTTERFLY_EXPRESSION_V1',
                    '1.0.0',
                    'LOCAL_IV_BUTTERFLY_RULES_V1',
                    'IV_RICH_LOCAL',
                    'PROPOSED',
                    'DEFINED_RISK_STRUCTURE_CONSTRUCTED',
                    'LONG_1_2_1_BUTTERFLY',
                    '1.0.0',
                    ?,
                    '{}',
                    'USD',
                    ?,
                    'THEORETICAL_EXPIRY_PAYOFF_USING_CONSERVATIVE_BID_ASK_ENTRY',
                    '2026-09-01T18:00:07Z'
                );
                """,
                (
                    evaluation_id,
                    run_id,
                    reference_id,
                    json.dumps(
                        {
                            "legs": [
                                {
                                    "reference_contract_id":
                                        reference_id,
                                    "option_quote_id":
                                        option_quote_id,
                                    "strike": 95.0,
                                    "right": "C",
                                    "quantity": 1,
                                    "side": "BUY",
                                    "shares_per_contract": 100,
                                },
                                {
                                    "reference_contract_id":
                                        reference_id,
                                    "option_quote_id":
                                        option_quote_id,
                                    "strike": 100.0,
                                    "right": "C",
                                    "quantity": 2,
                                    "side": "SELL",
                                    "shares_per_contract": 100,
                                },
                                {
                                    "reference_contract_id":
                                        reference_id,
                                    "option_quote_id":
                                        option_quote_id,
                                    "strike": 105.0,
                                    "right": "C",
                                    "quantity": 1,
                                    "side": "BUY",
                                    "shares_per_contract": 100,
                                },
                            ]
                        }
                    ),
                    max_loss_usd_minor,
                ),
            ).lastrowid
        )

        conn.commit()

        return {
            "proposal_id":
                proposal_id,
            "quote_evidence_id":
                quote_evidence_id,
            "greek_evidence_id":
                greek_evidence_id,
        }
    finally:
        conn.close()


def fx():
    return EcbFxObservation(
        provider="ECB",
        base_currency="EUR",
        quote_currency="USD",
        rate=1.20,
        reference_date="2026-09-01",
        observed_at=
            "2026-09-01T12:00:00Z",
        source_url="https://example.test/ecb",
        provenance=
            "ECB_DAILY_REFERENCE_RATE",
    )


def test_under_cap_is_admitted_and_shadow_tracked(
    db_path,
):
    seeded = seed_proposal(
        db_path,
        max_loss_usd_minor=
            20_000,
    )

    result = admit_shadow_proposals(
        fx=fx(),
        proposal_ids=[
            seeded["proposal_id"]
        ],
        db_path=db_path,
    )

    assert result.admitted_count == 1
    assert result.blocked_count == 0

    decision = result.decisions[0]

    assert decision.candidate_id is not None
    assert (
        decision.reserved_risk_eur_minor
        <= 50_000
    )

    conn = get_connection(db_path)

    try:
        candidate = conn.execute(
            """
            SELECT *
            FROM shadow_candidates
            WHERE id = ?;
            """,
            (decision.candidate_id,),
        ).fetchone()

        assert (
            candidate["admission_label"]
            ==
            "CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING"
        )

        state = conn.execute(
            """
            SELECT to_state
            FROM shadow_state_events
            WHERE candidate_id = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (decision.candidate_id,),
        ).fetchone()[0]

        assert state == "SHADOW_TRACKED"

        pin = conn.execute(
            """
            SELECT action
            FROM underlying_pin_events
            WHERE candidate_id = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (decision.candidate_id,),
        ).fetchone()[0]

        assert pin == "PIN"
    finally:
        conn.close()


def test_one_unit_over_cap_is_blocked(
    db_path,
):
    seeded = seed_proposal(
        db_path,
        max_loss_usd_minor=
            70_000,
    )

    result = admit_shadow_proposals(
        fx=fx(),
        proposal_ids=[
            seeded["proposal_id"]
        ],
        db_path=db_path,
    )

    assert result.admitted_count == 0
    assert result.blocked_count == 1
    assert (
        result.decisions[0].reason_code
        ==
        "ONE_UNIT_EXCEEDS_EUR_500_BANKROLL"
    )
    assert (
        result.decisions[0].candidate_id
        is None
    )


def test_admission_is_idempotent_for_same_policy(
    db_path,
):
    seeded = seed_proposal(
        db_path,
        max_loss_usd_minor=
            20_000,
    )

    first = admit_shadow_proposals(
        fx=fx(),
        proposal_ids=[
            seeded["proposal_id"]
        ],
        db_path=db_path,
    )

    second = admit_shadow_proposals(
        fx=fx(),
        proposal_ids=[
            seeded["proposal_id"]
        ],
        db_path=db_path,
    )

    assert (
        first.decisions[0].candidate_id
        == second.decisions[0].candidate_id
    )

    conn = get_connection(db_path)

    try:
        assert conn.execute(
            """
            SELECT COUNT(*)
            FROM shadow_admission_decisions
            WHERE proposal_id = ?;
            """,
            (
                seeded["proposal_id"],
            ),
        ).fetchone()[0] == 1

        assert conn.execute(
            """
            SELECT COUNT(*)
            FROM shadow_candidates;
            """
        ).fetchone()[0] == 1
    finally:
        conn.close()

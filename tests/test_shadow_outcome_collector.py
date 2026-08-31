import json

from src.database.repository import (
    get_connection,
)
from src.research.shadow_outcome_collector import (
    collect_shadow_marks,
)


def seed_active_candidate(
    db_path,
):
    conn = get_connection(db_path)

    try:
        run1 = int(
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
                    'TEST',
                    'hash1',
                    'sha',
                    '2026-09-01T14:00:00Z',
                    '2026-09-01T14:01:00Z',
                    '2026-09-01',
                    'INTRADAY',
                    'COMPLETED'
                );
                """
            ).lastrowid
        )

        ref = int(
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
                    '2026-09-01T14:00:00Z',
                    '2026-09-01T14:00:00Z'
                );
                """,
                (run1,),
            ).lastrowid
        )

        quote_evidence = int(
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
                VALUES (
                    ?,
                    'THETADATA',
                    'THETADATA_QUOTE',
                    'PRESENT',
                    '2026-09-01T14:00:00Z',
                    '2026-09-01T14:00:00Z'
                );
                """,
                (ref,),
            ).lastrowid
        )

        greek_evidence = int(
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
                VALUES (
                    ?,
                    'THETADATA',
                    'THETADATA_GREEKS',
                    'PRESENT',
                    '2026-09-01T14:00:00Z',
                    '2026-09-01T14:00:00Z'
                );
                """,
                (ref,),
            ).lastrowid
        )

        entry_snapshot = int(
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
                    '2026-09-01T14:00:05Z',
                    'AAPL',
                    'THETADATA',
                    ?,
                    '2026-09-01',
                    'INTRADAY',
                    'UNKNOWN',
                    'UNKNOWN'
                );
                """,
                (run1,),
            ).lastrowid
        )

        entry_option_quote_id = int(
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
                    'THETA:ENTRY',
                    'C',
                    100,
                    '2026-09-18',
                    '2026-09-01T10:00:00',
                    4.9,
                    'FETCHED',
                    '2026-09-01T10:00:00',
                    5.0,
                    'FETCHED',
                    '2026-09-01T10:00:00',
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
                (entry_snapshot,),
            ).lastrowid
        )

        if entry_option_quote_id != 1:
            raise AssertionError(
                "Fixture expected first option quote id=1."
            )

        candidate = int(
            conn.execute(
                """
                INSERT INTO shadow_candidates (
                    research_run_id,
                    reference_contract_id,
                    underlying,
                    scanner_family_id,
                    scanner_version,
                    scanner_rule_version,
                    surfaced_at,
                    entry_quote_observation_id,
                    entry_greek_observation_id,
                    quote_freshness_class,
                    greek_quality_class,
                    universe_status,
                    structure_id,
                    structure_version,
                    structure_json,
                    hypothesis_family,
                    hypothesis_version,
                    sizing_policy_version,
                    max_theoretical_loss_minor,
                    cost_model_version,
                    cost_provenance,
                    admission_label
                )
                VALUES (
                    ?, ?, 'AAPL',
                    'TEST', '1', '1',
                    '2026-09-01T14:00:00Z',
                    ?, ?,
                    'FRESH', 'GOOD', 'CONSISTENT',
                    'TEST_SPREAD', '1',
                    ?,
                    'TEST', '1',
                    'SIZING_POLICY_V1',
                    10000,
                    'COST_V1',
                    'ASSUMED',
                    'CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING'
                );
                """,
                (
                    run1,
                    ref,
                    quote_evidence,
                    greek_evidence,
                    json.dumps(
                        {
                            "legs": [
                                {
                                    "option_quote_id": 1,
                                    "strike": 100.0,
                                    "right": "C",
                                    "quantity": 1,
                                    "side": "BUY",
                                    "shares_per_contract": 100,
                                }
                            ]
                        }
                    ),
                ),
            ).lastrowid
        )

        conn.execute(
            """
            INSERT INTO shadow_state_events (
                candidate_id,
                from_state,
                to_state,
                occurred_at,
                actor,
                reason_code
            )
            VALUES (
                ?, NULL, 'SURFACED',
                '2026-09-01T14:00:00Z',
                'SYSTEM', 'TEST'
            );
            """,
            (candidate,),
        )

        for from_state, to_state in [
            ("SURFACED", "INVESTIGATED"),
            ("INVESTIGATED", "DECIDED"),
            ("DECIDED", "SHADOW_TRACKED"),
        ]:
            conn.execute(
                """
                INSERT INTO shadow_state_events (
                    candidate_id,
                    from_state,
                    to_state,
                    occurred_at,
                    actor,
                    reason_code
                )
                VALUES (
                    ?, ?, ?,
                    '2026-09-01T14:00:00Z',
                    'SYSTEM', 'TEST'
                );
                """,
                (
                    candidate,
                    from_state,
                    to_state,
                ),
            )

        fx_id = int(
            conn.execute(
                """
                INSERT INTO fx_observations (
                    provider,
                    base_currency,
                    quote_currency,
                    rate,
                    reference_date,
                    observed_at,
                    provenance
                )
                VALUES (
                    'ECB',
                    'EUR',
                    'USD',
                    1.20,
                    '2026-09-01',
                    '2026-09-01T12:00:00Z',
                    'TEST'
                );
                """
            ).lastrowid
        )

        proposal = int(
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
                    'TEST', '1', '1',
                    'TEST', '1',
                    ?, '{}',
                    '2026-09-01T14:00:00Z',
                    1, 1, 1
                );
                """,
                (
                    run1,
                    "a" * 64,
                ),
            ).lastrowid
        )

        evaluation = int(
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
                    residual_threshold,
                    evaluation_state,
                    reason_code,
                    surfaced_direction,
                    evidence_json
                )
                VALUES (
                    ?, ?, 1,
                    'AAPL',
                    '2026-09-18',
                    100,
                    'C',
                    0.5,
                    0.2,
                    0.03,
                    'SURFACED',
                    'TEST',
                    'IV_RICH_LOCAL',
                    '{}'
                );
                """,
                (
                    proposal,
                    ref,
                ),
            ).lastrowid
        )

        structure_proposal = int(
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
                    ?, ?, ?,
                    'AAPL',
                    '2026-09-18',
                    'C',
                    100,
                    'TEST', '1', '1',
                    'IV_RICH_LOCAL',
                    'PROPOSED',
                    'TEST',
                    'TEST_SPREAD',
                    '1',
                    ?,
                    ?,
                    'USD',
                    10000,
                    'TEST',
                    '2026-09-01T14:00:00Z'
                );
                """,
                (
                    evaluation,
                    run1,
                    ref,
                    json.dumps(
                        {
                            "legs": [
                                {
                                    "option_quote_id": 1,
                                    "strike": 100.0,
                                    "right": "C",
                                    "quantity": 1,
                                    "side": "BUY",
                                    "shares_per_contract": 100,
                                }
                            ]
                        }
                    ),
                    json.dumps(
                        {
                            "legs": [
                                {
                                    "option_quote_id": 1,
                                    "side": "BUY",
                                    "quantity": 1,
                                    "entry_price": 5.0,
                                }
                            ]
                        }
                    ),
                ),
            ).lastrowid
        )

        conn.execute(
            """
            INSERT INTO shadow_admission_decisions (
                proposal_id,
                fx_observation_id,
                candidate_id,
                sizing_policy_version,
                cost_model_version,
                cost_provenance,
                proposal_max_loss_usd_minor,
                estimated_cost_usd_minor,
                reserved_risk_usd_minor,
                converted_max_loss_eur_minor,
                estimated_cost_eur_minor,
                reserved_risk_eur_minor,
                bankroll_cap_eur_minor,
                decision,
                reason_code,
                decided_at,
                evidence_json
            )
            VALUES (
                ?, ?, ?,
                'SIZING_POLICY_V1',
                'COST_V1',
                'ASSUMED',
                10000,
                600,
                10600,
                8333,
                500,
                8833,
                50000,
                'ADMITTED',
                'TEST',
                '2026-09-01T14:00:00Z',
                '{}'
            );
            """,
            (
                structure_proposal,
                fx_id,
                candidate,
            ),
        )

        run2 = int(
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
                    'TEST',
                    'hash2',
                    'sha',
                    '2026-09-01T14:15:00Z',
                    '2026-09-01T14:16:00Z',
                    '2026-09-01',
                    'INTRADAY',
                    'COMPLETED'
                );
                """
            ).lastrowid
        )

        snapshot = int(
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
                    '2026-09-01T14:15:05Z',
                    'AAPL',
                    'THETADATA',
                    ?,
                    '2026-09-01',
                    'INTRADAY',
                    'UNKNOWN',
                    'UNKNOWN'
                );
                """,
                (run2,),
            ).lastrowid
        )

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
                '2026-09-01T10:15:00',
                5.4,
                'FETCHED',
                '2026-09-01T10:15:00',
                5.5,
                'FETCHED',
                '2026-09-01T10:15:00',
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
            (snapshot,),
        )

        conn.commit()

        return (
            candidate,
            run2,
        )
    finally:
        conn.close()


def test_collects_conservative_long_mark(
    db_path,
):
    candidate_id, run2 = seed_active_candidate(
        db_path
    )

    result = collect_shadow_marks(
        research_run_id=run2,
        db_path=db_path,
    )

    assert result.active_candidate_count == 1
    assert result.marks_written == 1
    assert result.complete_marks == 1

    mark = result.marks[0]

    # Entry long at $5.00 = -$500.
    # Conservative liquidation at bid $5.40 = +$540.
    # Gross = +$40 = 4000 cents.
    assert mark.gross_pnl_usd_minor == 4000

    # Frozen round-trip cost reserve is $6.00.
    assert (
        mark.estimated_net_pnl_usd_minor
        == 3400
    )

    conn = get_connection(db_path)

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM shadow_mark_observations
            WHERE candidate_id = ?;
            """,
            (candidate_id,),
        ).fetchall()

        assert len(rows) == 1
        assert (
            rows[0]["quality_state"]
            ==
            "COMPLETE_UNVERIFIED_FRESHNESS"
        )
    finally:
        conn.close()

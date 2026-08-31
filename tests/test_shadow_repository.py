import sqlite3

import pytest

from src.database.repository import (
    append_shadow_outcome_observation,
    append_shadow_state_event,
    append_underlying_pin_event,
    create_listing_reference_contract,
    create_shadow_candidate,
    get_connection,
    get_shadow_candidate,
    record_provider_observation_availability,
)


def create_run(db_path):
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO research_runs (
                cohort_id,
                started_at,
                code_git_sha,
                preregistration_hash,
                us_session_date,
                us_session_state,
                status
            )
            VALUES (
                'SHADOW_TEST',
                '2026-08-31T12:00:00Z',
                'abc',
                'hash',
                '2026-08-31',
                'INTRADAY',
                'STARTED'
            );
            """
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def base_reference(run_id):
    return {
        "research_run_id": run_id,
        "provider": "MASSIVE",
        "underlying": "AAPL",
        "provider_contract_id": "O:AAPL260914C00250000",
        "option_symbol": "O:AAPL260914C00250000",
        "expiration": "2026-09-14",
        "strike": 250.0,
        "right": "C",
        "exercise_style": "american",
        "shares_per_contract": 100,
        "primary_exchange": "X",
        "observed_at": "2026-08-31T12:00:00Z",
    }


def base_candidate(run_id, reference_id, quote_id=None, greek_id=None):
    return {
        "research_run_id": run_id,
        "reference_contract_id": reference_id,
        "underlying": "AAPL",
        "scanner_family_id": "TEST_SCANNER",
        "scanner_version": "scanner_v1",
        "scanner_rule_version": "rule_v1",
        "surfaced_at": "2026-08-31T12:01:00Z",
        "entry_quote_observation_id": quote_id,
        "entry_greek_observation_id": greek_id,
        "quote_freshness_class": "FRESH",
        "greek_quality_class": "GOOD",
        "universe_status": "CONSISTENT",
        "structure_id": "LONG_CALL",
        "structure_version": "v1",
        "hypothesis_family": "TEST",
        "hypothesis_version": "v1",
        "sizing_policy_version": "SIZING_POLICY_V1",
        "max_theoretical_loss_minor": 25000,
    }


def test_reference_observation_shadow_roundtrip(db_path):
    run_id = create_run(db_path)
    reference_id = create_listing_reference_contract(
        base_reference(run_id),
        db_path=db_path,
    )

    quote_id = record_provider_observation_availability(
        {
            "reference_contract_id": reference_id,
            "provider": "THETADATA",
            "evidence_family": "THETADATA_QUOTE",
            "state": "PRESENT",
            "observed_at": "2026-08-31T12:00:30Z",
            "raw_timestamp": "2026-08-31 08:00:30",
        },
        db_path=db_path,
    )

    greek_id = record_provider_observation_availability(
        {
            "reference_contract_id": reference_id,
            "provider": "THETADATA",
            "evidence_family": "THETADATA_GREEKS",
            "state": "PRESENT",
            "observed_at": "2026-08-31T12:00:31Z",
        },
        db_path=db_path,
    )

    candidate_id = create_shadow_candidate(
        base_candidate(
            run_id,
            reference_id,
            quote_id,
            greek_id,
        ),
        db_path=db_path,
    )

    append_shadow_state_event(
        candidate_id,
        to_state="INVESTIGATED",
        occurred_at="2026-08-31T12:02:00Z",
        actor="USER",
        db_path=db_path,
    )
    append_shadow_state_event(
        candidate_id,
        to_state="DECIDED",
        occurred_at="2026-08-31T12:03:00Z",
        actor="USER",
        db_path=db_path,
    )
    append_shadow_state_event(
        candidate_id,
        to_state="SHADOW_TRACKED",
        occurred_at="2026-08-31T12:04:00Z",
        actor="USER",
        db_path=db_path,
    )

    append_underlying_pin_event(
        underlying="AAPL",
        candidate_id=candidate_id,
        action="PIN",
        occurred_at="2026-08-31T12:04:01Z",
        reason="Active shadow candidate.",
        db_path=db_path,
    )

    append_shadow_outcome_observation(
        {
            "candidate_id": candidate_id,
            "horizon": "NEXT_ELIGIBLE_SESSION",
            "provider": "THETADATA",
            "observed_at": "2026-09-01T14:00:00Z",
            "bid": 2.40,
            "ask": 2.60,
            "mid": 2.50,
            "underlying_price": 251.0,
            "pnl_minor": 1000,
            "return_fraction": 0.04,
            "quality_state": "FRESH",
        },
        db_path=db_path,
    )

    result = get_shadow_candidate(
        candidate_id,
        db_path=db_path,
    )

    assert result is not None
    assert result["candidate"]["underlying"] == "AAPL"
    assert result["candidate"]["admission_label"] == (
        "CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING"
    )
    assert [
        event["to_state"]
        for event in result["state_events"]
    ] == [
        "SURFACED",
        "INVESTIGATED",
        "DECIDED",
        "SHADOW_TRACKED",
    ]
    assert len(result["outcomes"]) == 1
    assert result["pin_events"][-1]["action"] == "PIN"


def test_invalid_lifecycle_transition_fails_closed(db_path):
    run_id = create_run(db_path)
    reference_id = create_listing_reference_contract(
        base_reference(run_id),
        db_path=db_path,
    )
    candidate_id = create_shadow_candidate(
        base_candidate(run_id, reference_id),
        db_path=db_path,
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="Invalid shadow lifecycle transition",
    ):
        append_shadow_state_event(
            candidate_id,
            to_state="SHADOW_TRACKED",
            occurred_at="2026-08-31T12:02:00Z",
            actor="USER",
            db_path=db_path,
        )


def test_shadow_candidate_is_immutable(db_path):
    run_id = create_run(db_path)
    reference_id = create_listing_reference_contract(
        base_reference(run_id),
        db_path=db_path,
    )
    candidate_id = create_shadow_candidate(
        base_candidate(run_id, reference_id),
        db_path=db_path,
    )

    conn = get_connection(db_path)
    try:
        with pytest.raises(
            sqlite3.IntegrityError,
            match="immutable",
        ):
            conn.execute(
                """
                UPDATE shadow_candidates
                SET max_theoretical_loss_minor = 1
                WHERE id = ?;
                """,
                (candidate_id,),
            )
    finally:
        conn.close()


def test_pin_actions_must_alternate(db_path):
    run_id = create_run(db_path)
    reference_id = create_listing_reference_contract(
        base_reference(run_id),
        db_path=db_path,
    )
    candidate_id = create_shadow_candidate(
        base_candidate(run_id, reference_id),
        db_path=db_path,
    )

    append_underlying_pin_event(
        underlying="AAPL",
        candidate_id=candidate_id,
        action="PIN",
        occurred_at="2026-08-31T12:02:00Z",
        reason="Active.",
        db_path=db_path,
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="must alternate",
    ):
        append_underlying_pin_event(
            underlying="AAPL",
            candidate_id=candidate_id,
            action="PIN",
            occurred_at="2026-08-31T12:03:00Z",
            reason="Duplicate.",
            db_path=db_path,
        )


def test_outcome_horizon_is_unique(db_path):
    run_id = create_run(db_path)
    reference_id = create_listing_reference_contract(
        base_reference(run_id),
        db_path=db_path,
    )
    candidate_id = create_shadow_candidate(
        base_candidate(run_id, reference_id),
        db_path=db_path,
    )

    observation = {
        "candidate_id": candidate_id,
        "horizon": "NEXT_ELIGIBLE_SESSION",
        "provider": "THETADATA",
        "observed_at": "2026-09-01T14:00:00Z",
    }

    append_shadow_outcome_observation(
        observation,
        db_path=db_path,
    )

    with pytest.raises(sqlite3.IntegrityError):
        append_shadow_outcome_observation(
            observation,
            db_path=db_path,
        )

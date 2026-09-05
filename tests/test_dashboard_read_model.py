from src.dashboard.read_model import (
    load_command_deck,
)
from src.database.repository import (
    EXPECTED_SCHEMA_VERSION,
    get_connection,
)


def test_command_deck_loads_empty_current_schema(
    db_path,
):
    snapshot = load_command_deck(
        db_path
    )

    assert snapshot["ready"] is True
    assert (
        snapshot["database"][
            "schema_version"
        ]
        == EXPECTED_SCHEMA_VERSION
    )
    assert (
        snapshot["database"][
            "quick_check"
        ]
        == "ok"
    )
    assert (
        snapshot["prospective"][
            "independent_dates"
        ]
        == 0
    )
    assert (
        snapshot["research_counts"][
            "shadow_candidates"
        ]
        == 0
    )
    assert snapshot["decision_desk_candidates"] == []


def test_command_deck_reads_daemon_and_run_state(
    db_path,
):
    conn = get_connection(
        db_path
    )

    try:
        with conn:
            cursor = conn.execute(
                '''
                INSERT INTO research_runs(
                    cohort_id,
                    preregistration_hash,
                    code_git_sha,
                    started_at,
                    ended_at,
                    us_session_date,
                    us_session_state,
                    status,
                    attempted_underlyings,
                    succeeded_underlyings,
                    failed_underlyings
                )
                VALUES(
                    'INDEPENDENT_RESEARCH_V1',
                    'test-hash',
                    'test-sha',
                    '2026-09-04T14:00:00Z',
                    '2026-09-04T14:03:00Z',
                    '2026-09-04',
                    'INTRADAY',
                    'COMPLETED',
                    26,
                    26,
                    0
                );
                '''
            )

            run_id = int(
                cursor.lastrowid
            )

            conn.execute(
                '''
                INSERT INTO research_daemon_iterations(
                    owner_token,
                    scheduled_for,
                    started_at,
                    completed_at,
                    status,
                    research_run_id,
                    proposals_count,
                    admitted_count,
                    blocked_count,
                    outcome_mark_count
                )
                VALUES(
                    'test-owner',
                    '2026-09-04T14:00:00Z',
                    '2026-09-04T14:00:00Z',
                    '2026-09-04T14:03:00Z',
                    'COMPLETED',
                    ?,
                    2,
                    1,
                    1,
                    4
                );
                ''',
                (run_id,),
            )

    finally:
        conn.close()

    snapshot = load_command_deck(
        db_path
    )

    assert (
        snapshot["latest_run"]["id"]
        == run_id
    )
    assert (
        snapshot["latest_iteration"][
            "status"
        ]
        == "COMPLETED"
    )
    assert (
        snapshot["session"][
            "attempted_underlyings"
        ]
        == 26
    )
    assert (
        snapshot["session"][
            "failed_underlyings"
        ]
        == 0
    )

def test_command_deck_refuses_foreign_key_violation(
    db_path,
):
    conn = get_connection(db_path)

    try:
        conn.execute(
            "PRAGMA foreign_keys = OFF;"
        )

        with conn:
            conn.execute(
                """
                INSERT INTO research_daemon_iterations(
                    owner_token,
                    scheduled_for,
                    started_at,
                    status,
                    research_run_id
                )
                VALUES(
                    'bad',
                    '2026-09-04T14:00:00Z',
                    '2026-09-04T14:00:00Z',
                    'RUNNING',
                    999999
                );
                """
            )

    finally:
        conn.close()

    snapshot = load_command_deck(
        db_path
    )

    assert snapshot["ready"] is False
    assert (
        snapshot["reason"]
        == "DATABASE_INTEGRITY_FAILURE"
    )


def test_command_deck_provider_probe_is_opt_in(db_path, monkeypatch):
    import src.dashboard.read_model as module

    called = []
    monkeypatch.setattr(
        module,
        "probe_theta_terminal",
        lambda: called.append(True),
    )

    snapshot = module.load_command_deck(db_path)

    assert snapshot["theta_health"]["state"] == "NOT_PROBED"
    assert called == []


def test_command_deck_can_include_theta_health(db_path, monkeypatch):
    import src.dashboard.read_model as module

    health = type(
        "Health",
        (),
        {
            "as_dict": lambda self: {
                "state": "READY",
                "ready": True,
                "latency_ms": 12.0,
            }
        },
    )()
    monkeypatch.setattr(
        module,
        "probe_theta_terminal",
        lambda: health,
    )

    snapshot = module.load_command_deck(
        db_path,
        include_provider_health=True,
    )

    assert snapshot["theta_health"]["state"] == "READY"


def test_command_deck_exposes_shadow_candidate_followup(db_path):
    conn = get_connection(db_path)

    try:
        with conn:
            run_cursor = conn.execute(
                """
                INSERT INTO research_runs(
                    cohort_id,
                    preregistration_hash,
                    code_git_sha,
                    started_at,
                    ended_at,
                    us_session_date,
                    us_session_state,
                    status,
                    attempted_underlyings,
                    succeeded_underlyings,
                    failed_underlyings
                )
                VALUES(
                    'INDEPENDENT_RESEARCH_V1',
                    'shadow-hash',
                    'shadow-sha',
                    '2026-09-04T14:00:00Z',
                    '2026-09-04T14:03:00Z',
                    '2026-09-04',
                    'INTRADAY',
                    'COMPLETED',
                    1,
                    1,
                    0
                );
                """
            )
            run_id = int(run_cursor.lastrowid)

            reference_cursor = conn.execute(
                """
                INSERT INTO listing_reference_contracts(
                    research_run_id,
                    provider,
                    underlying,
                    provider_contract_id,
                    option_symbol,
                    expiration,
                    strike,
                    right,
                    observed_at,
                    ingested_at
                )
                VALUES(
                    ?,
                    'MASSIVE',
                    'SPY',
                    'SPY_TEST_CONTRACT',
                    'SPY_TEST',
                    '2026-09-11',
                    650.0,
                    'C',
                    '2026-09-04T14:00:00Z',
                    '2026-09-04T14:00:01Z'
                );
                """,
                (run_id,),
            )
            reference_id = int(reference_cursor.lastrowid)

            candidate_cursor = conn.execute(
                """
                INSERT INTO shadow_candidates(
                    research_run_id,
                    reference_contract_id,
                    underlying,
                    scanner_family_id,
                    scanner_version,
                    scanner_rule_version,
                    surfaced_at,
                    universe_status,
                    structure_id,
                    structure_version,
                    hypothesis_family,
                    hypothesis_version,
                    sizing_policy_version,
                    max_theoretical_loss_minor,
                    admission_label
                )
                VALUES(
                    ?,
                    ?,
                    'SPY',
                    'LOCAL_SURFACE_V2',
                    '2.0',
                    'RULES_V1',
                    '2026-09-04T14:01:00Z',
                    'CONSISTENT',
                    'DEFINED_RISK_TEST',
                    '1',
                    'H1',
                    '1',
                    'V1',
                    2500,
                    'CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING'
                );
                """,
                (run_id, reference_id),
            )
            candidate_id = int(candidate_cursor.lastrowid)

            conn.execute(
                """
                INSERT INTO shadow_mark_observations(
                    candidate_id,
                    research_run_id,
                    observed_at,
                    provider,
                    structure_mark_usd_minor,
                    gross_pnl_usd_minor,
                    estimated_net_pnl_usd_minor,
                    gross_pnl_eur_minor,
                    estimated_net_pnl_eur_minor,
                    quality_state,
                    evidence_json,
                    measurement_role,
                    outcome_eligible
                )
                VALUES(
                    ?,
                    ?,
                    '2026-09-04T15:00:00Z',
                    'THETADATA',
                    1200,
                    250,
                    200,
                    220,
                    175,
                    'COMPLETE_UNVERIFIED_FRESHNESS',
                    '{}',
                    'INDEPENDENT_LEG_LIQUIDATION_STRESS',
                    0
                );
                """,
                (candidate_id, run_id),
            )
    finally:
        conn.close()

    snapshot = load_command_deck(db_path)

    assert snapshot["shadow_tracking"]["mark_observations"] == 1
    assert snapshot["shadow_tracking"]["marked_candidates"] == 1
    assert snapshot["shadow_tracking"]["validated_outcomes"] == 0

    mark = snapshot["shadow_mark_history"][0]
    assert mark["candidate_id"] == candidate_id
    assert mark["underlying"] == "SPY"
    assert mark["estimated_net_pnl_eur_minor"] == 175
    assert mark["outcome_eligible"] == 0

    followup = snapshot["shadow_candidate_followup"][0]
    assert followup["candidate_id"] == candidate_id
    assert followup["mark_count"] == 1
    assert followup["latest_estimated_net_pnl_eur_minor"] == 175
    assert followup["latest_measurement_role"] == "INDEPENDENT_LEG_LIQUIDATION_STRESS"

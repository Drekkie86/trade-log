from src.database.repository import get_connection
from src.research.shadow_admission import admit_shadow_proposals
from src.research.shadow_lifecycle_runtime import advance_shadow_lifecycle
from tests._shadow_admission_seed import fx, seed_proposal


def _candidate(db_path):
    seeded = seed_proposal(db_path, max_loss_usd_minor=20_000)
    decision = admit_shadow_proposals(
        fx=fx(),
        proposal_ids=[seeded["proposal_id"]],
        db_path=db_path,
    ).decisions[0]
    assert decision.candidate_id is not None
    return decision


def _research_run(db_path, *, session_date: str, suffix: str) -> int:
    conn = get_connection(db_path)
    try:
        with conn:
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
                ) VALUES (
                    'INDEPENDENT_RESEARCH_RUNNER_V1',
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    'INTRADAY',
                    'COMPLETED'
                );
                """,
                (
                    f"hash-{suffix}",
                    f"sha-{suffix}",
                    f"{session_date}T20:00:00Z",
                    f"{session_date}T20:01:00Z",
                    session_date,
                ),
            )
        return int(cursor.lastrowid)
    finally:
        conn.close()


def _state(db_path, candidate_id: int) -> str:
    conn = get_connection(db_path)
    try:
        return str(
            conn.execute(
                """
                SELECT to_state
                FROM shadow_state_events
                WHERE candidate_id = ?
                ORDER BY id DESC
                LIMIT 1;
                """,
                (candidate_id,),
            ).fetchone()[0]
        )
    finally:
        conn.close()


def test_expiration_day_remains_trackable(db_path):
    decision = _candidate(db_path)
    run_id = _research_run(
        db_path,
        session_date="2026-09-18",
        suffix="expiry-day",
    )

    result = advance_shadow_lifecycle(
        research_run_id=run_id,
        db_path=db_path,
    )

    assert result.closed_count == 0
    assert result.scored_count == 0
    assert _state(db_path, decision.candidate_id) == "SHADOW_TRACKED"


def test_candidate_closes_and_unpins_after_expiration_session(db_path):
    decision = _candidate(db_path)
    run_id = _research_run(
        db_path,
        session_date="2026-09-19",
        suffix="post-expiry",
    )

    first = advance_shadow_lifecycle(
        research_run_id=run_id,
        db_path=db_path,
    )
    second = advance_shadow_lifecycle(
        research_run_id=run_id,
        db_path=db_path,
    )

    assert first.closed_count == 1
    assert first.unpinned_count == 1
    assert first.scored_count == 0
    assert second.closed_count == 0
    assert second.unpinned_count == 0
    assert second.scored_count == 0
    assert _state(db_path, decision.candidate_id) == "CLOSED_OR_EXPIRED"

    conn = get_connection(db_path)
    try:
        latest_pin = conn.execute(
            """
            SELECT action
            FROM underlying_pin_events
            WHERE candidate_id = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (decision.candidate_id,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert latest_pin == "UNPIN"


def test_intraday_marks_do_not_score_closed_candidate(db_path):
    decision = _candidate(db_path)
    close_run = _research_run(
        db_path,
        session_date="2026-09-19",
        suffix="close",
    )
    advance_shadow_lifecycle(research_run_id=close_run, db_path=db_path)

    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO shadow_mark_observations (
                    candidate_id,
                    research_run_id,
                    observed_at,
                    provider,
                    structure_mark_usd_minor,
                    gross_pnl_usd_minor,
                    estimated_net_pnl_usd_minor,
                    gross_pnl_eur_minor,
                    estimated_net_pnl_eur_minor,
                    entry_fx_observation_id,
                    quality_state,
                    measurement_role,
                    outcome_eligible,
                    evidence_json
                ) VALUES (
                    ?, ?, '2026-09-19T20:01:00Z', 'THETADATA',
                    0, 0, 0, 0, 0, ?,
                    'COMPLETE_UNVERIFIED_FRESHNESS',
                    'INDEPENDENT_LEG_LIQUIDATION_STRESS', 0, '{}'
                );
                """,
                (
                    decision.candidate_id,
                    close_run,
                    decision.fx_observation_id,
                ),
            )
    finally:
        conn.close()

    result = advance_shadow_lifecycle(
        research_run_id=close_run,
        db_path=db_path,
    )
    assert result.scored_count == 0
    assert _state(db_path, decision.candidate_id) == "CLOSED_OR_EXPIRED"


def test_validated_package_outcome_allows_scoring_after_close(db_path):
    decision = _candidate(db_path)
    close_run = _research_run(
        db_path,
        session_date="2026-09-19",
        suffix="close-valid",
    )
    advance_shadow_lifecycle(research_run_id=close_run, db_path=db_path)
    validation_run = _research_run(
        db_path,
        session_date="2026-09-22",
        suffix="validated-package",
    )

    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO shadow_mark_observations (
                    candidate_id,
                    research_run_id,
                    observed_at,
                    provider,
                    structure_mark_usd_minor,
                    gross_pnl_usd_minor,
                    estimated_net_pnl_usd_minor,
                    gross_pnl_eur_minor,
                    estimated_net_pnl_eur_minor,
                    entry_fx_observation_id,
                    quality_state,
                    measurement_role,
                    outcome_eligible,
                    evidence_json
                ) VALUES (
                    ?, ?, '2026-09-22T20:01:00Z', 'THETADATA',
                    0, 1000, 900, 800, 700, ?,
                    'COMPLETE_UNVERIFIED_FRESHNESS',
                    'VALIDATED_PACKAGE_OUTCOME', 1, '{}'
                );
                """,
                (
                    decision.candidate_id,
                    validation_run,
                    decision.fx_observation_id,
                ),
            )
    finally:
        conn.close()

    result = advance_shadow_lifecycle(
        research_run_id=validation_run,
        db_path=db_path,
    )

    assert result.scored_count == 1
    assert _state(db_path, decision.candidate_id) == "SCORED"

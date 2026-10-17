"""Prospective expiry-intrinsic outcomes (migration 035 + writer + wiring)."""
import json
import sqlite3

import pytest

from src.database.repository import get_connection
from src.research.shadow_expiry_outcome_v1 import (
    MEASUREMENT_ROLE,
    SETTLEMENT_BASIS,
    record_shadow_expiry_outcomes,
)
from src.research.shadow_lifecycle_runtime import advance_shadow_lifecycle
from tests.test_shadow_outcome_collector import seed_active_candidate

# Seed economics (tests/test_shadow_outcome_collector.seed_active_candidate):
#   long 1 x AAPL 100 C, expiry 2026-09-18, entry 5.00 -> cashflow -50000 minor
#   assumed cost 600 minor, EUR/USD 1.20, max theoretical loss 10000 minor.


def _insert_run(conn, *, started, session_date, status="COMPLETED"):
    return int(conn.execute(
        """
        INSERT INTO research_runs (cohort_id, preregistration_hash, code_git_sha,
            started_at, ended_at, us_session_date, us_session_state, status)
        VALUES ('TEST','hash1','sha',?,?,?,'INTRADAY',?);
        """,
        (started, started, session_date, status),
    ).lastrowid)


def _insert_snapshot(conn, *, run_id, captured_at, session_date, price):
    return int(conn.execute(
        """
        INSERT INTO market_snapshots (captured_at, underlying, provider, research_run_id,
            us_session_date, us_session_state, underlying_source, fx_source, underlying_price)
        VALUES (?, 'AAPL', 'THETADATA', ?, ?, 'INTRADAY', 'FETCHED', 'UNKNOWN', ?);
        """,
        (captured_at, run_id, session_date, price),
    ).lastrowid)


def _outcome(db_path, candidate_id):
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM shadow_expiry_outcomes_v1 WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        return None if row is None else dict(row)
    finally:
        conn.close()


def test_not_due_before_expiration_session_has_passed(db_path):
    candidate_id, run2 = seed_active_candidate(db_path)  # run2 is 2026-09-01
    conn = get_connection(db_path)
    try:
        expiry_day_run = _insert_run(conn, started="2026-09-18T19:00:00Z", session_date="2026-09-18")
        conn.commit()
    finally:
        conn.close()
    # Expiration day itself: candidate still trackable, no outcome yet.
    res = record_shadow_expiry_outcomes(research_run_id=expiry_day_run, db_path=db_path)
    assert res.candidates_due == 0
    assert _outcome(db_path, candidate_id) is None


def test_resolved_outcome_arithmetic_in_the_money(db_path):
    candidate_id, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        expiry_run = _insert_run(conn, started="2026-09-18T19:45:00Z", session_date="2026-09-18")
        # Two snapshots on expiry day; the LATER one must be used.
        _insert_snapshot(conn, run_id=expiry_run, captured_at="2026-09-18T18:00:00Z",
                         session_date="2026-09-18", price=101.0)
        _insert_snapshot(conn, run_id=expiry_run, captured_at="2026-09-18T19:45:00Z",
                         session_date="2026-09-18", price=108.0)
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        conn.commit()
    finally:
        conn.close()

    res = record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    assert (res.candidates_due, res.resolved_written, res.unresolved_written) == (1, 1, 0)

    o = _outcome(db_path, candidate_id)
    assert o["outcome_state"] == "RESOLVED"
    assert o["measurement_role"] == MEASUREMENT_ROLE
    assert o["settlement_basis"] == SETTLEMENT_BASIS
    assert o["terminal_underlying_price"] == 108.0
    # intrinsic (108-100) * 100 shares = $800 -> 80000 minor
    assert o["terminal_structure_value_usd_minor"] == 80000
    assert o["entry_cashflow_usd_minor"] == -50000
    assert o["gross_pnl_usd_minor"] == 30000
    assert o["estimated_net_pnl_usd_minor"] == 30000 - 600
    assert o["gross_pnl_eur_minor"] == round(30000 / 1.20)
    assert o["estimated_net_pnl_eur_minor"] == round(29400 / 1.20)
    assert o["max_theoretical_loss_usd_minor"] == 10000
    evidence = json.loads(o["evidence_json"])
    assert evidence["snapshot"]["underlying_price"] == 108.0
    assert "not the official settlement" in evidence["settlement_note"]


def test_resolved_outcome_out_of_the_money_is_full_defined_loss(db_path):
    candidate_id, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        expiry_run = _insert_run(conn, started="2026-09-18T19:45:00Z", session_date="2026-09-18")
        _insert_snapshot(conn, run_id=expiry_run, captured_at="2026-09-18T19:45:00Z",
                         session_date="2026-09-18", price=95.0)
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        conn.commit()
    finally:
        conn.close()
    record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    o = _outcome(db_path, candidate_id)
    assert o["terminal_structure_value_usd_minor"] == 0
    assert o["gross_pnl_usd_minor"] == -50000
    assert o["estimated_net_pnl_usd_minor"] == -50600


def test_unresolved_when_no_expiry_session_snapshot(db_path):
    candidate_id, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        conn.commit()
    finally:
        conn.close()
    res = record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    assert (res.resolved_written, res.unresolved_written) == (0, 1)
    o = _outcome(db_path, candidate_id)
    assert o["outcome_state"] == "UNRESOLVED"
    assert o["reason_code"] == "MISSING_EXPIRY_SESSION_UNDERLYING_SNAPSHOT"
    assert o["estimated_net_pnl_eur_minor"] is None


def test_idempotent_one_row_per_candidate(db_path):
    candidate_id, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        later = _insert_run(conn, started="2026-09-22T14:00:00Z", session_date="2026-09-22")
        conn.commit()
    finally:
        conn.close()
    record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    res = record_shadow_expiry_outcomes(research_run_id=later, db_path=db_path)
    assert res.candidates_due == 0
    conn = get_connection(db_path)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM shadow_expiry_outcomes_v1 WHERE candidate_id=?", (candidate_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_stuck_shadow_tracked_candidate_still_gets_outcome(db_path):
    """Lifecycle state is not a filter: a candidate the lifecycle failed to
    close (the dashboard's stale-tracked WARN) still receives its outcome."""
    candidate_id, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        conn.commit()
        state = conn.execute(
            "SELECT to_state FROM shadow_state_events WHERE candidate_id=? ORDER BY id DESC LIMIT 1",
            (candidate_id,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert state == "SHADOW_TRACKED"
    res = record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    assert res.candidates_due == 1


def test_scoring_contract_untouched(db_path):
    """Recording an expiry outcome never promotes the candidate to SCORED."""
    candidate_id, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        expiry_run = _insert_run(conn, started="2026-09-18T19:45:00Z", session_date="2026-09-18")
        _insert_snapshot(conn, run_id=expiry_run, captured_at="2026-09-18T19:45:00Z",
                         session_date="2026-09-18", price=108.0)
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        conn.commit()
    finally:
        conn.close()
    advance_shadow_lifecycle(research_run_id=after, db_path=db_path)
    record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    r = advance_shadow_lifecycle(research_run_id=after, db_path=db_path)
    assert r.scored_count == 0
    conn = get_connection(db_path)
    try:
        state = conn.execute(
            "SELECT to_state FROM shadow_state_events WHERE candidate_id=? ORDER BY id DESC LIMIT 1",
            (candidate_id,),
        ).fetchone()[0]
        validated = conn.execute(
            "SELECT COUNT(*) FROM shadow_mark_observations WHERE outcome_eligible=1"
        ).fetchone()[0]
    finally:
        conn.close()
    assert state == "CLOSED_OR_EXPIRED"
    assert validated == 0


def test_schema_guards(db_path):
    candidate_id, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        conn.commit()
        base = dict(candidate_id=candidate_id, research_run_id=after,
                    recorded_at="x", expiration="2026-09-18", evidence_json="{}")

        def ins(**extra):
            cols = {**base, **extra}
            conn.execute(
                f"INSERT INTO shadow_expiry_outcomes_v1 ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' * len(cols))})", tuple(cols.values()))

        # Wrong role / basis rejected.
        with pytest.raises(sqlite3.IntegrityError):
            ins(outcome_state="UNRESOLVED", reason_code="X", measurement_role="VALIDATED_PACKAGE_OUTCOME")
        with pytest.raises(sqlite3.IntegrityError):
            ins(outcome_state="UNRESOLVED", reason_code="X", settlement_basis="OFFICIAL_SETTLEMENT")
        # RESOLVED without arithmetic rejected; RESOLVED with broken identity rejected.
        with pytest.raises(sqlite3.IntegrityError):
            ins(outcome_state="RESOLVED", reason_code="X")
        with pytest.raises(sqlite3.IntegrityError):
            ins(outcome_state="RESOLVED", reason_code="X", snapshot_id=1,
                terminal_underlying_price=1.0, entry_cashflow_usd_minor=-1, terminal_structure_value_usd_minor=1,
                estimated_cost_usd_minor=0, gross_pnl_usd_minor=5, estimated_net_pnl_usd_minor=5,
                gross_pnl_eur_minor=5, estimated_net_pnl_eur_minor=5, entry_fx_observation_id=1, entry_eur_to_usd=1.0)
        # Non-admitted candidate rejected.
        conn.execute(
            """INSERT INTO shadow_candidates (research_run_id, reference_contract_id, underlying,
               scanner_family_id, scanner_version, scanner_rule_version, surfaced_at,
               quote_freshness_class, greek_quality_class, universe_status, structure_id, structure_version,
               structure_json, hypothesis_family, hypothesis_version, sizing_policy_version,
               max_theoretical_loss_minor, cost_model_version, cost_provenance, admission_label)
               SELECT research_run_id, reference_contract_id, underlying, scanner_family_id, scanner_version,
               scanner_rule_version, surfaced_at, quote_freshness_class, greek_quality_class, universe_status,
               structure_id, structure_version, structure_json, hypothesis_family, hypothesis_version,
               sizing_policy_version, max_theoretical_loss_minor, cost_model_version, cost_provenance,
               admission_label FROM shadow_candidates WHERE id=?""", (candidate_id,))
        other = conn.execute("SELECT MAX(id) FROM shadow_candidates").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="admitted"):
            ins(candidate_id=other, outcome_state="UNRESOLVED", reason_code="X")
        # Valid UNRESOLVED row then immutable.
        ins(outcome_state="UNRESOLVED", reason_code="X")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE shadow_expiry_outcomes_v1 SET reason_code='Y'")
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            conn.execute("DELETE FROM shadow_expiry_outcomes_v1")
        with pytest.raises(sqlite3.IntegrityError):  # UNIQUE(candidate_id)
            ins(outcome_state="UNRESOLVED", reason_code="X")
    finally:
        conn.close()


def test_defined_risk_is_recorded_in_usd_not_the_eur_candidate_column(db_path):
    """shadow_candidates.max_theoretical_loss_minor is EUR (converted at
    admission); the outcome's max-loss column is USD and must come from the
    admission decision. Built on the production admission path so the two
    columns genuinely differ (20000 USD vs 16667 EUR at 1.20)."""
    from src.research.shadow_admission import admit_shadow_proposals
    from tests._shadow_admission_seed import fx, seed_proposal

    seeded = seed_proposal(db_path, max_loss_usd_minor=20_000)
    admit_shadow_proposals(fx=fx(), proposal_ids=[seeded["proposal_id"]], db_path=db_path)
    conn = get_connection(db_path)
    try:
        cand = conn.execute(
            "SELECT id, max_theoretical_loss_minor FROM shadow_candidates"
        ).fetchone()
        assert cand["max_theoretical_loss_minor"] == round(20_000 / fx().rate)  # EUR
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        conn.commit()
    finally:
        conn.close()
    record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    o = _outcome(db_path, cand["id"])
    assert o["max_theoretical_loss_usd_minor"] == 20_000
    assert o["max_theoretical_loss_usd_minor"] != cand["max_theoretical_loss_minor"]


def test_expiry_price_excludes_post_close_snapshots(db_path):
    """A later POST_CLOSE price must never replace an expiry-session quote."""
    candidate_id, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        in_run = _insert_run(conn, started="2026-09-18T19:45:00Z",
                             session_date="2026-09-18")
        _insert_snapshot(conn, run_id=in_run, captured_at="2026-09-18T19:45:00Z",
                         session_date="2026-09-18", price=108.0)
        post_run = conn.execute(
            """INSERT INTO research_runs
               (cohort_id, preregistration_hash, code_git_sha, started_at,
                ended_at, us_session_date, us_session_state, status)
               VALUES ('TEST','hash1','sha','2026-09-18T21:30:00Z',
                       '2026-09-18T21:30:00Z','2026-09-18','POST_CLOSE','COMPLETED')"""
        ).lastrowid
        conn.execute(
            """INSERT INTO market_snapshots
               (captured_at, underlying, provider, research_run_id,
                us_session_date, us_session_state, underlying_source, fx_source,
                underlying_price)
               VALUES ('2026-09-18T21:30:00Z','AAPL','THETADATA',?,
                       '2026-09-18','POST_CLOSE','FETCHED','UNKNOWN',60.0)""",
            (post_run,),
        )
        after = _insert_run(conn, started="2026-09-21T14:00:00Z",
                            session_date="2026-09-21")
        conn.commit()
    finally:
        conn.close()
    result = record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    assert result.resolved_written == 1
    assert _outcome(db_path, candidate_id)["terminal_underlying_price"] == 108.0


def test_expiry_query_does_not_require_specific_hint_index(db_path):
    candidate_id, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        in_run = _insert_run(conn, started="2026-09-18T19:45:00Z",
                             session_date="2026-09-18")
        _insert_snapshot(conn, run_id=in_run, captured_at="2026-09-18T19:45:00Z",
                         session_date="2026-09-18", price=108.0)
        after = _insert_run(conn, started="2026-09-21T14:00:00Z",
                            session_date="2026-09-21")
        conn.execute("DROP INDEX IF EXISTS idx_market_snapshots_run_provider")
        conn.commit()
    finally:
        conn.close()
    outcome = record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    assert outcome.resolved_written == 1
    assert _outcome(db_path, candidate_id)["terminal_underlying_price"] == 108.0


def test_expiry_price_prefers_later_instant_with_different_iso_format(db_path):
    candidate_id, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        in_run = _insert_run(conn, started="2026-09-18T19:45:00Z",
                             session_date="2026-09-18")
        _insert_snapshot(conn, run_id=in_run, captured_at="2026-09-18T19:30:00Z",
                         session_date="2026-09-18", price=101.0)
        _insert_snapshot(conn, run_id=in_run, captured_at="2026-09-18T19:45:00+00:00",
                         session_date="2026-09-18", price=108.0)
        after = _insert_run(conn, started="2026-09-21T14:00:00Z",
                            session_date="2026-09-21")
        conn.commit()
    finally:
        conn.close()
    record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    assert _outcome(db_path, candidate_id)["terminal_underlying_price"] == 108.0

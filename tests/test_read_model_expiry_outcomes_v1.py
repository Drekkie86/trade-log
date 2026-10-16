"""Read model exposes expiry outcomes and honest mark counts to the UI."""
from src.dashboard.read_model import load_command_deck
from src.database.repository import get_connection
from src.research.shadow_expiry_outcome_v1 import record_shadow_expiry_outcomes
from src.research.shadow_outcome_collector import collect_shadow_marks
from tests.test_shadow_expiry_outcome_v1 import _insert_run, _insert_snapshot
from tests.test_shadow_outcome_collector import seed_active_candidate


def _followup_row(snapshot, candidate_id):
    return next(r for r in snapshot["shadow_candidate_followup"] if r["candidate_id"] == candidate_id)


def test_dashboard_and_shadow_lab_see_expiry_outcomes(db_path):
    candidate_id, run_with_snapshot = seed_active_candidate(db_path)

    # One valued mark, two unsampled-cycle placeholders.
    collect_shadow_marks(research_run_id=run_with_snapshot, db_path=db_path)
    conn = get_connection(db_path)
    try:
        for i in (1, 2):
            rid = _insert_run(conn, started=f"2026-09-02T14:{15*i:02d}:00Z", session_date="2026-09-02")
            conn.commit()
            collect_shadow_marks(research_run_id=rid, db_path=db_path)
        expiry_run = _insert_run(conn, started="2026-09-18T19:45:00Z", session_date="2026-09-18")
        _insert_snapshot(conn, run_id=expiry_run, captured_at="2026-09-18T19:45:00Z",
                         session_date="2026-09-18", price=108.0)
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        conn.commit()
    finally:
        conn.close()

    # Before any outcome: Dashboard shows zero, not a missing key.
    dash = load_command_deck(page="Dashboard", db_path=db_path)
    assert dash["shadow_expiry_outcomes"]["resolved"] == 0
    assert dash["shadow_expiry_outcomes"]["win_rate"] is None

    record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)

    dash = load_command_deck(page="Dashboard", db_path=db_path)
    agg = dash["shadow_expiry_outcomes"]
    assert agg["resolved"] == 1 and agg["wins"] == 1 and agg["losses"] == 0
    assert agg["win_rate"] == 1.0
    assert agg["total_net_eur_minor"] == round(29400 / 1.20)
    assert agg["net_to_risk_ratio"] == 29400 / 10000
    assert agg["resolved_expiration_dates"] == 1
    assert agg["measurement_role"] == "PROSPECTIVE_EXPIRY_INTRINSIC_V1"

    lab = load_command_deck(page="Shadow Lab", db_path=db_path)
    row = _followup_row(lab, candidate_id)
    assert row["mark_count"] == 3
    assert row["complete_mark_count"] == 1
    assert row["unsampled_cycle_count"] == 2
    assert row["expiry_result"] == "PROFIT AT EXPIRY"
    assert row["expiry_net_pnl_eur_minor"] == round(29400 / 1.20)
    assert row["expiry_terminal_underlying_price"] == 108.0
    # Frozen contract untouched and still visible.
    assert row["validated_outcomes"] == 0
    assert lab["shadow_tracking"]["validated_outcomes"] == 0

    desk = load_command_deck(page="Decision Desk", db_path=db_path)
    cand = next(c for c in desk["decision_desk_candidates"] if c["candidate_id"] == candidate_id)
    assert cand["complete_mark_count"] == 1
    assert cand["expiry_outcome_state"] == "RESOLVED"


def test_unresolved_outcome_is_visible_not_silent(db_path):
    candidate_id, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        conn.commit()
    finally:
        conn.close()
    record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    lab = load_command_deck(page="Shadow Lab", db_path=db_path)
    assert lab["shadow_expiry_outcomes"]["unresolved"] == 1
    row = _followup_row(lab, candidate_id)
    assert row["expiry_result"] == "UNRESOLVED"
    assert row["expiry_outcome_reason"] == "MISSING_EXPIRY_SESSION_UNDERLYING_SNAPSHOT"

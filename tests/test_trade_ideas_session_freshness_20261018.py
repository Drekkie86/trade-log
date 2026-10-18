"""Coffee-desk session accounting: never recycle older ideas as live candidates."""
from src.database.repository import get_connection
from src.decision.trade_ideas import load_current_ideas, load_session_research_funnel
from tests.test_trade_ideas import seed_scenario, SESSION


def _insert_run(conn, day: str, status: str = "COMPLETED") -> int:
    return int(conn.execute(
        """INSERT INTO research_runs (
            cohort_id, preregistration_hash, code_git_sha,
            started_at, ended_at, us_session_date, us_session_state, status
        ) VALUES ('FRESHNESS_TEST','test','test', ?, ?, ?, 'INTRADAY', ?);""",
        (day + "T14:00:00Z", day + "T14:01:00Z", day, status)
    ).lastrowid)


def test_newer_completed_session_with_only_blocked_candidates_does_not_recycle_old(db_path):
    seed_scenario(db_path)
    ideas, errors, day = load_current_ideas(db_path=db_path)
    assert len(ideas) == 1 and errors == [] and day == SESSION
    conn = get_connection(db_path)
    try:
        _insert_run(conn, "2026-09-02")
        conn.commit()
    finally:
        conn.close()
    ideas, errors, day = load_current_ideas(db_path=db_path)
    assert ideas == [] and errors == [] and day == "2026-09-02"
    funnel = load_session_research_funnel(day, db_path=db_path)
    assert funnel == {
        "symbols_sampled": 0,
        "market_snapshots": 0,
        "structures_proposed": 0,
        "structures_blocked": 0,
    }


def test_no_completed_research_session_has_no_ideas(db_path):
    assert load_current_ideas(db_path=db_path) == ([], [], None)
    assert load_session_research_funnel(None, db_path=db_path)["symbols_sampled"] == 0


def test_funnel_counts_actual_evidence_not_configured_universe(db_path):
    seed_scenario(db_path)
    funnel = load_session_research_funnel(SESSION, db_path=db_path)
    assert funnel == {
        "symbols_sampled": 1,
        "market_snapshots": 1,
        "structures_proposed": 1,
        "structures_blocked": 0,
    }


def test_newer_failed_run_does_not_displace_completed_session(db_path):
    ids = seed_scenario(db_path)
    conn = get_connection(db_path)
    try:
        _insert_run(conn, "2026-09-02", "FAILED")
        conn.commit()
    finally:
        conn.close()
    ideas, errors, day = load_current_ideas(db_path=db_path)
    assert errors == [] and day == SESSION
    assert [idea.proposal_id for idea in ideas] == [ids["proposal_id"]]

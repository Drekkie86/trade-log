import json, sqlite3, time
import pytest
from src.database.repository import get_connection
from src.research.shadow_expiry_outcome_v1 import record_shadow_expiry_outcomes
from tests.test_shadow_expiry_outcome_v1 import _insert_run
from tests.test_shadow_outcome_collector import seed_active_candidate


def _snap(conn, run_id, captured, price, state="INTRADAY"):
    return conn.execute(
        """INSERT INTO market_snapshots (captured_at, underlying, provider, research_run_id,
            us_session_date, us_session_state, underlying_source, fx_source, underlying_price)
           VALUES (?, 'AAPL', 'THETADATA', ?, '2026-09-18', ?, 'FETCHED', 'UNKNOWN', ?);""",
        (captured, run_id, state, price)).lastrowid


def test_non_intraday_snapshot_becomes_the_terminal_price(db_path):
    cid, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        r1 = _insert_run(conn, started="2026-09-18T19:30:00Z", session_date="2026-09-18")
        _snap(conn, r1, "2026-09-18T19:30:00Z", 100.0, "INTRADAY")
        r2 = _insert_run(conn, started="2026-09-19T02:00:00Z", session_date="2026-09-18")
        sid = _snap(conn, r2, "2026-09-19T02:00:00Z", 60.0, "POST_CLOSE")
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        conn.commit()
    finally:
        conn.close()
    record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    conn = get_connection(db_path)
    o = conn.execute("select terminal_underlying_price, snapshot_id from shadow_expiry_outcomes_v1").fetchone()
    st = conn.execute("select us_session_state from market_snapshots where id=?", (o["snapshot_id"],)).fetchone()[0]
    print("TERMINAL PRICE USED:", o["terminal_underlying_price"], "from state", st)
    assert o["terminal_underlying_price"] == 60.0  # demonstrates the defect


def test_forced_index_hint_makes_writer_fail_hard_if_index_missing(db_path):
    seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        conn.execute("DROP INDEX idx_market_snapshots_run_provider")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(sqlite3.OperationalError, match="no such index"):
        record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)


def test_timestamp_format_mismatch_in_supersession_compare(db_path):
    # '...00Z' sorts AFTER '...00.500Z' lexicographically although it is earlier
    assert "2026-09-18T19:45:00Z" > "2026-09-18T19:45:00.500Z"

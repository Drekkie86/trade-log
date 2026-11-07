"""Collector-only daemon mode: snapshots persist, retired stages are skipped."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.database.repository import get_connection
from src.research.collector_cycle import run_collector_cycle, skip_shadow_marks
from src.research.research_daemon import (
    acquire_daemon_lock, iteration_runners, release_daemon_lock, run_one_iteration,
)

NY = ZoneInfo("America/New_York")


def test_iteration_runners_follow_the_environment_switch(monkeypatch):
    from src.research.full_research_cycle import run_full_research_cycle
    from src.research.shadow_outcome_collector import collect_shadow_marks

    monkeypatch.delenv("CHRISTIANIA_COLLECTOR_ONLY", raising=False)
    assert iteration_runners() == (run_full_research_cycle, collect_shadow_marks)
    monkeypatch.setenv("CHRISTIANIA_COLLECTOR_ONLY", "1")
    assert iteration_runners() == (run_collector_cycle, skip_shadow_marks)


def test_collector_cycle_persists_a_run_and_the_iteration_summary_keeps_its_shape(db_path, monkeypatch):
    import src.research.collector_cycle as cc

    conn = get_connection(db_path)
    with conn:
        run_id = conn.execute(
            """INSERT INTO research_runs (cohort_id, preregistration_hash, code_git_sha, started_at,
               us_session_date, us_session_state, status, ended_at)
               VALUES ('INDEPENDENT_RESEARCH_RUNNER_V1', 'h', 's', '2026-09-01T14:00:00Z',
                       '2026-09-01', 'INTRADAY', 'COMPLETED', '2026-09-01T14:00:30Z')"""
        ).lastrowid
    conn.close()

    class FakeRun:
        status = "COMPLETED"
        us_session_date = "2026-09-01"
        us_session_state = "INTRADAY"
        summaries = ()

    FakeRun.run_id = run_id
    captured = {}

    def fake_independent(**kwargs):
        captured.update(kwargs)
        return FakeRun()

    monkeypatch.setattr(cc, "run_independent_research", fake_independent)
    owner = "collector-owner"
    acquire_daemon_lock(owner_token=owner, db_path=db_path)
    try:
        summary = run_one_iteration(
            scheduled_for=datetime(2026, 9, 1, 10, 0, tzinfo=NY), owner_token=owner,
            symbols=["AAPL", "SPY"], massive_client=object(), theta_client=object(),
            db_path=db_path, full_cycle_runner=run_collector_cycle, mark_collector=skip_shadow_marks,
        )
    finally:
        release_daemon_lock(owner_token=owner, db_path=db_path)
    assert captured["symbols"] == ["AAPL", "SPY"] and captured["min_dte"] == 7
    assert summary.status == "COMPLETED" and summary.research_run_id == run_id
    assert summary.hypothesis_scanner_run_id is None
    assert (summary.proposals_count, summary.admitted_count, summary.blocked_count,
            summary.outcome_mark_count) == (0, 0, 0, 0)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT status, research_run_id FROM research_daemon_iterations ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert (row["status"], row["research_run_id"]) == ("COMPLETED", run_id)
    finally:
        conn.close()


def test_collector_cycle_refuses_a_non_completed_run(monkeypatch):
    import pytest
    import src.research.collector_cycle as cc

    class Failed:
        run_id = 8
        status = "FAILED"

    monkeypatch.setattr(cc, "run_independent_research", lambda **_: Failed())
    with pytest.raises(RuntimeError):
        run_collector_cycle(symbols=["AAPL"], massive_client=object(), theta_client=object())

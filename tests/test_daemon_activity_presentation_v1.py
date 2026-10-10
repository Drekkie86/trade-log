"""Regression for the October 2026 misleading daemon activity chart."""
from datetime import UTC, datetime
from pathlib import Path

from src.dashboard.daemon_activity_presentation import summarize_daemon_activity


def _row(when: str, status: str = "COMPLETED"):
    return {
        "scheduled_for": when,
        "completed_at": when,
        "status": status,
        "proposals_count": 0,
        "blocked_count": 0,
        "outcome_mark_count": 175,
    }


def test_four_missing_market_sessions_are_visible_even_when_daemon_restarted():
    result = summarize_daemon_activity(
        [_row("2026-10-05T19:45:00Z")],
        daemon_state="HEALTHY",
        observed_at=datetime(2026, 10, 10, 14, 0, tzinfo=UTC),
    )
    assert result["missing_completed_sessions"] == [
        "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09",
    ]
    assert result["live_healthy"] is True
    assert result["latest_recorded_status"] == "COMPLETED"


def test_healthy_weekend_creates_no_false_missed_sessions():
    result = summarize_daemon_activity(
        [_row("2026-10-09T19:45:00Z")],
        daemon_state="HEALTHY",
        observed_at=datetime(2026, 10, 11, 16, 0, tzinfo=UTC),
    )
    assert result["missing_completed_sessions"] == []
    assert result["live_healthy"]


def test_incomplete_monday_session_does_not_trigger_missing_day():
    result = summarize_daemon_activity(
        [_row("2026-10-09T19:45:00Z")],
        daemon_state="HEALTHY",
        observed_at=datetime(2026, 10, 12, 18, 0, tzinfo=UTC),
    )
    assert result["missing_completed_sessions"] == []


def test_completed_monday_session_without_cycle_is_missing():
    result = summarize_daemon_activity(
        [_row("2026-10-09T19:45:00Z")],
        daemon_state="NO_DAEMON_LEASE",
        observed_at=datetime(2026, 10, 12, 21, 0, tzinfo=UTC),
    )
    assert result["missing_completed_sessions"] == ["2026-10-12"]
    assert not result["live_healthy"]


def test_historical_completed_status_cannot_override_missing_lease():
    result = summarize_daemon_activity(
        [_row("2026-10-05T19:45:00Z")],
        daemon_state="NO_DAEMON_LEASE",
        observed_at=datetime(2026, 10, 10, 14, 0, tzinfo=UTC),
    )
    assert result["latest_recorded_status"] == "COMPLETED"
    assert result["live_healthy"] is False


def test_malformed_or_missing_timestamps_cannot_claim_recent_activity():
    result = summarize_daemon_activity(
        [_row("not-a-datetime")],
        daemon_state="UNKNOWN",
        observed_at=datetime(2026, 10, 10, 14, 0, tzinfo=UTC),
    )
    assert result["last_scheduled_at"] is None
    assert result["missing_completed_sessions"] == []
    assert result["live_healthy"] is False


def test_ui_uses_real_time_scatter_and_no_synthetic_cycle_line():
    app = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert 'section_heading(\n            "Last recorded daemon cycles"' in app
    assert 'st.scatter_chart(' in app
    assert 'chart_df, x="scheduled_time"' in app
    assert 'df["cycle"] = range(1, len(df) + 1)' not in app
    assert 'st.line_chart(chart_df' not in app
    assert 'missing_sessions = activity["missing_completed_sessions"]' in app


def test_missing_sessions_remain_visible_after_25_new_cycles_roll_history():
    # The plot contains only today's newer cycles; the independent date set
    # retains the Oct 6-9 outage and does not fabricate any past iterations.
    result = summarize_daemon_activity(
        [_row("2026-10-12T18:00:00Z")],
        daemon_state="HEALTHY",
        recorded_session_dates=[
            "2026-10-05", "2026-10-12",
        ],
        observed_at=datetime(2026, 10, 12, 19, 0, tzinfo=UTC),
    )
    assert result["missing_completed_sessions"] == [
        "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09",
    ]
    assert result["last_scheduled_at"] == "2026-10-12T18:00:00Z"


def test_explicit_empty_history_does_not_invent_missing_sessions():
    result = summarize_daemon_activity(
        [_row("2026-10-05T19:45:00Z")],
        daemon_state="HEALTHY",
        recorded_session_dates=[],
        observed_at=datetime(2026, 10, 10, 14, 0, tzinfo=UTC),
    )
    assert result["missing_completed_sessions"] == []


def test_read_model_uses_index_bounded_session_date_history():
    read_model = (
        Path(__file__).resolve().parents[1] /
        "src" / "dashboard" / "read_model.py"
    ).read_text(encoding="utf-8")
    assert "WHERE scheduled_for >= ?" in read_model
    assert "recorded_daemon_session_dates" in read_model
    assert 'ORDER BY scheduled_for;' in read_model

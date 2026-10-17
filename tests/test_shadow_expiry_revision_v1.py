"""Append-only late-data recovery and latest-only scoreboards for migration 035."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.database.repository import get_connection
from src.dashboard.read_model import load_command_deck
from src.research.shadow_expiry_outcome_v1 import record_shadow_expiry_outcomes
from src.research.universe_profiles import (
    LIQUID_US_RESEARCH_V1,
    select_symbol_batch,
)
from tests.test_shadow_expiry_outcome_v1 import _insert_run, _insert_snapshot
from tests.test_shadow_outcome_collector import seed_active_candidate


def _history(db_path, cid):
    conn = get_connection(db_path)
    try:
        return [
            dict(r) for r in conn.execute(
                "SELECT id, candidate_id, revision, supersedes_outcome_id, "
                "outcome_state, reason_code, snapshot_id, estimated_net_pnl_usd_minor "
                "FROM shadow_expiry_outcomes_v1 WHERE candidate_id=? ORDER BY revision",
                (cid,),
            ).fetchall()
        ]
    finally:
        conn.close()


def test_late_expiry_snapshot_adds_immutable_revision_and_no_double_count(db_path):
    cid, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        initial = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        new_run = _insert_run(conn, started="2026-09-22T14:00:00Z", session_date="2026-09-22")
        conn.commit()
    finally:
        conn.close()

    first = record_shadow_expiry_outcomes(research_run_id=initial, db_path=db_path)
    assert (first.resolved_written, first.unresolved_written) == (0, 1)
    rows = _history(db_path, cid)
    assert len(rows) == 1
    assert rows[0]["outcome_state"] == "UNRESOLVED"
    missing_id = rows[0]["id"]

    # Late archive recovery: expiry-session snapshot inserted AFTER missing result.
    conn = get_connection(db_path)
    try:
        expiry_run = _insert_run(
            conn, started="2026-09-18T19:45:00Z", session_date="2026-09-18"
        )
        _insert_snapshot(
            conn, run_id=expiry_run, captured_at="2026-09-18T19:45:00Z",
            session_date="2026-09-18", price=108.0,
        )
        conn.commit()
    finally:
        conn.close()

    second = record_shadow_expiry_outcomes(research_run_id=new_run, db_path=db_path)
    assert (second.resolved_written, second.unresolved_written) == (1, 0)
    rows = _history(db_path, cid)
    assert len(rows) == 2
    assert rows[1]["revision"] == 2
    assert rows[1]["supersedes_outcome_id"] == missing_id
    assert rows[0]["outcome_state"] == "UNRESOLVED"  # never rewritten
    assert rows[1]["outcome_state"] == "RESOLVED"
    assert rows[1]["estimated_net_pnl_usd_minor"] == 29400

    snap = load_command_deck(page="Shadow Lab", db_path=db_path)
    assert snap["shadow_expiry_outcomes"]["recorded"] == 1
    assert snap["shadow_expiry_outcomes"]["resolved"] == 1
    assert snap["shadow_expiry_outcomes"]["unresolved"] == 0
    assert snap["shadow_expiry_outcomes"]["wins"] == 1
    assert record_shadow_expiry_outcomes(
        research_run_id=new_run, db_path=db_path
    ).candidates_due == 0


def test_newer_expiry_snapshot_supersedes_prior_resolved_price(db_path):
    cid, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        expiry_run = _insert_run(
            conn, started="2026-09-18T19:00:00Z", session_date="2026-09-18"
        )
        first_snapshot = _insert_snapshot(
            conn, run_id=expiry_run, captured_at="2026-09-18T19:00:00Z",
            session_date="2026-09-18", price=108.0,
        )
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        conn.commit()
    finally:
        conn.close()
    record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    assert _history(db_path, cid)[0]["snapshot_id"] == first_snapshot

    conn = get_connection(db_path)
    try:
        later_snapshot = _insert_snapshot(
            conn, run_id=expiry_run, captured_at="2026-09-18T20:00:00Z",
            session_date="2026-09-18", price=95.0,
        )
        next_run = _insert_run(
            conn, started="2026-09-22T14:00:00Z", session_date="2026-09-22"
        )
        conn.commit()
    finally:
        conn.close()
    record_shadow_expiry_outcomes(research_run_id=next_run, db_path=db_path)
    history = _history(db_path, cid)
    assert [r["revision"] for r in history] == [1, 2]
    assert history[1]["snapshot_id"] == later_snapshot
    assert history[0]["estimated_net_pnl_usd_minor"] == 29400
    assert history[1]["estimated_net_pnl_usd_minor"] == -50600
    latest = load_command_deck(page="Shadow Lab", db_path=db_path)["shadow_expiry_outcomes"]
    assert (latest["resolved"], latest["losses"], latest["wins"]) == (1, 1, 0)


def test_revision_cannot_fork_or_overwrite_old_rows(db_path):
    cid, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        conn.commit()
    finally:
        conn.close()
    record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    conn = get_connection(db_path)
    try:
        previous = _history(db_path, cid)[0]["id"]
        with pytest.raises(sqlite3.IntegrityError, match="supersession"):
            conn.execute(
                "INSERT INTO shadow_expiry_outcomes_v1 "
                "(candidate_id, revision, supersedes_outcome_id, research_run_id, "
                "recorded_at, expiration, outcome_state, reason_code, evidence_json) "
                "VALUES (?,?,?,?,?,'2026-09-18','UNRESOLVED','MISSING_EXPIRY_SESSION_UNDERLYING_SNAPSHOT','{}')",
                (cid, 2, previous, after, "2026-09-21T14:00:00Z"),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE shadow_expiry_outcomes_v1 SET reason_code='CHANGED' WHERE id=?",
                (previous,),
            )
    finally:
        conn.close()


def test_pinned_batch_capacity_is_bounded_and_deferred_are_disclosed():
    symbols = list(LIQUID_US_RESEARCH_V1)
    all_pinned = list(reversed(symbols))
    ny = ZoneInfo("America/New_York")
    seen = set()
    deferred_seen = set()
    for minute in range(0, 60 * 7, 15):
        slot = datetime(2026, 10, 15, 9, 45, tzinfo=ny).replace(
            hour=9 + (45 + minute) // 60, minute=(45 + minute) % 60
        )
        batch = select_symbol_batch(
            symbols=symbols, scheduled_for=slot, batch_size=12,
            interval_minutes=15, pinned=all_pinned,
        )
        assert batch.batch_size <= 24
        assert batch.batch_size == len(batch.symbols)
        assert len(batch.symbols) == len(set(batch.symbols))
        assert set(batch.pinned_added).isdisjoint(batch.pinned_deferred)
        assert set(batch.pinned_deferred).isdisjoint(batch.symbols)
        seen.update(batch.symbols)
        deferred_seen.update(batch.pinned_deferred)
    assert seen == set(symbols)
    assert deferred_seen


def test_new_revision_accepts_later_instant_even_if_iso_text_sorts_earlier(db_path):
    """+00:00 sorts before Z as text but 19:45 is later than 19:30."""
    cid, _ = seed_active_candidate(db_path)
    conn = get_connection(db_path)
    try:
        expiry_run = _insert_run(
            conn, started="2026-09-18T19:30:00Z", session_date="2026-09-18"
        )
        _insert_snapshot(
            conn, run_id=expiry_run, captured_at="2026-09-18T19:30:00Z",
            session_date="2026-09-18", price=108.0,
        )
        after = _insert_run(
            conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21"
        )
        conn.commit()
    finally:
        conn.close()
    first = record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    assert first.resolved_written == 1
    conn = get_connection(db_path)
    try:
        _insert_snapshot(
            conn, run_id=expiry_run,
            captured_at="2026-09-18T19:45:00+00:00",
            session_date="2026-09-18", price=95.0,
        )
        next_run = _insert_run(
            conn, started="2026-09-22T14:00:00Z",
            session_date="2026-09-22"
        )
        conn.commit()
    finally:
        conn.close()
    second = record_shadow_expiry_outcomes(research_run_id=next_run, db_path=db_path)
    assert second.resolved_written == 1
    history = _history(db_path, cid)
    assert [x["revision"] for x in history] == [1, 2]
    assert history[1]["estimated_net_pnl_usd_minor"] == -50600

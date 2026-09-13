from __future__ import annotations

import sqlite3

from src.research.prospective_shadow_runtime_v1 import load_calibration_shadow_runtime


def _build_db(path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE prospective_research_freeze_v1_runs (
                id INTEGER PRIMARY KEY,
                frozen_through_session_date TEXT NOT NULL,
                prospective_start_session_date TEXT NOT NULL,
                protocol_state TEXT NOT NULL,
                p_values_enabled INTEGER NOT NULL,
                fdr_enabled INTEGER NOT NULL,
                admission_enabled INTEGER NOT NULL,
                decision_enabled INTEGER NOT NULL
            );
            CREATE TABLE prospective_research_hypotheses_v1 (
                id INTEGER PRIMARY KEY,
                freeze_run_id INTEGER NOT NULL
            );
            CREATE TABLE prospective_surface (
                session_date TEXT NOT NULL
            );
            CREATE VIEW v_local_surface_v2_prospective_partition_v2 AS
                SELECT session_date FROM prospective_surface;
            CREATE TABLE shadow_candidates (
                id INTEGER PRIMARY KEY
            );
            CREATE TABLE shadow_state_events (
                id INTEGER PRIMARY KEY,
                candidate_id INTEGER NOT NULL,
                to_state TEXT NOT NULL
            );
            CREATE TABLE shadow_mark_observations (
                id INTEGER PRIMARY KEY,
                candidate_id INTEGER NOT NULL,
                research_run_id INTEGER NOT NULL,
                quality_state TEXT NOT NULL,
                estimated_net_pnl_eur_minor INTEGER
            );
            """
        )
        conn.execute(
            """
            INSERT INTO prospective_research_freeze_v1_runs VALUES
            (1,'2026-09-03','2026-09-04','FROZEN_PROSPECTIVE_OBSERVATION_ONLY',0,0,0,0);
            """
        )
        conn.executemany(
            "INSERT INTO prospective_research_hypotheses_v1(freeze_run_id) VALUES (1);",
            [() for _ in range(4)],
        )
        conn.executemany(
            "INSERT INTO prospective_surface(session_date) VALUES (?);",
            [(f"2026-09-{day:02d}",) for day in range(4, 10)],
        )
        conn.executemany("INSERT INTO shadow_candidates(id) VALUES (?);", [(1,), (2,), (3,)])
        conn.executemany(
            "INSERT INTO shadow_state_events(candidate_id,to_state) VALUES (?,?);",
            [(1, "SHADOW_TRACKED"), (2, "CLOSED_OR_EXPIRED"), (3, "REJECTED")],
        )
        conn.executemany(
            """
            INSERT INTO shadow_mark_observations(
                candidate_id,research_run_id,quality_state,estimated_net_pnl_eur_minor
            ) VALUES (?,?,?,?);
            """,
            [
                (1, 10, "COMPLETE", 120),
                (1, 11, "COMPLETE", -50),
                (2, 11, "INCOMPLETE_LEG_MARK", None),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_runtime_summarizes_prospective_and_shadow_evidence_read_only(tmp_path) -> None:
    path = tmp_path / "runtime.db"
    _build_db(path)
    state = load_calibration_shadow_runtime(path)

    assert state.state == "DESCRIPTIVE_REVIEW_AVAILABLE"
    assert state.prospective.freeze_run_id == 1
    assert state.prospective.prospective_independent_dates == 6
    assert state.prospective.hypothesis_count == 4
    assert state.prospective.p_values_enabled is False
    assert state.prospective.fdr_enabled is False
    assert state.shadow.candidate_count == 3
    assert state.shadow.shadow_tracked_count == 1
    assert state.shadow.closed_or_expired_count == 1
    assert state.shadow.rejected_count == 1
    assert state.shadow.complete_mark_count == 2
    assert state.shadow.incomplete_mark_count == 1
    assert state.shadow.profitable_mark_count == 1
    assert state.shadow.losing_mark_count == 1
    assert state.shadow.marked_research_run_count == 2
    assert state.shadow.decision_time_probability_state == "NOT_CAPTURED_IN_SHADOW_MARKS"
    assert state.promotion_authority == "NONE_AUTOMATIC_REVIEW_ONLY"


def test_missing_database_fails_closed(tmp_path) -> None:
    state = load_calibration_shadow_runtime(tmp_path / "missing.db")
    assert state.state == "DATABASE_UNAVAILABLE"
    assert state.promotion_authority == "NONE_RESEARCH_ONLY"

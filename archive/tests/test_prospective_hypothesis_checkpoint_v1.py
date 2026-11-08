from __future__ import annotations

import json
import sqlite3

from src.research.prospective_hypothesis_checkpoint_v1 import (
    evaluate_prospective_hypotheses_v1,
)


HYPOTHESES = (
    "H1_DTE_14_20_TRANSFER_STABILITY",
    "H2_MODEL_FORM_GENERALIZATION",
    "H3_MARKET_QUALITY_CONDITIONING",
    "H4_PERSISTENT_EPISODE_RECURRENCE",
)


def _build_db(path, *, session_dates: list[str]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE prospective_research_freeze_v1_runs (
                id INTEGER PRIMARY KEY,
                source_validity_run_id INTEGER NOT NULL
            );

            CREATE TABLE prospective_research_hypotheses_v1 (
                id INTEGER PRIMARY KEY,
                freeze_run_id INTEGER NOT NULL,
                hypothesis_key TEXT NOT NULL,
                minimum_independent_dates INTEGER NOT NULL
            );

            CREATE TABLE local_surface_calibration_validity_v1_runs (
                id INTEGER PRIMARY KEY,
                source_calibration_run_id INTEGER NOT NULL
            );

            CREATE TABLE local_surface_calibration_readiness_v1_runs (
                id INTEGER PRIMARY KEY,
                source_null_run_id INTEGER NOT NULL
            );

            CREATE TABLE local_surface_null_v1_strata (
                null_run_id INTEGER NOT NULL,
                stratum_key TEXT NOT NULL,
                shrunk_location REAL NOT NULL
            );

            CREATE TABLE prospective_surface (
                research_run_id INTEGER NOT NULL,
                underlying TEXT NOT NULL,
                expiration TEXT NOT NULL,
                strike REAL NOT NULL,
                right TEXT NOT NULL,
                implied_volatility REAL,
                dte INTEGER,
                loo_residual REAL,
                abs_delta REAL,
                spread_to_mid REAL,
                greek_age_seconds REAL,
                us_session_date TEXT NOT NULL,
                evidence_phase TEXT NOT NULL,
                observation_state TEXT NOT NULL
            );

            CREATE VIEW v_local_surface_v2_prospective_partition_v2 AS
            SELECT * FROM prospective_surface;

            CREATE TABLE prospective_research_hypothesis_evaluations_v1 (
                id INTEGER PRIMARY KEY,
                freeze_run_id INTEGER NOT NULL,
                hypothesis_id INTEGER NOT NULL,
                hypothesis_key TEXT NOT NULL,
                evaluation_version TEXT NOT NULL,
                evaluated_at TEXT NOT NULL,
                evidence_start_session_date TEXT,
                evidence_end_session_date TEXT,
                independent_date_count INTEGER NOT NULL,
                observation_count INTEGER NOT NULL,
                evaluation_state TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                p_values_enabled INTEGER NOT NULL DEFAULT 0 CHECK(p_values_enabled=0),
                fdr_enabled INTEGER NOT NULL DEFAULT 0 CHECK(fdr_enabled=0),
                decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK(decision_enabled=0),
                UNIQUE(
                    freeze_run_id,
                    hypothesis_id,
                    evaluation_version,
                    evidence_end_session_date
                )
            );
            """
        )
        conn.execute(
            "INSERT INTO prospective_research_freeze_v1_runs VALUES (1, 1);"
        )
        conn.execute(
            "INSERT INTO local_surface_calibration_validity_v1_runs VALUES (1, 1);"
        )
        conn.execute(
            "INSERT INTO local_surface_calibration_readiness_v1_runs VALUES (1, 7);"
        )
        conn.executemany(
            """
            INSERT INTO prospective_research_hypotheses_v1(
                id, freeze_run_id, hypothesis_key, minimum_independent_dates
            ) VALUES (?, 1, ?, 5);
            """,
            [(index, key) for index, key in enumerate(HYPOTHESES, start=1)],
        )
        conn.execute(
            """
            INSERT INTO local_surface_null_v1_strata(
                null_run_id, stratum_key, shrunk_location
            ) VALUES (7, 'C|DTE_14_20|ABSDELTA_40_60', 0.0);
            """
        )

        rows = []
        for run_id, session_date in enumerate(session_dates, start=100):
            for strike, iv, residual in (
                (95.0, 0.20, 0.01),
                (100.0, 0.25, 0.04),
                (105.0, 0.20, 0.01),
            ):
                rows.append(
                    (
                        run_id,
                        "AAPL",
                        "2026-10-02",
                        strike,
                        "C",
                        iv,
                        16,
                        residual,
                        0.50,
                        0.04,
                        0.5,
                        session_date,
                        "POST_FREEZE_PROSPECTIVE",
                        "EVALUATED_OBSERVATIONAL",
                    )
                )

        conn.executemany(
            """
            INSERT INTO prospective_surface(
                research_run_id, underlying, expiration, strike, right,
                implied_volatility, dte, loo_residual, abs_delta,
                spread_to_mid, greek_age_seconds, us_session_date,
                evidence_phase, observation_state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def test_checkpoint_refuses_hypothesis_assessment_before_frozen_date_minimum(
    tmp_path,
):
    db = tmp_path / "prospective_insufficient.db"
    _build_db(
        db,
        session_dates=[
            "2026-09-04",
            "2026-09-05",
            "2026-09-08",
            "2026-09-09",
        ],
    )

    first = evaluate_prospective_hypotheses_v1(db_path=db, persist=True)
    second = evaluate_prospective_hypotheses_v1(db_path=db, persist=True)

    assert len(first.checkpoints) == 4
    assert all(
        checkpoint.evaluation_state == "INSUFFICIENT_INDEPENDENT_DATES"
        for checkpoint in first.checkpoints
    )
    assert all(checkpoint.independent_date_count == 4 for checkpoint in first.checkpoints)
    assert [item.persisted_evaluation_id for item in first.checkpoints] == [
        item.persisted_evaluation_id for item in second.checkpoints
    ]

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """
            SELECT p_values_enabled, fdr_enabled, decision_enabled, metrics_json
            FROM prospective_research_hypothesis_evaluations_v1
            ORDER BY id;
            """
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 4
    assert all(row[:3] == (0, 0, 0) for row in rows)
    assert all(
        json.loads(row[3])["guardrail"].startswith("Frozen minimum date count")
        for row in rows
    )


def test_six_date_checkpoint_is_descriptive_only_and_runs_h2_challenger(
    tmp_path,
):
    db = tmp_path / "prospective_ready.db"
    _build_db(
        db,
        session_dates=[
            "2026-09-04",
            "2026-09-05",
            "2026-09-08",
            "2026-09-09",
            "2026-09-10",
            "2026-09-11",
        ],
    )

    result = evaluate_prospective_hypotheses_v1(db_path=db, persist=True)
    by_key = {item.hypothesis_key: item for item in result.checkpoints}

    assert set(by_key) == set(HYPOTHESES)
    assert all(
        checkpoint.evaluation_state == "DESCRIPTIVE_CHECKPOINT_READY"
        for checkpoint in result.checkpoints
    )
    assert all(checkpoint.independent_date_count == 6 for checkpoint in result.checkpoints)

    h2 = by_key["H2_MODEL_FORM_GENERALIZATION"].metrics
    assert h2["metric_family"] == (
        "QUADRATIC_V2_VS_NEAREST_BRACKET_LINEAR_PROSPECTIVE_V1"
    )
    assert h2["comparison_by_dte"]
    assert h2["comparison_by_dte"][0]["dte_bucket"] == "DTE_14_20"
    assert h2["p_values_enabled"] is False
    assert h2["fdr_enabled"] is False
    assert h2["decision_enabled"] is False
    assert "No automatic model switching" in h2["interpretation"]

    h4 = by_key["H4_PERSISTENT_EPISODE_RECURRENCE"].metrics
    assert h4["recurring_contract_count_in_top_view"] >= 3

    conn = sqlite3.connect(db)
    try:
        persisted = conn.execute(
            """
            SELECT
                COUNT(*),
                SUM(p_values_enabled),
                SUM(fdr_enabled),
                SUM(decision_enabled)
            FROM prospective_research_hypothesis_evaluations_v1;
            """
        ).fetchone()
    finally:
        conn.close()

    assert persisted == (4, 0, 0, 0)

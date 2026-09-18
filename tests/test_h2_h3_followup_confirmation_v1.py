from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.database.migration_runner import apply_migration_file
from src.research.h2_h3_followup_confirmation_v1 import (
    FollowupConfirmationError,
    H2_KEY,
    H3_KEY,
    evaluate_h2_h3_followup_confirmation_v1,
    freeze_h2_h3_followup_confirmation_v1,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "032_h2_h3_followup_confirmation.sql"

SCANNER_FAMILY = "BASIC_TRADABILITY_V1"
SCANNER_VERSION = "1.0.1"
RULE_VERSION = "LOCAL_IV_RESIDUAL_RULES_V1"
HYPOTHESIS_FAMILY = "LOCAL_SURFACE_IV_RESIDUAL"
HYPOTHESIS_VERSION = "1.0.0"
SCANNER_CONFIG = "s" * 64

SURFACE_FAMILY = "LOCAL_SURFACE_RESIDUAL_V2"
SURFACE_VERSION = "0.1.0"
FIT_SPEC = "LOO_QUADRATIC_CENTERED_V1"
SURFACE_CONFIG = "q" * 64


def _build_v31(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE schema_version (
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_version(version, applied_at)
            VALUES (31, '2026-09-17T00:00:00Z');

            CREATE TABLE research_runs (
                id INTEGER PRIMARY KEY,
                us_session_date TEXT NOT NULL,
                status TEXT NOT NULL
            );

            CREATE TABLE prospective_research_freeze_v1_runs (
                id INTEGER PRIMARY KEY,
                source_validity_run_id INTEGER NOT NULL,
                frozen_through_session_date TEXT NOT NULL,
                prospective_start_session_date TEXT NOT NULL
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

            CREATE TABLE hypothesis_scanner_runs (
                id INTEGER PRIMARY KEY,
                research_run_id INTEGER NOT NULL,
                scanner_family_id TEXT NOT NULL,
                scanner_version TEXT NOT NULL,
                rule_version TEXT NOT NULL,
                hypothesis_family TEXT NOT NULL,
                hypothesis_version TEXT NOT NULL,
                config_hash TEXT NOT NULL
            );

            CREATE TABLE hypothesis_scanner_evaluations (
                id INTEGER PRIMARY KEY,
                scanner_run_id INTEGER NOT NULL,
                option_quote_id INTEGER NOT NULL,
                iv_residual REAL
            );

            CREATE TABLE local_surface_residual_v2_runs (
                id INTEGER PRIMARY KEY,
                research_run_id INTEGER NOT NULL,
                model_family_id TEXT NOT NULL,
                model_version TEXT NOT NULL,
                fit_spec_version TEXT NOT NULL,
                config_hash TEXT NOT NULL
            );

            CREATE TABLE local_surface_residual_v2_observations (
                id INTEGER PRIMARY KEY,
                model_run_id INTEGER NOT NULL,
                option_quote_id INTEGER NOT NULL
            );

            CREATE TABLE surface_rows (
                observation_id INTEGER PRIMARY KEY,
                research_run_id INTEGER NOT NULL,
                model_version TEXT NOT NULL,
                fit_spec_version TEXT NOT NULL,
                underlying TEXT NOT NULL,
                expiration TEXT NOT NULL,
                strike REAL NOT NULL,
                right TEXT NOT NULL,
                abs_delta REAL NOT NULL,
                implied_volatility REAL,
                loo_residual REAL,
                spread_to_mid REAL,
                us_session_date TEXT NOT NULL,
                dte INTEGER NOT NULL,
                greek_age_seconds REAL,
                observation_state TEXT NOT NULL
            );

            CREATE VIEW v_local_surface_residual_v2_discovery_dataset AS
            SELECT *
            FROM surface_rows;
            """
        )

        conn.execute(
            """
            INSERT INTO prospective_research_freeze_v1_runs(
                id,
                source_validity_run_id,
                frozen_through_session_date,
                prospective_start_session_date
            ) VALUES (1, 1, '2026-09-03', '2026-09-04');
            """
        )
        conn.execute(
            """
            INSERT INTO local_surface_calibration_validity_v1_runs(
                id, source_calibration_run_id
            ) VALUES (1, 1);
            """
        )
        conn.execute(
            """
            INSERT INTO local_surface_calibration_readiness_v1_runs(
                id, source_null_run_id
            ) VALUES (1, 7);
            """
        )
        conn.execute(
            """
            INSERT INTO local_surface_null_v1_strata(
                null_run_id,
                stratum_key,
                shrunk_location
            ) VALUES (
                7,
                'C|DTE_14_20|ABSDELTA_40_60',
                0.0
            );
            """
        )

        # One pre-freeze discovery run is sufficient to freeze a unique
        # implementation identity.
        conn.execute(
            """
            INSERT INTO research_runs(id, us_session_date, status)
            VALUES (10, '2026-09-17', 'COMPLETED');
            """
        )
        conn.execute(
            """
            INSERT INTO hypothesis_scanner_runs(
                id,
                research_run_id,
                scanner_family_id,
                scanner_version,
                rule_version,
                hypothesis_family,
                hypothesis_version,
                config_hash
            ) VALUES (?, 10, ?, ?, ?, ?, ?, ?);
            """,
            (
                10,
                SCANNER_FAMILY,
                SCANNER_VERSION,
                RULE_VERSION,
                HYPOTHESIS_FAMILY,
                HYPOTHESIS_VERSION,
                SCANNER_CONFIG,
            ),
        )
        conn.execute(
            """
            INSERT INTO local_surface_residual_v2_runs(
                id,
                research_run_id,
                model_family_id,
                model_version,
                fit_spec_version,
                config_hash
            ) VALUES (?, 10, ?, ?, ?, ?);
            """,
            (
                10,
                SURFACE_FAMILY,
                SURFACE_VERSION,
                FIT_SPEC,
                SURFACE_CONFIG,
            ),
        )
        conn.commit()

        apply_migration_file(
            conn,
            MIGRATION,
            expected_from=31,
            target_version=32,
        )
    finally:
        conn.close()


def _add_followup_date(
    path: Path,
    *,
    run_id: int,
    session_date: str,
) -> None:
    conn = sqlite3.connect(path)
    try:
        scanner_run_id = run_id * 10
        surface_run_id = run_id * 100

        conn.execute(
            """
            INSERT INTO research_runs(id, us_session_date, status)
            VALUES (?, ?, 'COMPLETED');
            """,
            (run_id, session_date),
        )
        conn.execute(
            """
            INSERT INTO hypothesis_scanner_runs(
                id,
                research_run_id,
                scanner_family_id,
                scanner_version,
                rule_version,
                hypothesis_family,
                hypothesis_version,
                config_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                scanner_run_id,
                run_id,
                SCANNER_FAMILY,
                SCANNER_VERSION,
                RULE_VERSION,
                HYPOTHESIS_FAMILY,
                HYPOTHESIS_VERSION,
                SCANNER_CONFIG,
            ),
        )
        conn.execute(
            """
            INSERT INTO local_surface_residual_v2_runs(
                id,
                research_run_id,
                model_family_id,
                model_version,
                fit_spec_version,
                config_hash
            ) VALUES (?, ?, ?, ?, ?, ?);
            """,
            (
                surface_run_id,
                run_id,
                SURFACE_FAMILY,
                SURFACE_VERSION,
                FIT_SPEC,
                SURFACE_CONFIG,
            ),
        )

        observations = (
            # spread, Greek age, quadratic residual, linear residual
            (0.02, 0.5, 0.010, 0.005),
            (0.07, 3.0, 0.020, 0.006),
            (0.15, 10.0, 0.030, 0.007),
        )

        for index, (
            spread,
            greek_age,
            quadratic_residual,
            linear_residual,
        ) in enumerate(observations, start=1):
            observation_id = run_id * 1000 + index
            option_quote_id = run_id * 10000 + index
            strike = 95.0 + 5.0 * index

            conn.execute(
                """
                INSERT INTO local_surface_residual_v2_observations(
                    id,
                    model_run_id,
                    option_quote_id
                ) VALUES (?, ?, ?);
                """,
                (
                    observation_id,
                    surface_run_id,
                    option_quote_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO surface_rows(
                    observation_id,
                    research_run_id,
                    model_version,
                    fit_spec_version,
                    underlying,
                    expiration,
                    strike,
                    right,
                    abs_delta,
                    implied_volatility,
                    loo_residual,
                    spread_to_mid,
                    us_session_date,
                    dte,
                    greek_age_seconds,
                    observation_state
                ) VALUES (
                    ?, ?, ?, ?,
                    'AAPL',
                    '2026-10-02',
                    ?,
                    'C',
                    0.50,
                    0.25,
                    ?,
                    ?,
                    ?,
                    16,
                    ?,
                    'EVALUATED_OBSERVATIONAL'
                );
                """,
                (
                    observation_id,
                    run_id,
                    SURFACE_VERSION,
                    FIT_SPEC,
                    strike,
                    quadratic_residual,
                    spread,
                    session_date,
                    greek_age,
                ),
            )
            conn.execute(
                """
                INSERT INTO hypothesis_scanner_evaluations(
                    scanner_run_id,
                    option_quote_id,
                    iv_residual
                ) VALUES (?, ?, ?);
                """,
                (
                    scanner_run_id,
                    option_quote_id,
                    linear_residual,
                ),
            )

        conn.commit()
    finally:
        conn.close()


def test_followup_freeze_is_separate_idempotent_and_preserves_original_clock(
    tmp_path: Path,
) -> None:
    db = tmp_path / "followup_freeze.db"
    _build_v31(db)

    first = freeze_h2_h3_followup_confirmation_v1(
        db_path=db,
    )
    second = freeze_h2_h3_followup_confirmation_v1(
        db_path=db,
    )

    assert first.created is True
    assert second.created is False
    assert second.program_id == first.program_id
    assert first.frozen_through_session_date == "2026-09-17"
    assert first.prospective_start_session_date == "2026-09-18"

    conn = sqlite3.connect(db)
    try:
        original = conn.execute(
            """
            SELECT frozen_through_session_date, prospective_start_session_date
            FROM prospective_research_freeze_v1_runs;
            """
        ).fetchall()
        followup_count = conn.execute(
            "SELECT COUNT(*) FROM prospective_followup_programs_v1;"
        ).fetchone()[0]
        hypothesis_count = conn.execute(
            "SELECT COUNT(*) FROM prospective_followup_hypotheses_v1;"
        ).fetchone()[0]
        discovery_context = json.loads(
            conn.execute(
                """
                SELECT discovery_context_json
                FROM prospective_followup_programs_v1
                WHERE program_key = 'H2_H3_FOLLOWUP_CONFIRMATION_V1';
                """
            ).fetchone()[0]
        )
    finally:
        conn.close()

    assert original == [("2026-09-03", "2026-09-04")]
    assert followup_count == 1
    assert hypothesis_count == 2

    overlap = discovery_context["h2"]["h2_v2_overlap_parity"]
    assert overlap["v1_evaluable_observations"] == 969048
    assert overlap["comparable_observations"] == 965689
    assert overlap["v2_not_evaluable_gap"] == 3359
    assert overlap["missing_v2_observations"] == 0
    assert overlap["v2_not_evaluable_reasons"] == {
        "INSUFFICIENT_USABLE_STRIKES": {
            "usable_strikes_3": 835,
            "usable_strikes_4": 2524,
            "total": 3359,
        }
    }
    assert overlap["per_date_gap"] == {
        "2026-09-04": 779,
        "2026-09-11": 53,
        "2026-09-14": 885,
        "2026-09-15": 594,
        "2026-09-16": 695,
        "2026-09-17": 353,
    }
    assert sum(overlap["per_date_gap"].values()) == 3359

    minimum_geometry = overlap["minimum_geometry_rule"]
    assert minimum_geometry["min_usable_strikes"] == 5
    assert minimum_geometry["quadratic_parameter_count"] == 3
    assert minimum_geometry["loo_peer_count_at_minimum"] == 4
    assert minimum_geometry["residual_degrees_of_freedom_at_minimum"] == 1
    assert "does not independently establish" in minimum_geometry["audit_boundary"]

    assert overlap["gap_reconciliation_state"] == (
        "FULLY_EXPLAINED_BY_V2_MINIMUM_GEOMETRY"
    )

    selection = discovery_context["h2"]["raw_vs_centered_selection_audit"]
    assert selection["raw_better_consistently_exceeds_centered"] is False

    examples = selection["centered_higher_examples_all_population"]
    assert examples == [
        {
            "session_date": "2026-09-14",
            "dte_bucket": "DTE_21_30",
            "raw_better_fraction": 0.6686,
            "centered_better_fraction": 0.6867,
        },
        {
            "session_date": "2026-09-16",
            "dte_bucket": "DTE_31_45",
            "raw_better_fraction": 0.6622,
            "centered_better_fraction": 0.6808,
        },
        {
            "session_date": "2026-09-17",
            "dte_bucket": "DTE_21_30",
            "raw_better_fraction": 0.6583,
            "centered_better_fraction": 0.6828,
        },
    ]
    assert all(
        item["centered_better_fraction"] > item["raw_better_fraction"]
        for item in examples
    )


def test_followup_freeze_refuses_late_creation_after_new_boundary_evidence(
    tmp_path: Path,
) -> None:
    db = tmp_path / "late_followup_freeze.db"
    _build_v31(db)

    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            INSERT INTO research_runs(id, us_session_date, status)
            VALUES (20, '2026-09-18', 'COMPLETED');
            """
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        FollowupConfirmationError,
        match="completed research evidence already exists",
    ):
        freeze_h2_h3_followup_confirmation_v1(
            db_path=db,
        )


def test_five_date_milestone_uses_first_five_dates_and_no_intermediate_peeking(
    tmp_path: Path,
) -> None:
    db = tmp_path / "followup_evaluation.db"
    _build_v31(db)
    freeze_h2_h3_followup_confirmation_v1(
        db_path=db,
    )

    first_five = [
        "2026-09-18",
        "2026-09-21",
        "2026-09-22",
        "2026-09-23",
        "2026-09-24",
    ]
    for offset, session_date in enumerate(
        first_five,
        start=20,
    ):
        _add_followup_date(
            db,
            run_id=offset,
            session_date=session_date,
        )

    first = evaluate_h2_h3_followup_confirmation_v1(
        db_path=db,
        persist=True,
    )

    assert first.available_independent_dates == 5
    assert first.available_session_dates == tuple(first_five)
    assert len(first.evaluations) == 2

    by_key = {
        item.hypothesis_key: item
        for item in first.evaluations
    }
    assert set(by_key) == {H2_KEY, H3_KEY}

    h2 = by_key[H2_KEY]
    assert h2.milestone_date_count == 5
    assert h2.evaluation_state == "DESCRIPTIVE_5_DATE_CHECKPOINT"
    assert h2.observation_count == 15

    h2_primary = h2.metrics["primary_all_population"]
    h2_clean = h2.metrics["secondary_clean_population"]
    assert h2_primary["date_x_dte_cell_count"] == 5
    assert h2_primary["local_linear_lower_median_cell_count"] == 5
    assert h2_primary["local_linear_lower_q95_cell_count"] == 5
    assert (
        h2_primary["local_linear_better_fraction_gt_half_cell_count"]
        == 5
    )
    assert h2_clean["role"] == (
        "PRESPECIFIED_SECONDARY_DISCOVERY_INFORMED"
    )
    assert h2_clean["date_x_dte_cell_count"] == 5

    h3 = by_key[H3_KEY]
    assert h3.observation_count == 15
    assert h3.metrics["spread_summary"] == {
        "evaluable_date_x_dte_cells": 5,
        "strict_monotonic_cells": 5,
    }
    assert h3.metrics["greek_age_summary"] == {
        "evaluable_date_x_dte_cells": 5,
        "strict_monotonic_cells": 5,
    }

    first_ids = {
        item.hypothesis_key: item.persisted_evaluation_id
        for item in first.evaluations
    }

    # A sixth fresh date is visible as coverage but must not create a rolling
    # 6-date checkpoint. The frozen 5-date milestone remains the first five
    # eligible dates.
    _add_followup_date(
        db,
        run_id=30,
        session_date="2026-09-25",
    )

    second = evaluate_h2_h3_followup_confirmation_v1(
        db_path=db,
        persist=True,
    )

    assert second.available_independent_dates == 6
    assert len(second.evaluations) == 2
    assert {
        item.hypothesis_key: item.persisted_evaluation_id
        for item in second.evaluations
    } == first_ids
    assert all(
        item.metrics["evidence_session_dates"] == first_five
        for item in second.evaluations
    )

    conn = sqlite3.connect(db)
    try:
        persisted = conn.execute(
            """
            SELECT
                COUNT(*),
                SUM(p_values_enabled),
                SUM(fdr_enabled),
                SUM(admission_enabled),
                SUM(model_promotion_enabled),
                SUM(decision_enabled)
            FROM prospective_followup_evaluations_v1;
            """
        ).fetchone()
    finally:
        conn.close()

    assert persisted == (2, 0, 0, 0, 0, 0)

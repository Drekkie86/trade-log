from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.database.migration_runner import apply_migration_file
from src.research.counterfactual_rejection_audit_v1 import (
    ADMITTED_GROUP,
    CounterfactualRejectionAuditError,
    REJECTED_GROUP,
    evaluate_counterfactual_rejection_audit_v1,
    freeze_counterfactual_rejection_audit_v1,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "033_counterfactual_rejection_audit_v1.sql"


def _build_v32(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE schema_version(
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_version(version, applied_at)
            VALUES(32, '2026-09-18T00:00:00Z');

            CREATE TABLE research_runs(
                id INTEGER PRIMARY KEY,
                us_session_date TEXT NOT NULL,
                status TEXT NOT NULL
            );

            CREATE TABLE historical_replay_runs_v1(
                id INTEGER PRIMARY KEY,
                replay_version TEXT NOT NULL
            );

            CREATE TABLE shadow_candidates(
                id INTEGER PRIMARY KEY
            );

            CREATE TABLE option_quotes(
                id INTEGER PRIMARY KEY,
                bid REAL,
                ask REAL
            );

            CREATE TABLE hypothesis_scanner_evaluations(
                id INTEGER PRIMARY KEY,
                option_quote_id INTEGER NOT NULL,
                lower_strike REAL,
                upper_strike REAL,
                delta REAL,
                implied_volatility REAL,
                iv_residual REAL,
                abs_iv_residual REAL,
                residual_threshold REAL
            );

            CREATE TABLE shadow_structure_proposals(
                id INTEGER PRIMARY KEY,
                research_run_id INTEGER NOT NULL,
                hypothesis_evaluation_id INTEGER NOT NULL,
                underlying TEXT NOT NULL,
                expiration TEXT NOT NULL,
                right TEXT NOT NULL,
                target_strike REAL NOT NULL,
                structure_id TEXT,
                structure_json TEXT,
                entry_pricing_json TEXT,
                max_theoretical_loss_minor INTEGER,
                risk_currency TEXT,
                proposal_state TEXT NOT NULL
            );

            CREATE TABLE shadow_admission_decisions(
                id INTEGER PRIMARY KEY,
                candidate_id INTEGER,
                proposal_id INTEGER NOT NULL,
                decided_at TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                estimated_cost_usd_minor INTEGER NOT NULL,
                reserved_risk_usd_minor INTEGER NOT NULL,
                decision TEXT NOT NULL
            );

            CREATE TABLE historical_policy_replay_v1(
                id INTEGER PRIMARY KEY,
                replay_run_id INTEGER NOT NULL,
                original_admission_decision_id INTEGER NOT NULL,
                proposal_id INTEGER NOT NULL,
                original_decided_at TEXT NOT NULL,
                original_reason_code TEXT NOT NULL,
                estimated_cost_usd_minor INTEGER NOT NULL,
                intrinsic_risk_usd_minor INTEGER NOT NULL,
                counterfactual_decision TEXT NOT NULL
            );

            CREATE TABLE historical_outcome_recovery_v1(
                id INTEGER PRIMARY KEY,
                replay_run_id INTEGER NOT NULL,
                source_population TEXT NOT NULL,
                source_candidate_id INTEGER,
                policy_replay_id INTEGER,
                proposal_id INTEGER NOT NULL,
                recovery_state TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                measurement_role TEXT NOT NULL,
                outcome_eligible INTEGER NOT NULL,
                estimated_net_pnl_usd_minor INTEGER
            );
            """
        )

        conn.execute(
            """
            INSERT INTO research_runs(id, us_session_date, status)
            VALUES(1, '2026-09-17', 'COMPLETED');
            """
        )
        conn.execute(
            """
            INSERT INTO historical_replay_runs_v1(id, replay_version)
            VALUES(1, 'HISTORICAL_REPLAY_V1');
            """
        )

        for proposal_id in range(1, 150):
            candidate_id = proposal_id if proposal_id <= 15 else None
            expiration = (
                "2026-09-11"
                if proposal_id <= 4
                else "2026-09-14"
                if proposal_id in (5, 16)
                else "2026-09-18"
                if proposal_id <= 20
                else "2026-10-30"
            )

            if candidate_id is not None:
                conn.execute(
                    "INSERT INTO shadow_candidates(id) VALUES(?);",
                    (candidate_id,),
                )

            conn.execute(
                """
                INSERT INTO option_quotes(id, bid, ask)
                VALUES(?, 1.00, 1.10);
                """,
                (proposal_id,),
            )
            conn.execute(
                """
                INSERT INTO hypothesis_scanner_evaluations(
                    id,
                    option_quote_id,
                    lower_strike,
                    upper_strike,
                    delta,
                    implied_volatility,
                    iv_residual,
                    abs_iv_residual,
                    residual_threshold
                ) VALUES(
                    ?, ?, 95.0, 105.0, 0.50, 0.25, 0.04, 0.04, 0.03
                );
                """,
                (proposal_id, proposal_id),
            )
            conn.execute(
                """
                INSERT INTO shadow_structure_proposals(
                    id,
                    research_run_id,
                    hypothesis_evaluation_id,
                    underlying,
                    expiration,
                    right,
                    target_strike,
                    structure_id,
                    structure_json,
                    entry_pricing_json,
                    max_theoretical_loss_minor,
                    risk_currency,
                    proposal_state
                ) VALUES(
                    ?, 1, ?, 'AAPL', ?, 'C', 100.0,
                    'LONG_1_2_1_BUTTERFLY',
                    '{"legs":[]}',
                    '{"pricing":"decision_time"}',
                    10000,
                    'USD',
                    'PROPOSED'
                );
                """,
                (proposal_id, proposal_id, expiration),
            )

            decision = "ADMITTED" if proposal_id <= 15 else "BLOCKED"
            reason = (
                "SHADOW_RESEARCH_ADMITTED_WITHIN_EUR_500_CAP"
                if proposal_id <= 15
                else "ACTIVE_PORTFOLIO_EXCEEDS_EUR_500_BANKROLL"
            )
            conn.execute(
                """
                INSERT INTO shadow_admission_decisions(
                    id,
                    candidate_id,
                    proposal_id,
                    decided_at,
                    reason_code,
                    estimated_cost_usd_minor,
                    reserved_risk_usd_minor,
                    decision
                ) VALUES(
                    ?, ?, ?, '2026-09-04T15:00:00Z', ?, 100, 10100, ?
                );
                """,
                (
                    proposal_id,
                    candidate_id,
                    proposal_id,
                    reason,
                    decision,
                ),
            )

            if proposal_id > 15:
                conn.execute(
                    """
                    INSERT INTO historical_policy_replay_v1(
                        id,
                        replay_run_id,
                        original_admission_decision_id,
                        proposal_id,
                        original_decided_at,
                        original_reason_code,
                        estimated_cost_usd_minor,
                        intrinsic_risk_usd_minor,
                        counterfactual_decision
                    ) VALUES(
                        ?, 1, ?, ?,
                        '2026-09-04T15:00:00Z',
                        'ACTIVE_PORTFOLIO_EXCEEDS_EUR_500_BANKROLL',
                        100,
                        10100,
                        'WOULD_ADMIT'
                    );
                    """,
                    (proposal_id, proposal_id, proposal_id),
                )

        # The exact six mature rows seen at freeze time are present but
        # unresolved. No recovered outcome label exists.
        outcome_id = 1
        for proposal_id in (1, 2, 3, 4, 5):
            conn.execute(
                """
                INSERT INTO historical_outcome_recovery_v1(
                    id,
                    replay_run_id,
                    source_population,
                    source_candidate_id,
                    policy_replay_id,
                    proposal_id,
                    recovery_state,
                    reason_code,
                    measurement_role,
                    outcome_eligible,
                    estimated_net_pnl_usd_minor
                ) VALUES(
                    ?, 1, 'PROSPECTIVE_ORIGINAL', ?, NULL, ?,
                    'UNRESOLVED',
                    'MISSING_EXPIRY_SESSION_UNDERLYING_SNAPSHOT',
                    'RETROSPECTIVE_EXPIRY_RECONSTRUCTION',
                    0,
                    NULL
                );
                """,
                (outcome_id, proposal_id, proposal_id),
            )
            outcome_id += 1

        conn.execute(
            """
            INSERT INTO historical_outcome_recovery_v1(
                id,
                replay_run_id,
                source_population,
                source_candidate_id,
                policy_replay_id,
                proposal_id,
                recovery_state,
                reason_code,
                measurement_role,
                outcome_eligible,
                estimated_net_pnl_usd_minor
            ) VALUES(
                ?, 1, 'RETROSPECTIVE_POLICY_REPLAY', NULL, 16, 16,
                'UNRESOLVED',
                'MISSING_EXPIRY_SESSION_UNDERLYING_SNAPSHOT',
                'RETROSPECTIVE_EXPIRY_RECONSTRUCTION',
                0,
                NULL
            );
            """,
            (outcome_id,),
        )

        conn.commit()

        apply_migration_file(
            conn,
            MIGRATION,
            expected_from=32,
            target_version=33,
        )
    finally:
        conn.close()


def test_freeze_snapshots_exact_fixed_cohort_and_prelabel_state(
    tmp_path: Path,
) -> None:
    db = tmp_path / "rejection_audit.db"
    _build_v32(db)

    first = freeze_counterfactual_rejection_audit_v1(db_path=db)
    second = freeze_counterfactual_rejection_audit_v1(db_path=db)

    assert first.created is True
    assert second.created is False
    assert first.cohort_n == 149
    assert first.admitted_n == 15
    assert first.wallet_rejected_n == 134
    assert first.cohort_max_expiration == "2026-10-30"

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        program = conn.execute(
            """
            SELECT *
            FROM counterfactual_rejection_audit_programs_v1;
            """
        ).fetchone()
        counts = conn.execute(
            """
            SELECT selection_group, COUNT(*) AS n
            FROM counterfactual_rejection_audit_cohort_v1
            GROUP BY selection_group
            ORDER BY selection_group;
            """
        ).fetchall()
        discovery = json.loads(program["discovery_context_json"])
        feature = json.loads(
            conn.execute(
                """
                SELECT decision_time_features_json
                FROM counterfactual_rejection_audit_cohort_v1
                ORDER BY id
                LIMIT 1;
                """
            ).fetchone()[0]
        )
    finally:
        conn.close()

    assert [(row["selection_group"], row["n"]) for row in counts] == [
        (ADMITTED_GROUP, 15),
        (REJECTED_GROUP, 134),
    ]

    assert program["wallet_feature_enabled"] == 0
    assert program["independent_leg_liquidation_label_enabled"] == 0
    assert program["p_values_enabled"] == 0
    assert program["model_training_enabled"] == 0
    assert program["admission_change_enabled"] == 0
    assert program["decision_enabled"] == 0

    assert discovery["fixed_cohort"] == {
        "total": 149,
        "admitted_at_time": 15,
        "rejected_at_time_wallet_only": 134,
        "decision_time_feature_coverage_complete": 149,
        "feature_coverage_fields": [
            "iv_residual",
            "delta",
            "implied_volatility",
            "target_quote_spread",
            "structure_and_entry",
            "defined_max_loss",
        ],
    }

    outcome = discovery["outcome_state_at_freeze"]
    assert outcome["latest_completed_session_date"] == "2026-09-17"
    assert outcome["matured_before_latest_session"] == 6
    assert outcome["recovered"] == 0
    assert outcome["unresolved"] == 6
    assert outcome["no_recovery_record"] == 143
    assert outcome["unresolved_reason_counts"] == {
        "MISSING_EXPIRY_SESSION_UNDERLYING_SNAPSHOT": 6
    }

    assert feature["feature_timing"] == "DECISION_TIME_ONLY"
    assert feature["wallet_or_account_balance_included"] is False


def test_freeze_refuses_after_sep18_research_evidence(
    tmp_path: Path,
) -> None:
    db = tmp_path / "late_rejection_audit.db"
    _build_v32(db)

    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            INSERT INTO research_runs(id, us_session_date, status)
            VALUES(2, '2026-09-18', 'COMPLETED');
            """
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        CounterfactualRejectionAuditError,
        match="expected exactly '2026-09-17'",
    ):
        freeze_counterfactual_rejection_audit_v1(db_path=db)


def test_freeze_refuses_if_recovered_label_already_exists(
    tmp_path: Path,
) -> None:
    db = tmp_path / "labeled_rejection_audit.db"
    _build_v32(db)

    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            UPDATE historical_outcome_recovery_v1
            SET recovery_state = 'RECOVERED',
                reason_code = 'TEST_RECOVERED',
                estimated_net_pnl_usd_minor = 123
            WHERE id = 1;
            """
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        CounterfactualRejectionAuditError,
        match="recovered outcome labels already exist",
    ):
        freeze_counterfactual_rejection_audit_v1(db_path=db)


def test_final_evaluation_refuses_intermediate_peeking(
    tmp_path: Path,
) -> None:
    db = tmp_path / "peeking_rejection_audit.db"
    _build_v32(db)
    freeze_counterfactual_rejection_audit_v1(db_path=db)

    with pytest.raises(
        CounterfactualRejectionAuditError,
        match="is not yet allowed",
    ):
        evaluate_counterfactual_rejection_audit_v1(db_path=db)


def test_final_evaluation_requires_recovery_attempt_for_full_cohort(
    tmp_path: Path,
) -> None:
    db = tmp_path / "coverage_rejection_audit.db"
    _build_v32(db)
    freeze_counterfactual_rejection_audit_v1(db_path=db)

    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            INSERT INTO research_runs(id, us_session_date, status)
            VALUES(2, '2026-11-02', 'COMPLETED');
            """
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        CounterfactualRejectionAuditError,
        match="outcome recovery has not been attempted",
    ):
        evaluate_counterfactual_rejection_audit_v1(db_path=db)

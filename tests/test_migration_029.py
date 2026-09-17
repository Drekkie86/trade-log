from __future__ import annotations

import sqlite3

import pytest

from src.database.repository import EXPECTED_SCHEMA_VERSION, get_connection, get_schema_version


NEW_TABLES = {
    "shadow_intrinsic_admission_decisions_v1",
    "shadow_intrinsic_risk_plans_v1",
    "shadow_intrinsic_risk_plan_recordings_v1",
    "shadow_intrinsic_risk_assessments_v1",
    "shadow_intrinsic_risk_exit_outcomes_v1",
    "prospective_research_hypothesis_evaluations_v1",
}

NEW_VIEWS = {
    "v_shadow_admission_decisions_all",
    "v_shadow_intrinsic_risk_current_v1",
    "v_shadow_risk_current_v2",
    "v_prospective_research_hypothesis_latest_v1",
}


def _columns(conn, table: str) -> set[str]:
    return {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({table});").fetchall()
    }


def test_schema_v29_adds_account_independent_risk_surfaces(db_path):
    # This test owns the objects introduced by v29; later additive migrations
    # must not make it assert that v29 is still the repository's final schema.
    assert get_schema_version(db_path) == EXPECTED_SCHEMA_VERSION

    conn = get_connection(db_path)
    try:
        objects = {
            (str(row[0]), str(row[1]))
            for row in conn.execute(
                """
                SELECT name, type
                FROM sqlite_master
                WHERE type IN ('table','view');
                """
            ).fetchall()
        }
        plan_columns = _columns(conn, "shadow_intrinsic_risk_plans_v1")
        admission_columns = _columns(
            conn, "shadow_intrinsic_admission_decisions_v1"
        )
    finally:
        conn.close()

    assert all((name, "table") in objects for name in NEW_TABLES)
    assert all((name, "view") in objects for name in NEW_VIEWS)

    assert "risk_basis_eur_minor" in plan_columns
    assert "bankroll_cap_eur_minor" not in plan_columns
    assert "account_balance" not in plan_columns
    assert "wallet_balance" not in plan_columns

    assert "intrinsic_risk_eur_minor" in admission_columns
    assert "bankroll_cap_eur_minor" not in admission_columns


def test_schema_v29_preserves_legacy_bankroll_evidence_tables(db_path):
    conn = get_connection(db_path)
    try:
        legacy_admission = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table' AND name='shadow_admission_decisions';
            """
        ).fetchone()
        legacy_risk = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table' AND name='shadow_risk_plans';
            """
        ).fetchone()
    finally:
        conn.close()

    assert legacy_admission is not None
    assert legacy_risk is not None


def test_v29_intrinsic_risk_evidence_is_immutable(db_path):
    conn = get_connection(db_path)
    try:
        with conn:
            # The persistence triggers are part of the contract. Use a minimal
            # direct row with FK checks temporarily disabled only to isolate the
            # immutability trigger itself from unrelated fixture setup.
            conn.execute("PRAGMA foreign_keys=OFF;")
            conn.execute(
                """
                INSERT INTO shadow_intrinsic_admission_decisions_v1(
                    id, proposal_id, fx_observation_id, candidate_id,
                    risk_policy_version, cost_model_version, cost_provenance,
                    proposal_max_loss_usd_minor, estimated_cost_usd_minor,
                    intrinsic_risk_usd_minor, converted_max_loss_eur_minor,
                    estimated_cost_eur_minor, intrinsic_risk_eur_minor,
                    decision, reason_code, decided_at, evidence_json
                ) VALUES (
                    999999, 999999, 999999, 999999,
                    'TEST_INTRINSIC_POLICY', 'TEST_COST', 'TEST',
                    100, 10, 110, 90, 9, 99,
                    'ADMITTED', 'TEST', '2026-09-17T00:00:00Z', '{}'
                );
                """
            )

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                """
                UPDATE shadow_intrinsic_admission_decisions_v1
                SET reason_code='MUTATED'
                WHERE id=999999;
                """
            )
        conn.rollback()

        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            conn.execute(
                "DELETE FROM shadow_intrinsic_admission_decisions_v1 WHERE id=999999;"
            )
        conn.rollback()
    finally:
        conn.close()

import sqlite3
from pathlib import Path

import pytest

from src.database.migration_runner import apply_migration_sql

M = Path(__file__).resolve().parents[1] / "migrations" / "027_pre_rc_integrity_hardening.sql"


def seed(conn):
    conn.executescript("""
    CREATE TABLE schema_version(version INTEGER PRIMARY KEY, applied_at TEXT);
    INSERT INTO schema_version VALUES(26,'x');
    CREATE TABLE shadow_candidates(id INTEGER PRIMARY KEY, surfaced_at TEXT);
    CREATE TABLE shadow_mark_observations(
      id INTEGER PRIMARY KEY, candidate_id INTEGER, observed_at TEXT,
      estimated_net_pnl_eur_minor INTEGER,
      measurement_role TEXT NOT NULL DEFAULT 'INDEPENDENT_LEG_LIQUIDATION_STRESS',
      outcome_eligible INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE shadow_risk_plans(
      id INTEGER PRIMARY KEY, candidate_id INTEGER NOT NULL UNIQUE,
      created_at TEXT NOT NULL, plan_version TEXT NOT NULL, actor TEXT NOT NULL,
      bankroll_cap_eur_minor INTEGER NOT NULL, max_defined_loss_eur_minor INTEGER NOT NULL,
      reserved_risk_eur_minor INTEGER NOT NULL, stop_loss_fraction REAL, time_stop_at TEXT,
      thesis_invalidation_rule TEXT, event_stop_rule TEXT, entry_assumption_json TEXT NOT NULL, notes TEXT
    );
    CREATE TABLE shadow_risk_assessments(
      id INTEGER PRIMARY KEY, risk_plan_id INTEGER NOT NULL, candidate_id INTEGER NOT NULL,
      shadow_mark_id INTEGER, observed_at TEXT NOT NULL, assessment_version TEXT NOT NULL,
      mark_net_pnl_eur_minor INTEGER, loss_fraction_reserved REAL,
      price_stop_state TEXT NOT NULL, time_stop_state TEXT NOT NULL,
      thesis_stop_state TEXT NOT NULL, event_stop_state TEXT NOT NULL,
      overall_state TEXT NOT NULL, reason_codes_json TEXT NOT NULL, evidence_json TEXT NOT NULL
    );
    CREATE VIEW v_shadow_risk_current AS SELECT id AS risk_plan_id,candidate_id FROM shadow_risk_plans;
    INSERT INTO shadow_candidates VALUES(1,'2026-09-01T14:00:00Z');
    INSERT INTO shadow_candidates VALUES(2,'2026-09-01T14:00:00Z');
    """)
    conn.commit()


def migrate(conn):
    apply_migration_sql(conn, M.read_text(), expected_from=26, target_version=27)


def test_new_plan_is_db_recorded_and_prior_mark_is_hard_refusal():
    conn = sqlite3.connect(":memory:")
    seed(conn); migrate(conn)
    conn.execute("INSERT INTO shadow_risk_plans VALUES(1,1,'2000-01-01T00:00:00Z','v','x',50000,1000,1000,NULL,NULL,NULL,NULL,'{}',NULL)")
    row = conn.execute("SELECT prospectivity_state, recorded_at FROM shadow_risk_plan_recordings WHERE risk_plan_id=1").fetchone()
    assert row[0] == 'DB_RECORDED_PROSPECTIVE'
    assert row[1]
    conn.execute("INSERT INTO shadow_mark_observations(id,candidate_id,observed_at) VALUES(9,2,'2026-09-01T14:05:00Z')")
    with pytest.raises(sqlite3.IntegrityError, match="already has shadow marks"):
        conn.execute("INSERT INTO shadow_risk_plans VALUES(2,2,'1999-01-01T00:00:00Z','v','x',50000,1000,1000,NULL,NULL,NULL,NULL,'{}',NULL)")


def test_exit_trigger_is_separate_measurement_population():
    conn = sqlite3.connect(":memory:")
    seed(conn); migrate(conn)
    conn.execute("INSERT INTO shadow_risk_plans VALUES(1,1,'2026-09-01T14:00:00Z','v','x',50000,1000,1000,NULL,NULL,NULL,NULL,'{}',NULL)")
    conn.execute("INSERT INTO shadow_mark_observations VALUES(10,1,'2026-09-01T14:05:00Z',-700,'VALIDATED_PACKAGE_OUTCOME',1)")
    conn.execute("""INSERT INTO shadow_risk_assessments VALUES(
      20,1,1,10,'2026-09-01T14:05:00Z','v',-700,.7,
      'BREACHED','NOT_CONFIGURED','NOT_CONFIGURED','NOT_CONFIGURED','EXIT_TRIGGERED','[]','{}')""")
    row = conn.execute("SELECT measurement_role,evidence_eligible,estimated_net_pnl_eur_minor FROM shadow_risk_exit_outcomes").fetchone()
    assert row == ('PREDECLARED_RISK_EXIT_OUTCOME',1,-700)
    roles = {r[0] for r in conn.execute("SELECT measurement_role FROM v_shadow_outcome_populations_v1")}
    assert roles == {'VALIDATED_PACKAGE_OUTCOME','PREDECLARED_RISK_EXIT_OUTCOME'}

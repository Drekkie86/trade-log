import sqlite3
from pathlib import Path

import pytest


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "026_shadow_risk_plan_lifecycle.sql"
)


def _base(conn):
    conn.executescript(
        """
        CREATE TABLE schema_version(
            version INTEGER PRIMARY KEY,
            applied_at TEXT
        );
        INSERT INTO schema_version VALUES(25,'x');

        CREATE TABLE shadow_candidates(
            id INTEGER PRIMARY KEY,
            surfaced_at TEXT,
            max_theoretical_loss_minor INTEGER
        );

        CREATE TABLE shadow_mark_observations(
            id INTEGER PRIMARY KEY,
            candidate_id INTEGER,
            observed_at TEXT,
            estimated_net_pnl_eur_minor INTEGER
        );

        INSERT INTO shadow_candidates VALUES(1,'2026-09-01T14:00:00Z',5000);
        INSERT INTO shadow_candidates VALUES(2,'2026-09-01T14:00:00Z',5000);
        """
    )


def test_migration_026_creates_immutable_risk_evidence(tmp_path):
    db = tmp_path / "x.db"
    conn = sqlite3.connect(db)
    _base(conn)
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 26

    conn.execute(
        """
        INSERT INTO shadow_risk_plans(
            candidate_id,created_at,plan_version,actor,
            bankroll_cap_eur_minor,max_defined_loss_eur_minor,
            reserved_risk_eur_minor,entry_assumption_json
        )
        VALUES(1,'2026-09-01T14:01:00Z','v','x',50000,5000,5000,'{}')
        """
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE shadow_risk_plans SET actor='y'")


def test_migration_026_rejects_cross_candidate_mark_link(tmp_path):
    db = tmp_path / "x.db"
    conn = sqlite3.connect(db)
    _base(conn)
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))

    conn.execute(
        """
        INSERT INTO shadow_risk_plans(
            candidate_id,created_at,plan_version,actor,
            bankroll_cap_eur_minor,max_defined_loss_eur_minor,
            reserved_risk_eur_minor,entry_assumption_json
        )
        VALUES(1,'2026-09-01T14:01:00Z','v','x',50000,5000,5000,'{}')
        """
    )
    risk_plan_id = conn.execute(
        "SELECT id FROM shadow_risk_plans WHERE candidate_id=1"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO shadow_mark_observations
        VALUES(99,2,'2026-09-01T14:05:00Z',-100)
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="same candidate"):
        conn.execute(
            """
            INSERT INTO shadow_risk_assessments(
                risk_plan_id,candidate_id,shadow_mark_id,observed_at,
                assessment_version,price_stop_state,time_stop_state,
                thesis_stop_state,event_stop_state,overall_state,
                reason_codes_json,evidence_json
            )
            VALUES(?,1,99,'2026-09-01T14:05:00Z','v',
                   'CLEAR','NOT_CONFIGURED','NOT_CONFIGURED',
                   'NOT_CONFIGURED','CLEAR','[]','{}')
            """,
            (risk_plan_id,),
        )



def test_shadow_risk_plan_delete_is_blocked(tmp_path):
    db = tmp_path / "delete.db"
    conn = sqlite3.connect(db)
    _base(conn)
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    conn.execute("""
      INSERT INTO shadow_risk_plans(
        candidate_id,created_at,plan_version,actor,bankroll_cap_eur_minor,
        max_defined_loss_eur_minor,reserved_risk_eur_minor,entry_assumption_json
      ) VALUES(1,'2026-09-01T14:01:00Z','v','x',50000,5000,5000,'{}')
    """)
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        conn.execute("DELETE FROM shadow_risk_plans WHERE candidate_id=1")

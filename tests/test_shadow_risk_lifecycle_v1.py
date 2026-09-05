import sqlite3
from pathlib import Path

import pytest

from src.decision.risk_lifecycle import (
    create_frozen_risk_plan,
    evaluate_risk_plan,
    monitor_frozen_risk_plans,
    record_risk_assessment,
)


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "026_shadow_risk_plan_lifecycle.sql"
)


def seed(db):
    conn = sqlite3.connect(db)
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

        INSERT INTO shadow_candidates
        VALUES(1,'2026-09-01T14:00:00+00:00',5000);

        INSERT INTO shadow_candidates
        VALUES(2,'2026-09-01T14:00:00+00:00',5000);
        """
    )
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    conn.close()


def test_price_and_time_stop(tmp_path):
    db = tmp_path / "x.db"
    seed(db)
    plan = create_frozen_risk_plan(
        candidate_id=1,
        max_defined_loss_eur_minor=5000,
        reserved_risk_eur_minor=5000,
        stop_loss_fraction=0.5,
        time_stop_at="2026-09-02T14:00:00+00:00",
        created_at="2026-09-01T14:01:00+00:00",
        db_path=db,
    )
    assessment = evaluate_risk_plan(
        plan,
        observed_at="2026-09-01T15:00:00+00:00",
        mark_net_pnl_eur_minor=-2600,
    )
    assert assessment.overall_state == "EXIT_TRIGGERED"


def test_manual_rule_requires_review(tmp_path):
    db = tmp_path / "x.db"
    seed(db)
    plan = create_frozen_risk_plan(
        candidate_id=1,
        max_defined_loss_eur_minor=5000,
        reserved_risk_eur_minor=5000,
        thesis_invalidation_rule="anomaly disappears",
        created_at="2026-09-01T14:01:00+00:00",
        db_path=db,
    )
    assert (
        evaluate_risk_plan(
            plan,
            observed_at="2026-09-01T15:00:00+00:00",
        ).overall_state
        == "REVIEW_REQUIRED"
    )


def test_bankroll_cap(tmp_path):
    db = tmp_path / "x.db"
    seed(db)
    with pytest.raises(ValueError, match="€500"):
        create_frozen_risk_plan(
            candidate_id=1,
            max_defined_loss_eur_minor=5000,
            reserved_risk_eur_minor=50001,
            created_at="2026-09-01T14:01:00+00:00",
            db_path=db,
        )


def test_retrospective_plan_is_refused(tmp_path):
    db = tmp_path / "x.db"
    seed(db)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO shadow_mark_observations
        VALUES(10,1,'2026-09-01T14:05:00+00:00',-100)
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="Prospective risk plan refused"):
        create_frozen_risk_plan(
            candidate_id=1,
            max_defined_loss_eur_minor=5000,
            reserved_risk_eur_minor=5000,
            created_at="2026-09-01T14:06:00+00:00",
            db_path=db,
        )


def test_assessment_cannot_predate_plan(tmp_path):
    db = tmp_path / "x.db"
    seed(db)
    plan = create_frozen_risk_plan(
        candidate_id=1,
        max_defined_loss_eur_minor=5000,
        reserved_risk_eur_minor=5000,
        created_at="2026-09-01T14:10:00+00:00",
        db_path=db,
    )
    with pytest.raises(ValueError, match="cannot predate"):
        evaluate_risk_plan(
            plan,
            observed_at="2026-09-01T14:09:00+00:00",
        )


def test_wrong_candidate_shadow_mark_is_refused(tmp_path):
    db = tmp_path / "x.db"
    seed(db)
    create_frozen_risk_plan(
        candidate_id=1,
        max_defined_loss_eur_minor=5000,
        reserved_risk_eur_minor=5000,
        created_at="2026-09-01T14:01:00+00:00",
        db_path=db,
    )
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO shadow_mark_observations
        VALUES(11,2,'2026-09-01T14:05:00+00:00',-100)
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="different candidate"):
        record_risk_assessment(
            candidate_id=1,
            shadow_mark_id=11,
            observed_at="2026-09-01T14:05:00+00:00",
            db_path=db,
        )


def test_shadow_mark_timestamp_and_pnl_are_authoritative(tmp_path):
    db = tmp_path / "x.db"
    seed(db)
    create_frozen_risk_plan(
        candidate_id=1,
        max_defined_loss_eur_minor=5000,
        reserved_risk_eur_minor=5000,
        created_at="2026-09-01T14:01:00+00:00",
        db_path=db,
    )
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO shadow_mark_observations
        VALUES(12,1,'2026-09-01T14:05:00+00:00',-100)
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="timestamp"):
        record_risk_assessment(
            candidate_id=1,
            shadow_mark_id=12,
            observed_at="2026-09-01T14:06:00+00:00",
            db_path=db,
        )

    with pytest.raises(ValueError, match="P&L conflicts"):
        record_risk_assessment(
            candidate_id=1,
            shadow_mark_id=12,
            observed_at="2026-09-01T14:05:00+00:00",
            mark_net_pnl_eur_minor=-999,
            db_path=db,
        )


def test_monitor_records_all_unassessed_marks(tmp_path):
    db = tmp_path / "x.db"
    seed(db)
    create_frozen_risk_plan(
        candidate_id=1,
        max_defined_loss_eur_minor=5000,
        reserved_risk_eur_minor=5000,
        stop_loss_fraction=0.5,
        created_at="2026-09-01T14:01:00+00:00",
        db_path=db,
    )
    conn = sqlite3.connect(db)
    conn.executemany(
        """
        INSERT INTO shadow_mark_observations(
            id,candidate_id,observed_at,estimated_net_pnl_eur_minor
        )
        VALUES(?,?,?,?)
        """,
        [
            (20,1,"2026-09-01T14:05:00+00:00",-100),
            (21,1,"2026-09-01T14:10:00+00:00",-2600),
        ],
    )
    conn.commit()
    conn.close()

    result = monitor_frozen_risk_plans(db_path=db)
    assert result["recorded"] == 2

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """
            SELECT shadow_mark_id, overall_state
            FROM shadow_risk_assessments
            ORDER BY shadow_mark_id
            """
        ).fetchall()
    finally:
        conn.close()

    assert rows == [(20, "CLEAR"), (21, "EXIT_TRIGGERED")]

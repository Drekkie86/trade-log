import sqlite3
from datetime import datetime, timedelta, timezone
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


def _after_recorded(plan, *, minutes: int) -> str:
    recorded = datetime.fromisoformat(
        plan.recorded_at.replace("Z", "+00:00")
    )
    return (
        recorded + timedelta(minutes=minutes)
    ).isoformat()


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
            estimated_net_pnl_eur_minor INTEGER,
            measurement_role TEXT NOT NULL DEFAULT 'INDEPENDENT_LEG_LIQUIDATION_STRESS',
            outcome_eligible INTEGER NOT NULL DEFAULT 0
        );

        INSERT INTO shadow_candidates
        VALUES(1,'2026-09-08T14:00:00+00:00',5000);

        INSERT INTO shadow_candidates
        VALUES(2,'2026-09-08T14:00:00+00:00',5000);
        """
    )
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    conn.executescript((
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "027_pre_rc_integrity_hardening.sql"
    ).read_text(encoding="utf-8"))
    conn.close()


def test_price_and_time_stop(tmp_path):
    db = tmp_path / "x.db"
    seed(db)

    time_stop_at = (
        datetime.now(timezone.utc)
        + timedelta(days=1)
    ).isoformat()

    plan = create_frozen_risk_plan(
        candidate_id=1,
        max_defined_loss_eur_minor=5000,
        reserved_risk_eur_minor=5000,
        stop_loss_fraction=0.5,
        time_stop_at=time_stop_at,
        created_at="2026-09-08T14:01:00+00:00",
        db_path=db,
    )

    price_assessment = evaluate_risk_plan(
        plan,
        observed_at=_after_recorded(plan, minutes=1),
        mark_net_pnl_eur_minor=-2600,
    )
    assert price_assessment.price_stop_state == "BREACHED"
    assert price_assessment.time_stop_state == "CLEAR"
    assert price_assessment.overall_state == "EXIT_TRIGGERED"

    after_time_stop = (
        datetime.fromisoformat(time_stop_at)
        + timedelta(minutes=1)
    ).isoformat()
    time_assessment = evaluate_risk_plan(
        plan,
        observed_at=after_time_stop,
    )
    assert time_assessment.time_stop_state == "BREACHED"
    assert time_assessment.overall_state == "EXIT_TRIGGERED"


def test_manual_rule_requires_review(tmp_path):
    db = tmp_path / "x.db"
    seed(db)
    plan = create_frozen_risk_plan(
        candidate_id=1,
        max_defined_loss_eur_minor=5000,
        reserved_risk_eur_minor=5000,
        thesis_invalidation_rule="anomaly disappears",
        created_at="2026-09-08T14:01:00+00:00",
        db_path=db,
    )
    assert (
        evaluate_risk_plan(
            plan,
            observed_at=_after_recorded(plan, minutes=1),
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
            created_at="2026-09-08T14:01:00+00:00",
            db_path=db,
        )


def test_retrospective_plan_is_refused(tmp_path):
    db = tmp_path / "x.db"
    seed(db)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO shadow_mark_observations(id,candidate_id,observed_at,estimated_net_pnl_eur_minor)
        VALUES(10,1,'2026-09-08T14:05:00+00:00',-100)
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="already has shadow marks"):
        create_frozen_risk_plan(
            candidate_id=1,
            max_defined_loss_eur_minor=5000,
            reserved_risk_eur_minor=5000,
            created_at="2026-09-08T14:01:00+00:00",
            db_path=db,
        )


def test_assessment_cannot_predate_plan(tmp_path):
    db = tmp_path / "x.db"
    seed(db)
    plan = create_frozen_risk_plan(
        candidate_id=1,
        max_defined_loss_eur_minor=5000,
        reserved_risk_eur_minor=5000,
        created_at="2026-09-08T14:10:00+00:00",
        db_path=db,
    )
    from datetime import timedelta
    recorded = __import__("datetime").datetime.fromisoformat(plan.recorded_at.replace("Z", "+00:00"))
    before = (recorded - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="cannot predate"):
        evaluate_risk_plan(plan, observed_at=before)


def test_wrong_candidate_shadow_mark_is_refused(tmp_path):
    db = tmp_path / "x.db"
    seed(db)
    create_frozen_risk_plan(
        candidate_id=1,
        max_defined_loss_eur_minor=5000,
        reserved_risk_eur_minor=5000,
        created_at="2026-09-08T14:01:00+00:00",
        db_path=db,
    )
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO shadow_mark_observations(id,candidate_id,observed_at,estimated_net_pnl_eur_minor)
        VALUES(11,2,'2026-09-08T14:05:00+00:00',-100)
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="different candidate"):
        record_risk_assessment(
            candidate_id=1,
            shadow_mark_id=11,
            observed_at="2026-09-08T14:05:00+00:00",
            db_path=db,
        )


def test_shadow_mark_timestamp_and_pnl_are_authoritative(tmp_path):
    db = tmp_path / "x.db"
    seed(db)
    create_frozen_risk_plan(
        candidate_id=1,
        max_defined_loss_eur_minor=5000,
        reserved_risk_eur_minor=5000,
        created_at="2026-09-08T14:01:00+00:00",
        db_path=db,
    )
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO shadow_mark_observations(id,candidate_id,observed_at,estimated_net_pnl_eur_minor)
        VALUES(12,1,'2026-09-08T14:05:00+00:00',-100)
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="timestamp"):
        record_risk_assessment(
            candidate_id=1,
            shadow_mark_id=12,
            observed_at="2026-09-08T14:06:00+00:00",
            db_path=db,
        )

    with pytest.raises(ValueError, match="P&L conflicts"):
        record_risk_assessment(
            candidate_id=1,
            shadow_mark_id=12,
            observed_at="2026-09-08T14:05:00+00:00",
            mark_net_pnl_eur_minor=-999,
            db_path=db,
        )


def test_monitor_records_all_unassessed_marks(tmp_path):
    db = tmp_path / "x.db"
    seed(db)
    plan = create_frozen_risk_plan(
        candidate_id=1,
        max_defined_loss_eur_minor=5000,
        reserved_risk_eur_minor=5000,
        stop_loss_fraction=0.5,
        created_at="2026-09-08T14:01:00+00:00",
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
            (20,1,_after_recorded(plan, minutes=5),-100),
            (21,1,_after_recorded(plan, minutes=10),-2600),
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

from datetime import datetime, timedelta, timezone

import pytest

from src.database.repository import get_connection
from src.decision.risk_lifecycle import (
    create_frozen_risk_plan,
    evaluate_risk_plan,
    record_risk_assessment,
)
from src.research.shadow_admission import admit_shadow_proposals
from src.research.shadow_outcome_collector_v2 import _persist_mark
from tests._shadow_admission_seed import fx, seed_proposal


def _candidate(db_path, *, max_loss_usd_minor=70_000):
    seeded = seed_proposal(
        db_path,
        max_loss_usd_minor=max_loss_usd_minor,
    )
    decision = admit_shadow_proposals(
        fx=fx(),
        proposal_ids=[seeded["proposal_id"]],
        db_path=db_path,
    ).decisions[0]
    assert decision.candidate_id is not None
    return seeded, decision


def _after_recorded(plan, *, minutes: int) -> str:
    recorded = datetime.fromisoformat(
        plan.recorded_at.replace("Z", "+00:00")
    )
    return (recorded + timedelta(minutes=minutes)).isoformat()


def test_risk_plan_above_500_eur_is_valid_intrinsic_risk(db_path):
    _, decision = _candidate(db_path, max_loss_usd_minor=80_000)

    plan = create_frozen_risk_plan(
        candidate_id=decision.candidate_id,
        max_defined_loss_eur_minor=decision.converted_max_loss_eur_minor,
        risk_basis_eur_minor=decision.intrinsic_risk_eur_minor,
        stop_loss_fraction=0.5,
        created_at="2026-09-01T18:02:00+00:00",
        db_path=db_path,
    )

    assert plan.risk_basis_eur_minor > 50_000
    assert plan.max_defined_loss_eur_minor <= plan.risk_basis_eur_minor

    conn = get_connection(db_path)
    try:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(shadow_intrinsic_risk_plans_v1);"
            ).fetchall()
        }
    finally:
        conn.close()

    assert "bankroll_cap_eur_minor" not in columns
    assert "account_balance" not in columns
    assert "risk_basis_eur_minor" in columns


def test_price_and_time_stops_use_intrinsic_risk_basis(db_path):
    _, decision = _candidate(db_path)
    time_stop_at = (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).isoformat()

    plan = create_frozen_risk_plan(
        candidate_id=decision.candidate_id,
        max_defined_loss_eur_minor=decision.converted_max_loss_eur_minor,
        risk_basis_eur_minor=decision.intrinsic_risk_eur_minor,
        stop_loss_fraction=0.5,
        time_stop_at=time_stop_at,
        created_at="2026-09-01T18:02:00+00:00",
        db_path=db_path,
    )

    loss = -(plan.risk_basis_eur_minor // 2 + 1)
    assessment = evaluate_risk_plan(
        plan,
        observed_at=_after_recorded(plan, minutes=1),
        mark_net_pnl_eur_minor=loss,
    )
    assert assessment.price_stop_state == "BREACHED"
    assert assessment.overall_state == "EXIT_TRIGGERED"
    assert assessment.loss_fraction_risk_basis is not None
    assert assessment.loss_fraction_risk_basis >= 0.5

    after_time_stop = (
        datetime.fromisoformat(time_stop_at) + timedelta(minutes=1)
    ).isoformat()
    time_assessment = evaluate_risk_plan(
        plan,
        observed_at=after_time_stop,
    )
    assert time_assessment.time_stop_state == "BREACHED"
    assert time_assessment.overall_state == "EXIT_TRIGGERED"


def test_legacy_reserved_risk_argument_is_only_a_compatibility_alias(db_path):
    _, decision = _candidate(db_path)

    plan = create_frozen_risk_plan(
        candidate_id=decision.candidate_id,
        max_defined_loss_eur_minor=decision.converted_max_loss_eur_minor,
        reserved_risk_eur_minor=decision.intrinsic_risk_eur_minor,
        created_at="2026-09-01T18:02:00+00:00",
        db_path=db_path,
    )

    assert plan.risk_basis_eur_minor == decision.intrinsic_risk_eur_minor


def test_retrospective_risk_plan_is_refused_after_any_shadow_mark(db_path):
    _, decision = _candidate(db_path)

    conn = get_connection(db_path)
    try:
        candidate = conn.execute(
            "SELECT research_run_id FROM shadow_candidates WHERE id = ?;",
            (decision.candidate_id,),
        ).fetchone()
    finally:
        conn.close()

    _persist_mark(
        candidate_id=decision.candidate_id,
        research_run_id=int(candidate["research_run_id"]),
        observed_at="2026-09-01T18:03:00+00:00",
        quality_state="INCOMPLETE_LEG_MARK",
        entry_fx_observation_id=decision.fx_observation_id,
        structure_mark_usd_minor=None,
        gross_pnl_usd_minor=None,
        estimated_net_pnl_usd_minor=None,
        gross_pnl_eur_minor=None,
        estimated_net_pnl_eur_minor=None,
        evidence_json="{}",
        db_path=db_path,
    )

    with pytest.raises(ValueError, match="already has shadow marks"):
        create_frozen_risk_plan(
            candidate_id=decision.candidate_id,
            max_defined_loss_eur_minor=decision.converted_max_loss_eur_minor,
            risk_basis_eur_minor=decision.intrinsic_risk_eur_minor,
            created_at="2026-09-01T18:02:00+00:00",
            db_path=db_path,
        )


def test_persisted_mark_is_authoritative_for_risk_assessment(db_path):
    _, decision = _candidate(db_path)
    plan = create_frozen_risk_plan(
        candidate_id=decision.candidate_id,
        max_defined_loss_eur_minor=decision.converted_max_loss_eur_minor,
        risk_basis_eur_minor=decision.intrinsic_risk_eur_minor,
        stop_loss_fraction=0.5,
        created_at="2026-09-01T18:02:00+00:00",
        db_path=db_path,
    )

    observed_at = _after_recorded(plan, minutes=5)
    conn = get_connection(db_path)
    try:
        run_id = int(
            conn.execute(
                "SELECT research_run_id FROM shadow_candidates WHERE id = ?;",
                (decision.candidate_id,),
            ).fetchone()[0]
        )
    finally:
        conn.close()

    mark_id = _persist_mark(
        candidate_id=decision.candidate_id,
        research_run_id=run_id,
        observed_at=observed_at,
        quality_state="COMPLETE_UNVERIFIED_FRESHNESS",
        entry_fx_observation_id=decision.fx_observation_id,
        structure_mark_usd_minor=0,
        gross_pnl_usd_minor=-100,
        estimated_net_pnl_usd_minor=-100,
        gross_pnl_eur_minor=-80,
        estimated_net_pnl_eur_minor=-80,
        evidence_json="{}",
        db_path=db_path,
    )

    with pytest.raises(ValueError, match="timestamp"):
        record_risk_assessment(
            candidate_id=decision.candidate_id,
            shadow_mark_id=mark_id,
            observed_at=_after_recorded(plan, minutes=6),
            db_path=db_path,
        )

    assessment = record_risk_assessment(
        candidate_id=decision.candidate_id,
        shadow_mark_id=mark_id,
        observed_at=observed_at,
        db_path=db_path,
    )
    assert assessment.candidate_id == decision.candidate_id

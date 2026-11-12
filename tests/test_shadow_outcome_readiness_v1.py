import sqlite3
import pytest

from src.database.repository import get_connection
from src.research.shadow_admission import admit_shadow_proposals
from src.research.shadow_outcome_readiness_v1 import (
    inspect_candidate, inspect_recent
)
from tests._shadow_admission_seed import fx, seed_proposal


def one_candidate(db_path):
    s=seed_proposal(db_path)
    result=admit_shadow_proposals(fx=fx(),proposal_ids=[s["proposal_id"]],
                                   db_path=db_path)
    assert result.admitted_count==1
    return result.decisions[0]


def test_legacy_fresh_status_is_not_independent_outcome_validation(db_path):
    decision=one_candidate(db_path)
    report=inspect_candidate(decision.candidate_id,db_path=db_path)
    assert report.quote_freshness_label=="FRESH"
    assert report.readiness=="NOT_READY"
    assert not report.can_score
    assert "ENTRY_QUALITY_NOT_VERIFIED_AS_OF_ADMISSION" in report.blockers
    assert "PROVIDER_TIMESTAMP_LIVE_PROBE_UNVERIFIED" in report.blockers
    assert "PREDECLARED_RISK_EXIT_PLAN_MISSING" in report.blockers
    assert "NO_ELIGIBLE_PACKAGE_MARK" in report.blockers
    assert report.independent_leg_stress_marks==0
    assert report.predeclared_risk_plan_count==0


def test_fake_eligible_marker_does_not_bypass_independent_receipt(db_path):
    decision=one_candidate(db_path)
    conn=get_connection(db_path)
    try:
        row=conn.execute(
            "SELECT research_run_id FROM shadow_candidates WHERE id=?",
            (decision.candidate_id,)).fetchone()
        with conn:
            conn.execute(
                """INSERT INTO shadow_mark_observations (
                    candidate_id,research_run_id,observed_at,provider,
                    structure_mark_usd_minor, gross_pnl_usd_minor,
                    estimated_net_pnl_usd_minor, gross_pnl_eur_minor,
                    estimated_net_pnl_eur_minor, entry_fx_observation_id,
                    quality_state,measurement_role,outcome_eligible,evidence_json
                ) VALUES (?,?,'2026-09-01T19:00:00Z','THETADATA',
                          0,100,100,80,80,?,
                          'COMPLETE_UNVERIFIED_FRESHNESS',
                          'VALIDATED_PACKAGE_OUTCOME',1,'{}')""",
                (decision.candidate_id,int(row["research_run_id"]),
                 decision.fx_observation_id))
    finally:
        conn.close()
    report=inspect_candidate(decision.candidate_id,db_path=db_path)
    assert report.independently_validated_package_marks==1
    assert "ELIGIBLE_MARK_LACKS_INDEPENDENT_RECEIPT_RECONCILIATION" in report.blockers
    assert not report.can_score


def test_recent_audit_is_bounded_and_source_db_unchanged(db_path):
    one_candidate(db_path)
    c=get_connection(db_path)
    try:
        before=c.execute("SELECT COUNT(*) FROM shadow_candidates").fetchone()[0]
    finally:
        c.close()
    reports=inspect_recent(db_path=db_path,limit=1)
    assert len(reports)==1 and reports[0].readiness=="NOT_READY"
    c=get_connection(db_path)
    try:
        after=c.execute("SELECT COUNT(*) FROM shadow_candidates").fetchone()[0]
    finally:
        c.close()
    assert after==before


@pytest.mark.parametrize("limit",[0,33,-1,True])
def test_batch_boundaries_fail_closed(db_path,limit):
    with pytest.raises(ValueError,match="BATCH_OUT_OF_BOUNDS"):
        inspect_recent(db_path=db_path,limit=limit)


def test_unknown_candidate_fails_closed(db_path):
    with pytest.raises(ValueError,match="CANDIDATE_NOT_FOUND"):
        inspect_candidate(99999999,db_path=db_path)


def test_invalid_candidate_rejected(db_path):
    with pytest.raises(ValueError,match="INVALID_CANDIDATE_ID"):
        inspect_candidate(-1,db_path=db_path)

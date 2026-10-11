"""Gate A P0 regression checks: no unverified FRESH shadow admission.

Only synthetic, deliberately timestamped fixtures. Never live quotes/orders.
"""
from __future__ import annotations

import json

import pytest

from src.database.repository import get_connection
from src.research.shadow_entry_quote_quality_v1 import (
    QUALITY_POLICY_VERSION, evaluate_entry_quote_quality
)
from src.research.shadow_intrinsic_admission_v1 import admit_shadow_proposals
import src.research.shadow_intrinsic_admission_v1 as admission_impl
from tests._shadow_admission_seed import seed_proposal,fx

CLOCK = "2026-09-01T18:00:10.000Z"


@pytest.fixture(autouse=True)
def freeze_test_admission_clock(monkeypatch):
    monkeypatch.setattr(admission_impl,"_now_utc",lambda:CLOCK)


def proposal_row(db_path, proposal_id):
    c=get_connection(db_path)
    try:
        r=c.execute("SELECT * FROM shadow_structure_proposals WHERE id=?",
                    (proposal_id,)).fetchone()
        return dict(r)
    finally:c.close()


def test_three_distinct_leg_quotes_checked_and_audited(db_path):
    seeded=seed_proposal(db_path)
    p=proposal_row(db_path,seeded["proposal_id"])
    q=evaluate_entry_quote_quality(proposal=p,admission_at=CLOCK,db_path=db_path)
    assert q.reason_code is None
    assert q.freshness_class=="FRESH"
    assert q.evidence["eligible"] is True
    assert q.evidence["quality_policy_version"]==QUALITY_POLICY_VERSION
    assert len(q.evidence["leg_evidence"])==3
    assert len({x["quote_id"] for x in q.evidence["leg_evidence"]})==3
    assert len({x["snapshot_id"] for x in q.evidence["leg_evidence"]})==1

    result=admit_shadow_proposals(
        fx=fx(),proposal_ids=[seeded["proposal_id"]],db_path=db_path
    )
    assert result.admitted_count==1
    cid=result.decisions[0].candidate_id
    c=get_connection(db_path)
    try:
        cand=c.execute("SELECT quote_freshness_class FROM shadow_candidates WHERE id=?",
                       (cid,)).fetchone()
        row=c.execute(
            "SELECT decided_at,evidence_json FROM shadow_intrinsic_admission_decisions_v1 "
            "WHERE proposal_id=?",(seeded["proposal_id"],)
        ).fetchone()
    finally:c.close()
    assert cand["quote_freshness_class"]=="FRESH"
    evidence=json.loads(row["evidence_json"])["entry_quote_quality"]
    assert evidence["admission_at"]==row["decided_at"]==CLOCK
    assert evidence["eligible"] is True
    assert len(evidence["leg_evidence"])==3


def test_one_stale_wing_blocks_and_preserves_immutable_reason(db_path):
    seeded=seed_proposal(db_path,lower_wing_quote_at="2026-09-01T13:55:00")
    result=admit_shadow_proposals(
        fx=fx(),proposal_ids=[seeded["proposal_id"]],db_path=db_path
    )
    assert result.admitted_count==0
    assert result.blocked_count==1
    assert result.decisions[0].reason_code=="ENTRY_LEG_STALE_AT_ADMISSION"
    assert result.decisions[0].candidate_id is None
    again=admit_shadow_proposals(
        fx=fx(),proposal_ids=[seeded["proposal_id"]],db_path=db_path)
    assert again.decisions[0].decision=="BLOCKED"
    c=get_connection(db_path)
    try:
        assert c.execute("SELECT COUNT(*) FROM shadow_candidates").fetchone()[0]==0
        row=c.execute("SELECT evidence_json FROM shadow_intrinsic_admission_decisions_v1 "
                      "WHERE proposal_id=?",(seeded["proposal_id"],)).fetchone()
    finally:c.close()
    e=json.loads(row["evidence_json"])["entry_quote_quality"]
    assert e["eligible"] is False
    assert e["reason_code"]=="ENTRY_LEG_STALE_AT_ADMISSION"
    assert len(e["leg_evidence"])>=1
    assert max(x["quote_age_seconds"] for x in e["leg_evidence"])>60


def test_latest_provider_semantics_not_live_validated_blocks(db_path):
    seeded=seed_proposal(db_path)
    c=get_connection(db_path)
    try:
        with c:
            c.execute("""
                INSERT INTO thetadata_timestamp_semantics_v1_runs
                    (semantics_version,validated_at,documented_market_timezone,
                     summer_offset_hours,winter_offset_hours,aware_conversion_pass,
                     dst_contract_pass,documentation_contract_pass,
                     live_probe_state,confidence_state,evidence_json,decision_enabled)
                SELECT semantics_version,validated_at,documented_market_timezone,
                    summer_offset_hours,winter_offset_hours,aware_conversion_pass,
                    dst_contract_pass,documentation_contract_pass,
                    'NOT_RUN','DOCUMENTED_CONTRACT_VALIDATED_NOT_LIVE_PROBED',
                    evidence_json,0
                FROM thetadata_timestamp_semantics_v1_runs ORDER BY id DESC LIMIT 1
            """)
    finally:c.close()
    r=admit_shadow_proposals(
        fx=fx(),proposal_ids=[seeded["proposal_id"]],db_path=db_path
    )
    assert r.admitted_count==0
    assert r.decisions[0].reason_code=="ENTRY_PROVIDER_CLOCK_UNVERIFIED"


def test_reused_leg_quote_ids_and_cross_run_quotes_rejected(db_path):
    one=seed_proposal(db_path)
    two=seed_proposal(db_path)
    p=proposal_row(db_path,one["proposal_id"])
    duplicate=json.loads(p["structure_json"])
    duplicate["legs"][0]["option_quote_id"]=duplicate["legs"][1]["option_quote_id"]
    p["structure_json"]=json.dumps(duplicate)
    assert evaluate_entry_quote_quality(proposal=p,admission_at=CLOCK,db_path=db_path).reason_code=="ENTRY_LEG_QUOTE_IDS_REUSED"

    other=json.loads(proposal_row(db_path,two["proposal_id"])["structure_json"])
    duplicate["legs"][0]["option_quote_id"]=other["legs"][0]["option_quote_id"]
    p["structure_json"]=json.dumps(duplicate)
    assert evaluate_entry_quote_quality(proposal=p,admission_at=CLOCK,db_path=db_path).reason_code=="ENTRY_LEG_QUOTE_SNAPSHOT_OR_RUN_MISMATCH"


def test_time_bounds_do_not_guess_or_clamp_future(db_path):
    seeded=seed_proposal(db_path)
    p=proposal_row(db_path,seeded["proposal_id"])
    assert evaluate_entry_quote_quality(
        proposal=p,admission_at="2026-09-01T18:00:15Z",db_path=db_path
    ).reason_code is None
    assert evaluate_entry_quote_quality(
        proposal=p,admission_at="2026-09-01T18:00:16Z",db_path=db_path
    ).reason_code=="ENTRY_LEG_STALE_AT_ADMISSION"
    assert evaluate_entry_quote_quality(
        proposal=p,admission_at="2026-09-01T18:00:02Z",db_path=db_path
    ).reason_code=="ENTRY_LEG_FUTURE_SOURCE_TIMESTAMP"
    assert evaluate_entry_quote_quality(
        proposal=p,admission_at="2026-09-01T18:00:10",db_path=db_path
    ).reason_code=="ENTRY_STRUCTURE_TIMESTAMP_OR_LEGS_INVALID"


def test_option_identity_drift_is_not_a_valid_shadow_leg(db_path):
    seeded=seed_proposal(db_path)
    p=proposal_row(db_path,seeded["proposal_id"])
    bad=json.loads(p["structure_json"])
    bad["legs"][0]["strike"]=97
    p["structure_json"]=json.dumps(bad)
    result=evaluate_entry_quote_quality(proposal=p,admission_at=CLOCK,db_path=db_path)
    assert result.reason_code=="ENTRY_LEG_OPTION_IDENTITY_MISMATCH"

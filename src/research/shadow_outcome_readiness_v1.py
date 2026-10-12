"""Bounded read-only diagnostics for existing Christiania shadow outcomes.

An audit is NOT a score. Even if legacy rows say FRESH, this module refuses
to infer validated executable P&L without independently qualified evidence.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote

VERSION = "SHADOW_OUTCOME_READINESS_V1"
MAX_BATCH = 32


@dataclass(frozen=True)
class CandidateReadiness:
    candidate_id: int
    readiness: str
    blockers: tuple[str, ...]
    quote_freshness_label: str | None
    latest_state: str | None
    independent_leg_stress_marks: int
    independently_validated_package_marks: int
    existing_outcome_observations: int
    predeclared_risk_plan_count: int
    can_score: bool = False

    def as_dict(self):
        return asdict(self)


def _open_ro(db_path) -> sqlite3.Connection:
    p=Path(db_path).resolve()
    if not p.is_file():
        raise ValueError("READ_ONLY_DB_PATH_NOT_FOUND")
    db = sqlite3.connect("file:" + quote(p.as_posix(), safe="/:") + "?mode=ro",
                         uri=True, timeout=0.5)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA busy_timeout=500")
    return db


def inspect_candidate(candidate_id: int, *, db_path) -> CandidateReadiness:
    if type(candidate_id) is not int or candidate_id <= 0:
        raise ValueError("INVALID_CANDIDATE_ID")
    db=_open_ro(db_path)
    start=time.monotonic()
    db.set_progress_handler(lambda:int(time.monotonic()-start>2.0),1000)
    try:
        tables={r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        needed={"shadow_candidates","v_shadow_admission_decisions_all",
                "shadow_structure_proposals","shadow_state_events",
                "shadow_mark_observations","shadow_outcome_observations",
                "thetadata_timestamp_semantics_v1_runs"}
        if not needed <= tables:
            raise ValueError("SCHEMA_OUTCOME_READINESS_PREREQUISITES_MISSING:"+
                             ",".join(sorted(needed-tables)))
        c=db.execute(
            "SELECT id,quote_freshness_class FROM shadow_candidates "
            "WHERE id=? LIMIT 1",(candidate_id,)).fetchone()
        if c is None:
            raise ValueError("SHADOW_CANDIDATE_NOT_FOUND")
        ad=db.execute(
            """SELECT sad.decided_at,sad.decision_source,sad.evidence_json,
                      ssp.entry_pricing_json
               FROM v_shadow_admission_decisions_all AS sad
               JOIN shadow_structure_proposals AS ssp
                 ON ssp.id=sad.proposal_id
               WHERE sad.candidate_id=? AND sad.decision='ADMITTED'
               ORDER BY sad.decision_id DESC LIMIT 1""",(candidate_id,)).fetchone()
        latest=db.execute(
            "SELECT to_state FROM shadow_state_events WHERE candidate_id=? "
            "ORDER BY id DESC LIMIT 1",(candidate_id,)).fetchone()
        validation=db.execute(
            "SELECT confidence_state,live_probe_state,decision_enabled "
            "FROM thetadata_timestamp_semantics_v1_runs "
            "ORDER BY id DESC LIMIT 1").fetchone()
        marks=[dict(row) for row in db.execute(
            "SELECT measurement_role,outcome_eligible,COUNT(*) AS n "
            "FROM shadow_mark_observations WHERE candidate_id=? "
            "GROUP BY measurement_role,outcome_eligible",(candidate_id,)).fetchall()]
        counts=dict(db.execute(
            "SELECT COUNT(*) AS n FROM shadow_outcome_observations "
            "WHERE candidate_id=?",(candidate_id,)).fetchone())
        risk=0
        for risk_table in ("shadow_intrinsic_risk_plans_v1","shadow_risk_plans"):
            if risk_table in tables:
                risk+=int(db.execute(
                    f'SELECT COUNT(*) n FROM "{risk_table}" WHERE candidate_id=?',
                    (candidate_id,)).fetchone()[0])
        reason=set()
        if ad is None:
            reason.add("IMMUTABLE_ADMISSION_OR_PROPOSAL_MISSING")
        else:
            try:
                evidence=json.loads(ad["evidence_json"])
                entry=evidence.get("entry_quote_quality")
                if (not isinstance(entry,dict) or entry.get("eligible") is not True or
                    entry.get("quality_policy_version")!="SHADOW_ENTRY_PER_LEG_ASOF_15S_V1" or
                    entry.get("admission_at")!=ad["decided_at"]):
                    reason.add("ENTRY_QUALITY_NOT_VERIFIED_AS_OF_ADMISSION")
            except (ValueError,TypeError):
                reason.add("ADMISSION_EVIDENCE_UNPARSEABLE")
            if not ad["entry_pricing_json"]:
                reason.add("FROZEN_ENTRY_PRICES_MISSING")
        if not validation or (validation["confidence_state"]!="DOCUMENTED_AND_LIVE_VALIDATED"
                               or validation["live_probe_state"]!="PASSED"):
            reason.add("PROVIDER_TIMESTAMP_LIVE_PROBE_UNVERIFIED")
        if c["quote_freshness_class"]!="FRESH":
            reason.add("CANDIDATE_NOT_MARKED_FRESH")
        if risk==0:
            reason.add("PREDECLARED_RISK_EXIT_PLAN_MISSING")
        stress=sum(int(x["n"]) for x in marks
                   if x["measurement_role"]=="INDEPENDENT_LEG_LIQUIDATION_STRESS")
        labelled=sum(int(x["n"]) for x in marks
                     if x["measurement_role"]=="VALIDATED_PACKAGE_OUTCOME"
                     and x["outcome_eligible"]==1)
        if labelled==0:
            reason.add("NO_ELIGIBLE_PACKAGE_MARK")
        else:
            # Legacy marker-only rows have no independent receipt verifier.
            # Do not mistake synthetic test inserts for authentic provenance.
            reason.add("ELIGIBLE_MARK_LACKS_INDEPENDENT_RECEIPT_RECONCILIATION")
        reason.add("CANONICAL_EXECUTABLE_PACKAGE_RECEIPT_NOT_INDEPENDENTLY_VERIFIED")
        return CandidateReadiness(
            candidate_id=candidate_id,readiness="NOT_READY",
            blockers=tuple(sorted(reason)),
            quote_freshness_label=c["quote_freshness_class"],
            latest_state=latest["to_state"] if latest else None,
            independent_leg_stress_marks=stress,
            independently_validated_package_marks=labelled,
            existing_outcome_observations=int(counts["n"]),
            predeclared_risk_plan_count=risk,
        )
    finally:
        db.close()


def inspect_recent(*, db_path, limit: int=8) -> list[CandidateReadiness]:
    if type(limit) is not int or not 1<=limit<=MAX_BATCH:
        raise ValueError("OUTCOME_AUDIT_BATCH_OUT_OF_BOUNDS")
    db=_open_ro(db_path)
    try:
        ids=[int(r[0]) for r in db.execute(
            "SELECT id FROM shadow_candidates ORDER BY id DESC LIMIT ?",(limit,))]
    finally:
        db.close()
    return [inspect_candidate(i,db_path=db_path) for i in ids]

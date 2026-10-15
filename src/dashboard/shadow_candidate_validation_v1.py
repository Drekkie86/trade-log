"""Bounded, read-only canonical Shadow Lab candidate evidence gate.

Never infer entry fills from quote/mark tables. This is a diagnostic funnel:
database evidence, not authorization to place orders or report positive EV.
"""
from __future__ import annotations

import sqlite3
from typing import Any

SAMPLE_LIMIT = 40

_SQL = """
WITH recent AS (
  SELECT id, underlying, surfaced_at, structure_id, quote_freshness_class,
         greek_quality_class, entry_quote_observation_id
  FROM shadow_candidates
  ORDER BY id DESC LIMIT ?
)
SELECT
  sc.id AS candidate_id,
  sc.underlying,
  sc.surfaced_at,
  sc.structure_id,
  sc.quote_freshness_class AS recorded_quote_class,
  sc.greek_quality_class AS recorded_greek_class,
  sc.entry_quote_observation_id,
  (
    SELECT d.decision_source
    FROM v_shadow_admission_decisions_all AS d
    WHERE d.candidate_id=sc.id AND d.decision='ADMITTED'
    ORDER BY d.decided_at DESC, d.decision_id DESC LIMIT 1
  ) AS admission_policy,
  CASE
    WHEN pir.candidate_id IS NOT NULL
     AND pir.prospectivity_state='DB_RECORDED_PROSPECTIVE'
      THEN 'DB_RECORDED_PROSPECTIVE'
    WHEN lr.candidate_id IS NOT NULL
     AND lr.prospectivity_state='DB_RECORDED_PROSPECTIVE'
      THEN 'DB_RECORDED_PROSPECTIVE'
    ELSE 'NOT_RECORDED'
  END AS risk_plan_recording,
  (
    SELECT COUNT(*)
    FROM shadow_mark_observations AS sm
    WHERE sm.candidate_id=sc.id
  ) AS mark_count,
  (
    SELECT COUNT(*)
    FROM shadow_mark_observations AS sm
    WHERE sm.candidate_id=sc.id
      AND sm.outcome_eligible=1
  ) AS eligible_marks,
  (
    SELECT COUNT(*)
    FROM shadow_outcome_observations AS so
    WHERE so.candidate_id=sc.id
  ) AS recorded_outcome_observations
FROM recent AS sc
LEFT JOIN shadow_intrinsic_risk_plan_recordings_v1 AS pir
  ON pir.candidate_id=sc.id
LEFT JOIN shadow_risk_plan_recordings AS lr
  ON lr.candidate_id=sc.id
ORDER BY sc.id DESC;
"""


def _source_clock_state(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """SELECT live_probe_state, confidence_state, decision_enabled
           FROM thetadata_timestamp_semantics_v1_runs
           ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    if (
        row is not None
        and row["live_probe_state"] == "PASSED"
        and row["confidence_state"] == "DOCUMENTED_AND_LIVE_VALIDATED"
        and int(row["decision_enabled"] or 0) == 1
    ):
        return "GLOBAL_LIVE_SEMANTICS_PASSED"
    return "GLOBAL_LIVE_SEMANTICS_NOT_VERIFIED"


def _classify(row: dict[str, Any], clock: str) -> dict[str, Any]:
    missing = []
    if row["admission_policy"] is None:
        missing.append("ADMISSION_PROVENANCE_MISSING")
    if row["entry_quote_observation_id"] is None:
        missing.append("ENTRY_QUOTE_REFERENCE_MISSING")
    if row["recorded_quote_class"] != "FRESH":
        missing.append("LEGACY_QUOTE_CLASS_NOT_FRESH")
    if clock != "GLOBAL_LIVE_SEMANTICS_PASSED":
        missing.append("PROVIDER_CLOCK_LIVE_PROBE_NOT_VERIFIED")
    # A candidate-level, per-leg source/contract/timestamp receipt is not
    # stored by the current canonical admission records. Neither a historical
    # FRESH label nor a global Theta probe is sufficient evidence.
    missing.append("ENTRY_LEG_ASOF_RECEIPTS_NOT_VERIFIED")
    if row["risk_plan_recording"] != "DB_RECORDED_PROSPECTIVE":
        missing.append("PROSPECTIVE_RISK_PLAN_NOT_RECORDED")
    if row["eligible_marks"] == 0:
        missing.append("NO_EVIDENCE_ELIGIBLE_OUTCOME_MARK")
    # Source-mark eligibility is NOT broker complex-package executability.
    # Canonical independent entry+exit package receipts are not yet present.
    missing.append("INDEPENDENT_ENTRY_EXIT_PACKAGE_RECEIPTS_MISSING")

    return {
        "candidate_id": int(row["candidate_id"]),
        "underlying": row["underlying"],
        "surfaced_at": row["surfaced_at"],
        "structure_id": row["structure_id"],
        "admission_policy": row["admission_policy"] or "NOT_RECORDED",
        "recorded_quote_class": row["recorded_quote_class"] or "UNKNOWN",
        "recorded_greek_class": row["recorded_greek_class"] or "UNKNOWN",
        "clock_evidence": clock,
        "risk_plan_recording": row["risk_plan_recording"],
        "mark_count": int(row["mark_count"]),
        "eligible_marks": int(row["eligible_marks"]),
        "recorded_outcome_observations": int(row["recorded_outcome_observations"]),
        "economic_scoring_state": "NOT_ELIGIBLE",
        "missing_evidence": " | ".join(missing),
    }


def read_shadow_candidate_validation(
    conn: sqlite3.Connection, *, limit: int = SAMPLE_LIMIT
) -> dict[str, Any]:
    """No writes; bounded newest-candidate sample and separate cohort totals."""
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("CANDIDATE_AUDIT_LIMIT_OUT_OF_BOUNDS")
    clock = _source_clock_state(conn)
    rows = [_classify(dict(r), clock) for r in conn.execute(_SQL, (limit,))]
    legacy = int(conn.execute("SELECT COUNT(*) FROM shadow_admission_decisions").fetchone()[0])
    intrinsic = int(conn.execute(
        "SELECT COUNT(*) FROM shadow_intrinsic_admission_decisions_v1"
    ).fetchone()[0])
    counts = {
        "recent_sample_size": len(rows),
        "sample_predeclared_risk_plans": sum(
            r["risk_plan_recording"] == "DB_RECORDED_PROSPECTIVE" for r in rows
        ),
        "sample_with_marks": sum(r["mark_count"] > 0 for r in rows),
        "sample_economically_eligible": 0,
        "historical_legacy_admission_decisions": legacy,
        "new_intrinsic_admission_decisions": intrinsic,
    }
    return {
        "clock_evidence": clock,
        "counts": counts,
        "recent_candidates": rows,
        "scope": f"NEWEST_{limit}_CANDIDATES_ONLY_NOT_FULL_POPULATION",
        "economic_eligibility_basis": "FAIL_CLOSED_INDEPENDENT_PACKAGE_RECEIPTS_ABSENT",
    }

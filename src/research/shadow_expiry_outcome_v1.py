"""Prospective expiry-intrinsic outcomes for admitted shadow candidates.

Closes the gap that made shadow suggestions unmeasurable: candidates were
closed at expiration but nothing ever recorded what the structure was worth
at expiry. A defined-risk structure's expiry payoff is a deterministic function
of the terminal underlying price, so it needs no leg-by-leg quote crossing and
is free of the liquidity-stress contamination of the intraday marks.

Contract (see migration 035):
  * exactly one row per candidate, written once the expiry session has passed
    relative to the current research session (same rule the lifecycle uses to
    close candidates);
  * terminal price = last stored underlying observation from the expiry
    session; the basis is persisted and is NOT called a settlement price;
  * measurement_role is PROSPECTIVE_EXPIRY_INTRINSIC_V1 — distinct from the
    frozen VALIDATED_PACKAGE_OUTCOME scoring contract, which is unchanged;
  * UNRESOLVED is recorded explicitly when no expiry-session snapshot exists.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from src.database.repository import get_connection
from src.research.historical_replay_recovery_v1 import (
    _expiry_snapshot,
    theoretical_expiry_value_usd_minor,
)
from src.research.shadow_outcome_collector_v2 import _entry_cashflow_usd_minor

MEASUREMENT_ROLE = "PROSPECTIVE_EXPIRY_INTRINSIC_V1"
SETTLEMENT_BASIS = "LAST_STORED_EXPIRY_SESSION_UNDERLYING_SNAPSHOT"


class ShadowExpiryOutcomeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ShadowExpiryOutcomeResult:
    research_run_id: int
    session_date: str
    candidates_due: int
    resolved_written: int
    unresolved_written: int


def _due_candidates(*, session_day: date, db_path=None) -> list[dict[str, Any]]:
    """Admitted candidates whose expiration session has passed and that have
    no expiry-outcome row yet. Lifecycle state is deliberately not a filter:
    a candidate stuck in SHADOW_TRACKED past expiry (the WARN the dashboard
    already shows) must still receive its outcome."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                sc.id            AS candidate_id,
                sc.underlying,
                sc.structure_json,
                lrc.expiration,
                sad.proposal_id,
                sad.fx_observation_id,
                sad.estimated_cost_usd_minor,
                -- USD, from the admission decision. shadow_candidates.
                -- max_theoretical_loss_minor is EUR (converted at admission)
                -- and must not be labelled or ratioed as USD.
                sad.proposal_max_loss_usd_minor,
                ssp.entry_pricing_json,
                fx.rate          AS entry_eur_to_usd
            FROM shadow_candidates AS sc
            JOIN listing_reference_contracts AS lrc
              ON lrc.id = sc.reference_contract_id
            JOIN v_shadow_admission_decisions_all AS sad
              ON sad.candidate_id = sc.id
             AND sad.decision = 'ADMITTED'
            JOIN shadow_structure_proposals AS ssp
              ON ssp.id = sad.proposal_id
            JOIN fx_observations AS fx
              ON fx.id = sad.fx_observation_id
            WHERE lrc.expiration < ?
              AND NOT EXISTS (
                    SELECT 1 FROM shadow_expiry_outcomes_v1 AS o
                    WHERE o.candidate_id = sc.id
              )
            ORDER BY sc.id;
            """,
            (session_day.isoformat(),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _insert(conn, **cols) -> int:
    names = ", ".join(cols)
    marks = ", ".join("?" * len(cols))
    return int(
        conn.execute(
            f"INSERT INTO shadow_expiry_outcomes_v1 ({names}) VALUES ({marks});",
            tuple(cols.values()),
        ).lastrowid
    )


def record_shadow_expiry_outcomes(
    *, research_run_id: int, db_path=None
) -> ShadowExpiryOutcomeResult:
    conn = get_connection(db_path)
    try:
        run = conn.execute(
            """
            SELECT id, us_session_date, COALESCE(ended_at, started_at) AS recorded_at
            FROM research_runs WHERE id = ?;
            """,
            (research_run_id,),
        ).fetchone()
    finally:
        conn.close()
    if run is None:
        raise ShadowExpiryOutcomeError(f"Unknown research run {research_run_id}.")
    if not run["us_session_date"] or not run["recorded_at"]:
        raise ShadowExpiryOutcomeError(
            f"Research run {research_run_id} lacks session date or timestamp."
        )
    session_day = date.fromisoformat(str(run["us_session_date"]))
    recorded_at = str(run["recorded_at"])

    due = _due_candidates(session_day=session_day, db_path=db_path)
    resolved = 0
    unresolved = 0

    for cand in due:
        candidate_id = int(cand["candidate_id"])
        expiration = str(cand["expiration"])
        evidence: dict[str, Any] = {
            "research_run_id": research_run_id,
            "session_date": session_day.isoformat(),
            "settlement_basis": SETTLEMENT_BASIS,
            "settlement_note": (
                "Terminal price is the last daemon-sampled underlying price of "
                "the expiry session, not the official settlement value."
            ),
        }
        common = dict(
            candidate_id=candidate_id,
            research_run_id=research_run_id,
            recorded_at=recorded_at,
            expiration=expiration,
            settlement_basis=SETTLEMENT_BASIS,
            measurement_role=MEASUREMENT_ROLE,
            max_theoretical_loss_usd_minor=int(cand["proposal_max_loss_usd_minor"]),
            entry_fx_observation_id=int(cand["fx_observation_id"]),
            entry_eur_to_usd=float(cand["entry_eur_to_usd"]),
            estimated_cost_usd_minor=int(cand["estimated_cost_usd_minor"]),
        )

        snapshot = _expiry_snapshot(
            underlying=str(cand["underlying"]), expiration=expiration, db_path=db_path
        )
        conn = get_connection(db_path)
        try:
            if snapshot is None:
                evidence["reason"] = "MISSING_EXPIRY_SESSION_UNDERLYING_SNAPSHOT"
                _insert(
                    conn,
                    **common,
                    outcome_state="UNRESOLVED",
                    reason_code="MISSING_EXPIRY_SESSION_UNDERLYING_SNAPSHOT",
                    evidence_json=json.dumps(evidence, sort_keys=True),
                )
                conn.commit()
                unresolved += 1
                continue

            try:
                structure = json.loads(str(cand["structure_json"]))
                entry_pricing = json.loads(str(cand["entry_pricing_json"]))
                entry_cashflow = _entry_cashflow_usd_minor(
                    structure=structure, entry_pricing=entry_pricing
                )
                terminal_value = theoretical_expiry_value_usd_minor(
                    structure=structure,
                    underlying_price=float(snapshot["underlying_price"]),
                )
            except Exception as exc:  # recorded, never swallowed
                evidence["reason"] = "ENTRY_OR_STRUCTURE_RECONSTRUCTION_UNAVAILABLE"
                evidence["error"] = f"{type(exc).__name__}: {exc}"
                _insert(
                    conn,
                    **common,
                    outcome_state="UNRESOLVED",
                    reason_code="ENTRY_OR_STRUCTURE_RECONSTRUCTION_UNAVAILABLE",
                    evidence_json=json.dumps(evidence, sort_keys=True),
                )
                conn.commit()
                unresolved += 1
                continue

            cost = int(cand["estimated_cost_usd_minor"])
            gross_usd = entry_cashflow + terminal_value
            net_usd = gross_usd - cost
            rate = float(cand["entry_eur_to_usd"])
            evidence["snapshot"] = {
                "snapshot_id": int(snapshot["id"]),
                "provider": str(snapshot["provider"]),
                "captured_at": str(snapshot["captured_at"]),
                "underlying_price": float(snapshot["underlying_price"]),
            }
            evidence["pricing"] = {
                "entry_cashflow_usd_minor": entry_cashflow,
                "terminal_structure_value_usd_minor": terminal_value,
                "estimated_round_trip_cost_usd_minor": cost,
                "entry_eur_to_usd": rate,
            }
            _insert(
                conn,
                **common,
                outcome_state="RESOLVED",
                reason_code="EXPIRY_SESSION_STORED_UNDERLYING_AVAILABLE",
                snapshot_id=int(snapshot["id"]),
                snapshot_captured_at=str(snapshot["captured_at"]),
                snapshot_provider=str(snapshot["provider"]),
                terminal_underlying_price=float(snapshot["underlying_price"]),
                entry_cashflow_usd_minor=entry_cashflow,
                terminal_structure_value_usd_minor=terminal_value,
                gross_pnl_usd_minor=gross_usd,
                estimated_net_pnl_usd_minor=net_usd,
                gross_pnl_eur_minor=int(round(gross_usd / rate)),
                estimated_net_pnl_eur_minor=int(round(net_usd / rate)),
                evidence_json=json.dumps(evidence, sort_keys=True),
            )
            conn.commit()
            resolved += 1
        finally:
            conn.close()

    return ShadowExpiryOutcomeResult(
        research_run_id=research_run_id,
        session_date=session_day.isoformat(),
        candidates_due=len(due),
        resolved_written=resolved,
        unresolved_written=unresolved,
    )

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.database.repository import get_connection


@dataclass(frozen=True)
class ShadowMarkResult:
    candidate_id: int
    research_run_id: int
    quality_state: str
    persisted_mark_id: int
    structure_mark_usd_minor: int | None
    gross_pnl_usd_minor: int | None
    estimated_net_pnl_usd_minor: int | None
    gross_pnl_eur_minor: int | None
    estimated_net_pnl_eur_minor: int | None


@dataclass(frozen=True)
class ShadowOutcomeCollectionResult:
    research_run_id: int
    active_candidate_count: int
    marks_written: int
    complete_marks: int
    incomplete_marks: int
    marks: tuple[ShadowMarkResult, ...]


class ShadowOutcomeCollectorError(RuntimeError):
    pass


def _active_candidates(*, db_path=None) -> list[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            WITH latest_state AS (
                SELECT
                    candidate_id,
                    to_state,
                    ROW_NUMBER() OVER (
                        PARTITION BY candidate_id
                        ORDER BY id DESC
                    ) AS rn
                FROM shadow_state_events
            )
            SELECT
                sc.*,
                lrc.expiration,
                sad.fx_observation_id,
                sad.estimated_cost_usd_minor,
                sad.estimated_cost_eur_minor,
                sad.decision_source AS admission_decision_source,
                fx.rate AS entry_eur_to_usd
            FROM shadow_candidates AS sc
            JOIN latest_state AS ls
              ON ls.candidate_id = sc.id
             AND ls.rn = 1
            JOIN listing_reference_contracts AS lrc
              ON lrc.id = sc.reference_contract_id
            JOIN v_shadow_admission_decisions_all AS sad
              ON sad.candidate_id = sc.id
             AND sad.decision = 'ADMITTED'
            JOIN fx_observations AS fx
              ON fx.id = sad.fx_observation_id
            WHERE ls.to_state = 'SHADOW_TRACKED'
            ORDER BY sc.id;
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _research_run(research_run_id: int, *, db_path=None) -> dict[str, Any]:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM research_runs WHERE id = ?;",
            (research_run_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ShadowOutcomeCollectorError(
            f"Research run {research_run_id} does not exist."
        )
    return dict(row)


def _latest_snapshot(
    *, research_run_id: int, underlying: str, db_path=None
) -> dict[str, Any] | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT *
            FROM market_snapshots
            WHERE research_run_id = ?
              AND underlying = ?
              AND provider = 'THETADATA'
            ORDER BY id DESC
            LIMIT 1;
            """,
            (research_run_id, underlying),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else dict(row)


def _quote_for_leg(
    *, snapshot_id: int, expiration: str, right: str, strike: float, db_path=None
) -> dict[str, Any] | None:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM option_quotes
            WHERE snapshot_id = ?
              AND expiration = ?
              AND right = ?
              AND strike = ?;
            """,
            (snapshot_id, expiration, right, strike),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return None
    if len(rows) != 1:
        raise ShadowOutcomeCollectorError(
            f"Ambiguous option quote for shadow leg: {expiration} {right} {strike}."
        )
    return dict(rows[0])


def _entry_pricing(candidate_id: int, *, db_path=None) -> str | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT ssp.entry_pricing_json
            FROM v_shadow_admission_decisions_all AS sad
            JOIN shadow_structure_proposals AS ssp
              ON ssp.id = sad.proposal_id
            WHERE sad.candidate_id = ?
              AND sad.decision = 'ADMITTED'
            LIMIT 1;
            """,
            (candidate_id,),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else row["entry_pricing_json"]


def _entry_cashflow_usd_minor(
    *, structure: dict[str, Any], entry_pricing: dict[str, Any]
) -> int:
    pricing_by_quote = {
        int(item["option_quote_id"]): item
        for item in entry_pricing.get("legs", [])
    }
    cashflow_usd = 0.0
    for leg in structure.get("legs", []):
        quote_id = int(leg["option_quote_id"])
        pricing = pricing_by_quote.get(quote_id)
        if pricing is None:
            raise ShadowOutcomeCollectorError(
                "Entry pricing is missing a structure leg."
            )
        quantity = int(leg["quantity"])
        multiplier = float(leg["shares_per_contract"])
        side = str(leg["side"])
        entry_price = float(pricing["entry_price"])
        signed = -1.0 if side == "BUY" else 1.0
        cashflow_usd += signed * quantity * multiplier * entry_price
    return int(round(cashflow_usd * 100))


def _persist_mark(
    *,
    candidate_id: int,
    research_run_id: int,
    observed_at: str,
    quality_state: str,
    entry_fx_observation_id: int,
    structure_mark_usd_minor: int | None,
    gross_pnl_usd_minor: int | None,
    estimated_net_pnl_usd_minor: int | None,
    gross_pnl_eur_minor: int | None,
    estimated_net_pnl_eur_minor: int | None,
    evidence_json: str,
    db_path=None,
) -> int:
    conn = get_connection(db_path)
    try:
        existing = conn.execute(
            """
            SELECT id
            FROM shadow_mark_observations
            WHERE candidate_id = ?
              AND research_run_id = ?;
            """,
            (candidate_id, research_run_id),
        ).fetchone()
        if existing is not None:
            return int(existing["id"])

        with conn:
            cursor = conn.execute(
                """
                INSERT INTO shadow_mark_observations (
                    candidate_id, research_run_id, observed_at, provider,
                    structure_mark_usd_minor, gross_pnl_usd_minor,
                    estimated_net_pnl_usd_minor, gross_pnl_eur_minor,
                    estimated_net_pnl_eur_minor, entry_fx_observation_id,
                    quality_state, evidence_json
                ) VALUES (?, ?, ?, 'THETADATA', ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    candidate_id,
                    research_run_id,
                    observed_at,
                    structure_mark_usd_minor,
                    gross_pnl_usd_minor,
                    estimated_net_pnl_usd_minor,
                    gross_pnl_eur_minor,
                    estimated_net_pnl_eur_minor,
                    entry_fx_observation_id,
                    quality_state,
                    evidence_json,
                ),
            )
        return int(cursor.lastrowid)
    finally:
        conn.close()


def _result(
    *,
    candidate_id: int,
    research_run_id: int,
    quality_state: str,
    mark_id: int,
    structure_mark_usd_minor: int | None = None,
    gross_pnl_usd_minor: int | None = None,
    estimated_net_pnl_usd_minor: int | None = None,
    gross_pnl_eur_minor: int | None = None,
    estimated_net_pnl_eur_minor: int | None = None,
) -> ShadowMarkResult:
    return ShadowMarkResult(
        candidate_id=candidate_id,
        research_run_id=research_run_id,
        quality_state=quality_state,
        persisted_mark_id=mark_id,
        structure_mark_usd_minor=structure_mark_usd_minor,
        gross_pnl_usd_minor=gross_pnl_usd_minor,
        estimated_net_pnl_usd_minor=estimated_net_pnl_usd_minor,
        gross_pnl_eur_minor=gross_pnl_eur_minor,
        estimated_net_pnl_eur_minor=estimated_net_pnl_eur_minor,
    )


def _persist_incomplete(
    *,
    candidate: dict[str, Any],
    research_run_id: int,
    observed_at: str,
    evidence: dict[str, Any],
    db_path=None,
) -> ShadowMarkResult:
    mark_id = _persist_mark(
        candidate_id=int(candidate["id"]),
        research_run_id=research_run_id,
        observed_at=observed_at,
        quality_state="INCOMPLETE_LEG_MARK",
        entry_fx_observation_id=int(candidate["fx_observation_id"]),
        structure_mark_usd_minor=None,
        gross_pnl_usd_minor=None,
        estimated_net_pnl_usd_minor=None,
        gross_pnl_eur_minor=None,
        estimated_net_pnl_eur_minor=None,
        evidence_json=json.dumps(evidence, sort_keys=True),
        db_path=db_path,
    )
    return _result(
        candidate_id=int(candidate["id"]),
        research_run_id=research_run_id,
        quality_state="INCOMPLETE_LEG_MARK",
        mark_id=mark_id,
    )


def collect_shadow_marks(
    *, research_run_id: int, db_path=None
) -> ShadowOutcomeCollectionResult:
    run = _research_run(research_run_id, db_path=db_path)
    observed_at = run.get("ended_at") or run.get("started_at")
    if not observed_at:
        raise ShadowOutcomeCollectorError(
            "Research run has no usable observation timestamp."
        )

    candidates = _active_candidates(db_path=db_path)
    results: list[ShadowMarkResult] = []

    for candidate in candidates:
        candidate_id = int(candidate["id"])
        snapshot = _latest_snapshot(
            research_run_id=research_run_id,
            underlying=str(candidate["underlying"]),
            db_path=db_path,
        )
        try:
            structure = json.loads(str(candidate["structure_json"]))
        except (json.JSONDecodeError, TypeError):
            structure = {"legs": []}

        entry_pricing_raw = _entry_pricing(candidate_id, db_path=db_path)
        if snapshot is None or entry_pricing_raw is None:
            results.append(
                _persist_incomplete(
                    candidate=candidate,
                    research_run_id=research_run_id,
                    observed_at=str(observed_at),
                    evidence={
                        "reason": (
                            "NO_THETADATA_SNAPSHOT"
                            if snapshot is None
                            else "ENTRY_PRICING_NOT_FOUND"
                        ),
                        "research_run_id": research_run_id,
                        "admission_decision_source": candidate.get(
                            "admission_decision_source"
                        ),
                    },
                    db_path=db_path,
                )
            )
            continue

        try:
            entry_pricing = json.loads(str(entry_pricing_raw))
            entry_cashflow_usd_minor = _entry_cashflow_usd_minor(
                structure=structure,
                entry_pricing=entry_pricing,
            )

            leg_evidence: list[dict[str, Any]] = []
            liquidation_cashflow_usd = 0.0
            complete = True

            for leg in structure.get("legs", []):
                quote = _quote_for_leg(
                    snapshot_id=int(snapshot["id"]),
                    expiration=str(candidate["expiration"]),
                    right=str(leg["right"]),
                    strike=float(leg["strike"]),
                    db_path=db_path,
                )
                if quote is None:
                    complete = False
                    leg_evidence.append(
                        {
                            "strike": leg["strike"],
                            "right": leg["right"],
                            "side": leg["side"],
                            "quantity": leg["quantity"],
                            "state": "QUOTE_MISSING",
                        }
                    )
                    continue

                bid = quote["bid"]
                ask = quote["ask"]
                if (
                    bid is None
                    or ask is None
                    or float(bid) < 0
                    or float(ask) < float(bid)
                ):
                    complete = False
                    leg_evidence.append(
                        {
                            "strike": leg["strike"],
                            "right": leg["right"],
                            "side": leg["side"],
                            "quantity": leg["quantity"],
                            "state": "QUOTE_INVALID",
                            "bid": bid,
                            "ask": ask,
                            "quote_at": quote["quote_at"],
                        }
                    )
                    continue

                side = str(leg["side"])
                quantity = int(leg["quantity"])
                multiplier = float(leg["shares_per_contract"])
                liquidation_price = float(bid) if side == "BUY" else float(ask)
                signed = 1.0 if side == "BUY" else -1.0
                liquidation_cashflow_usd += (
                    signed * quantity * multiplier * liquidation_price
                )
                leg_evidence.append(
                    {
                        "strike": leg["strike"],
                        "right": leg["right"],
                        "side": side,
                        "quantity": quantity,
                        "bid": float(bid),
                        "ask": float(ask),
                        "liquidation_price": liquidation_price,
                        "quote_at": quote["quote_at"],
                        "state": "COMPLETE",
                    }
                )

            if not complete:
                results.append(
                    _persist_incomplete(
                        candidate=candidate,
                        research_run_id=research_run_id,
                        observed_at=str(observed_at),
                        evidence={
                            "research_run_id": research_run_id,
                            "snapshot_id": snapshot["id"],
                            "leg_evidence": leg_evidence,
                            "freshness": "NOT_RECLASSIFIED_HERE",
                            "admission_decision_source": candidate.get(
                                "admission_decision_source"
                            ),
                        },
                        db_path=db_path,
                    )
                )
                continue

            structure_mark_usd_minor = int(
                round(liquidation_cashflow_usd * 100)
            )
            gross_pnl_usd_minor = (
                entry_cashflow_usd_minor + structure_mark_usd_minor
            )
            estimated_net_pnl_usd_minor = (
                gross_pnl_usd_minor
                - int(candidate["estimated_cost_usd_minor"])
            )
            entry_eur_to_usd = float(candidate["entry_eur_to_usd"])
            gross_pnl_eur_minor = int(
                round(gross_pnl_usd_minor / entry_eur_to_usd)
            )
            estimated_net_pnl_eur_minor = int(
                round(estimated_net_pnl_usd_minor / entry_eur_to_usd)
            )

            evidence = {
                "research_run_id": research_run_id,
                "snapshot_id": snapshot["id"],
                "pricing_basis": "CONSERVATIVE_LIQUIDATION_LONG_BID_SHORT_ASK",
                "entry_cashflow_usd_minor": entry_cashflow_usd_minor,
                "entry_fx": {
                    "fx_observation_id": candidate["fx_observation_id"],
                    "eur_to_usd": entry_eur_to_usd,
                },
                "leg_evidence": leg_evidence,
                "freshness": (
                    "RAW_QUOTE_TIMESTAMPS_PRESERVED_BUT_NOT_RECLASSIFIED_BY_COLLECTOR"
                ),
                "admission_decision_source": candidate.get(
                    "admission_decision_source"
                ),
            }
            mark_id = _persist_mark(
                candidate_id=candidate_id,
                research_run_id=research_run_id,
                observed_at=str(observed_at),
                quality_state="COMPLETE_UNVERIFIED_FRESHNESS",
                entry_fx_observation_id=int(candidate["fx_observation_id"]),
                structure_mark_usd_minor=structure_mark_usd_minor,
                gross_pnl_usd_minor=gross_pnl_usd_minor,
                estimated_net_pnl_usd_minor=estimated_net_pnl_usd_minor,
                gross_pnl_eur_minor=gross_pnl_eur_minor,
                estimated_net_pnl_eur_minor=estimated_net_pnl_eur_minor,
                evidence_json=json.dumps(evidence, sort_keys=True),
                db_path=db_path,
            )
            results.append(
                _result(
                    candidate_id=candidate_id,
                    research_run_id=research_run_id,
                    quality_state="COMPLETE_UNVERIFIED_FRESHNESS",
                    mark_id=mark_id,
                    structure_mark_usd_minor=structure_mark_usd_minor,
                    gross_pnl_usd_minor=gross_pnl_usd_minor,
                    estimated_net_pnl_usd_minor=estimated_net_pnl_usd_minor,
                    gross_pnl_eur_minor=gross_pnl_eur_minor,
                    estimated_net_pnl_eur_minor=estimated_net_pnl_eur_minor,
                )
            )

        except Exception as exc:
            evidence = {
                "research_run_id": research_run_id,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "admission_decision_source": candidate.get(
                    "admission_decision_source"
                ),
            }
            mark_id = _persist_mark(
                candidate_id=candidate_id,
                research_run_id=research_run_id,
                observed_at=str(observed_at),
                quality_state="INVALID_MARK",
                entry_fx_observation_id=int(candidate["fx_observation_id"]),
                structure_mark_usd_minor=None,
                gross_pnl_usd_minor=None,
                estimated_net_pnl_usd_minor=None,
                gross_pnl_eur_minor=None,
                estimated_net_pnl_eur_minor=None,
                evidence_json=json.dumps(evidence, sort_keys=True),
                db_path=db_path,
            )
            results.append(
                _result(
                    candidate_id=candidate_id,
                    research_run_id=research_run_id,
                    quality_state="INVALID_MARK",
                    mark_id=mark_id,
                )
            )

    complete_marks = sum(
        mark.quality_state == "COMPLETE_UNVERIFIED_FRESHNESS"
        for mark in results
    )
    return ShadowOutcomeCollectionResult(
        research_run_id=research_run_id,
        active_candidate_count=len(candidates),
        marks_written=len(results),
        complete_marks=complete_marks,
        incomplete_marks=len(results) - complete_marks,
        marks=tuple(results),
    )

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.database.repository import (
    append_shadow_state_event,
    append_underlying_pin_event,
    create_shadow_candidate,
    get_connection,
)
from src.providers.ecb_fx import EcbFxObservation
from src.research.shadow_lifecycle import classify_greek_quality

UTC = ZoneInfo("UTC")

RISK_POLICY_VERSION = "INTRINSIC_DEFINED_RISK_V1"
# Compatibility alias for the legacy shadow_candidates column name. This is a
# research-risk policy identifier, not an account-sizing policy.
SIZING_POLICY_VERSION = RISK_POLICY_VERSION

COST_MODEL_VERSION = "SAXO_BE_SHADOW_COST_CEILING_V1"
COST_PROVENANCE = "ASSUMED_PUBLIC_TARIFF_PLUS_CONTINGENCY"
USD_COST_PER_CONTRACT_SIDE_MINOR = 300

ADMISSION_LABEL = "CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING"


class ShadowAdmissionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ShadowAdmissionDecision:
    proposal_id: int
    decision: str
    reason_code: str
    candidate_id: int | None
    fx_observation_id: int
    proposal_max_loss_usd_minor: int
    estimated_cost_usd_minor: int
    intrinsic_risk_usd_minor: int
    converted_max_loss_eur_minor: int
    estimated_cost_eur_minor: int
    intrinsic_risk_eur_minor: int


@dataclass(frozen=True)
class ShadowAdmissionResult:
    proposal_count: int
    admitted_count: int
    blocked_count: int
    decisions: tuple[ShadowAdmissionDecision, ...]


def _now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _persist_fx(observation: EcbFxObservation, *, db_path=None) -> int:
    if observation.base_currency != "EUR" or observation.quote_currency != "USD":
        raise ShadowAdmissionError(
            "Shadow admission requires EUR/USD expressed as USD per EUR."
        )
    if observation.rate <= 0:
        raise ShadowAdmissionError("FX rate must be positive.")

    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO fx_observations (
                    provider, base_currency, quote_currency, rate,
                    reference_date, observed_at, source_url, provenance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    observation.provider,
                    observation.base_currency,
                    observation.quote_currency,
                    observation.rate,
                    observation.reference_date,
                    observation.observed_at,
                    observation.source_url,
                    observation.provenance,
                ),
            )
        return int(cursor.lastrowid)
    finally:
        conn.close()


def _load_proposals(
    *, proposal_ids: list[int] | None, db_path=None
) -> list[dict[str, Any]]:
    """Load proposed structures without retroactively reopening legacy decisions.

    Explicit IDs are used by the live research cycle and are safe because a
    proposal ID belongs to exactly one persisted research run. The unfiltered
    path excludes anything already decided under either the legacy bankroll
    policy or the intrinsic-risk policy; removing the wallet ceiling must not
    rewrite historical cohorts.
    """
    conn = get_connection(db_path)
    try:
        if proposal_ids:
            conn.execute(
                """
                CREATE TEMP TABLE IF NOT EXISTS requested_shadow_proposal_ids (
                    id INTEGER PRIMARY KEY
                );
                """
            )
            conn.execute("DELETE FROM requested_shadow_proposal_ids;")
            conn.executemany(
                "INSERT INTO requested_shadow_proposal_ids(id) VALUES (?);",
                ((int(proposal_id),) for proposal_id in proposal_ids),
            )
            selector_join = (
                "JOIN requested_shadow_proposal_ids AS requested "
                "ON requested.id = ssp.id"
            )
            undecided_clause = ""
        else:
            selector_join = ""
            undecided_clause = """
              AND NOT EXISTS (
                    SELECT 1
                    FROM shadow_admission_decisions AS legacy
                    WHERE legacy.proposal_id = ssp.id
              )
              AND NOT EXISTS (
                    SELECT 1
                    FROM shadow_intrinsic_admission_decisions_v1 AS intrinsic
                    WHERE intrinsic.proposal_id = ssp.id
                      AND intrinsic.risk_policy_version = ?
                      AND intrinsic.cost_model_version = ?
              )
            """

        sql = f"""
            SELECT
                ssp.*,
                hse.scanner_run_id,
                hse.option_quote_id AS target_option_quote_id,
                hsr.scanner_family_id,
                hsr.scanner_version,
                hsr.rule_version AS scanner_rule_version,
                hsr.hypothesis_family,
                hsr.hypothesis_version,
                hsr.evaluated_at AS surfaced_at,
                pmo.model_input_notes
            FROM shadow_structure_proposals AS ssp
            {selector_join}
            JOIN hypothesis_scanner_evaluations AS hse
              ON hse.id = ssp.hypothesis_evaluation_id
            JOIN hypothesis_scanner_runs AS hsr
              ON hsr.id = hse.scanner_run_id
            JOIN provider_model_observations AS pmo
              ON pmo.option_quote_id = hse.option_quote_id
             AND pmo.provider = 'THETADATA'
            WHERE ssp.proposal_state = 'PROPOSED'
            {undecided_clause}
            ORDER BY ssp.id;
        """
        params: tuple[Any, ...] = (
            ()
            if proposal_ids
            else (RISK_POLICY_VERSION, COST_MODEL_VERSION)
        )
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _structure_contract_sides(structure_json: str) -> int:
    try:
        legs = json.loads(structure_json)["legs"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ShadowAdmissionError("Proposal structure_json is invalid.") from exc

    total = 0
    for leg in legs:
        quantity = int(leg["quantity"])
        if quantity <= 0:
            raise ShadowAdmissionError("Structure leg quantity must be positive.")
        total += quantity
    if total <= 0:
        raise ShadowAdmissionError("Structure must contain contract sides.")
    return total


def _to_eur_minor(usd_minor: int, *, eur_to_usd: float) -> int:
    return int(round(usd_minor / eur_to_usd))


def _iv_error(model_input_notes: str | None) -> float | None:
    if not model_input_notes:
        return None
    try:
        value = json.loads(model_input_notes).get("iv_error")
        return None if value is None else float(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _availability(
    *, reference_contract_id: int, evidence_family: str, db_path=None
) -> dict[str, Any] | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT *
            FROM provider_observation_availability
            WHERE reference_contract_id = ?
              AND provider = 'THETADATA'
              AND evidence_family = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (reference_contract_id, evidence_family),
        ).fetchone()
        return None if row is None else dict(row)
    finally:
        conn.close()


def _universe_status(*, reference_contract_id: int, db_path=None) -> str:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT state
            FROM provider_observation_availability
            WHERE reference_contract_id = ?
              AND provider = 'MASSIVE'
              AND evidence_family = 'MASSIVE_SNAPSHOT'
            ORDER BY id DESC
            LIMIT 1;
            """,
            (reference_contract_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return "UNUSABLE"
    if row["state"] == "PRESENT":
        return "CONSISTENT"
    return "DISAGREEMENT_RECORDED"


def _existing_decision(*, proposal_id: int, db_path=None) -> ShadowAdmissionDecision | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT *
            FROM shadow_intrinsic_admission_decisions_v1
            WHERE proposal_id = ?
              AND risk_policy_version = ?
              AND cost_model_version = ?;
            """,
            (proposal_id, RISK_POLICY_VERSION, COST_MODEL_VERSION),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return ShadowAdmissionDecision(
        proposal_id=int(row["proposal_id"]),
        decision=str(row["decision"]),
        reason_code=str(row["reason_code"]),
        candidate_id=(None if row["candidate_id"] is None else int(row["candidate_id"])),
        fx_observation_id=int(row["fx_observation_id"]),
        proposal_max_loss_usd_minor=int(row["proposal_max_loss_usd_minor"]),
        estimated_cost_usd_minor=int(row["estimated_cost_usd_minor"]),
        intrinsic_risk_usd_minor=int(row["intrinsic_risk_usd_minor"]),
        converted_max_loss_eur_minor=int(row["converted_max_loss_eur_minor"]),
        estimated_cost_eur_minor=int(row["estimated_cost_eur_minor"]),
        intrinsic_risk_eur_minor=int(row["intrinsic_risk_eur_minor"]),
    )


def _persist_decision(
    *,
    proposal: dict[str, Any],
    fx_observation_id: int,
    candidate_id: int | None,
    decision: str,
    reason_code: str,
    proposal_max_loss_usd_minor: int,
    estimated_cost_usd_minor: int,
    intrinsic_risk_usd_minor: int,
    converted_max_loss_eur_minor: int,
    estimated_cost_eur_minor: int,
    intrinsic_risk_eur_minor: int,
    fx: EcbFxObservation,
    db_path=None,
) -> int:
    evidence = json.dumps(
        {
            "admission_label": ADMISSION_LABEL,
            "fx": asdict(fx),
            "cost_model": {
                "usd_per_contract_side_minor": USD_COST_PER_CONTRACT_SIDE_MINOR,
                "round_trip": True,
                "provenance": COST_PROVENANCE,
            },
            "intrinsic_risk": {
                "policy_version": RISK_POLICY_VERSION,
                "proposal_max_loss_usd_minor": proposal_max_loss_usd_minor,
                "estimated_round_trip_cost_usd_minor": estimated_cost_usd_minor,
                "intrinsic_risk_usd_minor": intrinsic_risk_usd_minor,
                "converted_max_loss_eur_minor": converted_max_loss_eur_minor,
                "estimated_round_trip_cost_eur_minor": estimated_cost_eur_minor,
                "intrinsic_risk_eur_minor": intrinsic_risk_eur_minor,
                "account_balance_dependency": False,
                "account_capacity_gate": False,
                "probability_model": None,
                "expected_value": None,
                "probability_note": (
                    "No validated probability distribution is used by shadow "
                    "admission. Probability-weighted EV belongs here only after "
                    "a prospectively validated model exists."
                ),
            },
            "research_only": True,
            "broker_order_created": False,
        },
        sort_keys=True,
    )

    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO shadow_intrinsic_admission_decisions_v1 (
                    proposal_id, fx_observation_id, candidate_id,
                    risk_policy_version, cost_model_version, cost_provenance,
                    proposal_max_loss_usd_minor, estimated_cost_usd_minor,
                    intrinsic_risk_usd_minor, converted_max_loss_eur_minor,
                    estimated_cost_eur_minor, intrinsic_risk_eur_minor,
                    decision, reason_code, decided_at, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    int(proposal["id"]),
                    fx_observation_id,
                    candidate_id,
                    RISK_POLICY_VERSION,
                    COST_MODEL_VERSION,
                    COST_PROVENANCE,
                    proposal_max_loss_usd_minor,
                    estimated_cost_usd_minor,
                    intrinsic_risk_usd_minor,
                    converted_max_loss_eur_minor,
                    estimated_cost_eur_minor,
                    intrinsic_risk_eur_minor,
                    decision,
                    reason_code,
                    _now_utc(),
                    evidence,
                ),
            )
        return int(cursor.lastrowid)
    finally:
        conn.close()


def admit_shadow_proposals(
    *,
    fx: EcbFxObservation,
    proposal_ids: list[int] | None = None,
    db_path=None,
) -> ShadowAdmissionResult:
    proposals = _load_proposals(proposal_ids=proposal_ids, db_path=db_path)
    decisions: list[ShadowAdmissionDecision] = []
    if not proposals:
        return ShadowAdmissionResult(0, 0, 0, ())

    fx_observation_id = _persist_fx(fx, db_path=db_path)

    for proposal in proposals:
        existing = _existing_decision(proposal_id=int(proposal["id"]), db_path=db_path)
        if existing is not None:
            decisions.append(existing)
            continue

        max_loss_usd_minor = int(proposal["max_theoretical_loss_minor"])
        contract_sides = _structure_contract_sides(str(proposal["structure_json"]))
        estimated_cost_usd_minor = (
            contract_sides * 2 * USD_COST_PER_CONTRACT_SIDE_MINOR
        )
        intrinsic_risk_usd_minor = max_loss_usd_minor + estimated_cost_usd_minor
        converted_max_loss_eur_minor = _to_eur_minor(
            max_loss_usd_minor, eur_to_usd=fx.rate
        )
        estimated_cost_eur_minor = _to_eur_minor(
            estimated_cost_usd_minor, eur_to_usd=fx.rate
        )
        intrinsic_risk_eur_minor = _to_eur_minor(
            intrinsic_risk_usd_minor, eur_to_usd=fx.rate
        )

        reference_id = int(proposal["target_reference_contract_id"])
        universe_status = _universe_status(
            reference_contract_id=reference_id, db_path=db_path
        )
        quote_evidence = _availability(
            reference_contract_id=reference_id,
            evidence_family="THETADATA_QUOTE",
            db_path=db_path,
        )
        greek_evidence = _availability(
            reference_contract_id=reference_id,
            evidence_family="THETADATA_GREEKS",
            db_path=db_path,
        )

        block_reason = None
        if max_loss_usd_minor <= 0 or converted_max_loss_eur_minor <= 0:
            block_reason = "NON_POSITIVE_DEFINED_MAX_LOSS"
        elif universe_status == "UNUSABLE":
            block_reason = "UNIVERSE_EVIDENCE_UNUSABLE"
        elif quote_evidence is None:
            block_reason = "ENTRY_QUOTE_EVIDENCE_MISSING"
        elif quote_evidence["state"] != "PRESENT":
            block_reason = "ENTRY_QUOTE_NOT_PRESENT"
        elif greek_evidence is None:
            block_reason = "ENTRY_GREEK_EVIDENCE_MISSING"
        elif greek_evidence["state"] != "PRESENT":
            block_reason = "ENTRY_GREEK_NOT_PRESENT"

        if block_reason is not None:
            _persist_decision(
                proposal=proposal,
                fx_observation_id=fx_observation_id,
                candidate_id=None,
                decision="BLOCKED",
                reason_code=block_reason,
                proposal_max_loss_usd_minor=max_loss_usd_minor,
                estimated_cost_usd_minor=estimated_cost_usd_minor,
                intrinsic_risk_usd_minor=intrinsic_risk_usd_minor,
                converted_max_loss_eur_minor=converted_max_loss_eur_minor,
                estimated_cost_eur_minor=estimated_cost_eur_minor,
                intrinsic_risk_eur_minor=intrinsic_risk_eur_minor,
                fx=fx,
                db_path=db_path,
            )
            decisions.append(
                ShadowAdmissionDecision(
                    int(proposal["id"]),
                    "BLOCKED",
                    block_reason,
                    None,
                    fx_observation_id,
                    max_loss_usd_minor,
                    estimated_cost_usd_minor,
                    intrinsic_risk_usd_minor,
                    converted_max_loss_eur_minor,
                    estimated_cost_eur_minor,
                    intrinsic_risk_eur_minor,
                )
            )
            continue

        greek_quality = classify_greek_quality(
            _iv_error(proposal["model_input_notes"])
        ).value

        candidate = {
            "research_run_id": int(proposal["research_run_id"]),
            "reference_contract_id": reference_id,
            "underlying": str(proposal["underlying"]),
            "scanner_family_id": str(proposal["scanner_family_id"]),
            "scanner_version": str(proposal["scanner_version"]),
            "scanner_rule_version": str(proposal["scanner_rule_version"]),
            "surfaced_at": str(proposal["surfaced_at"]),
            "entry_quote_observation_id": int(quote_evidence["id"]),
            "entry_greek_observation_id": int(greek_evidence["id"]),
            "quote_freshness_class": "FRESH",
            "greek_quality_class": greek_quality,
            "universe_status": universe_status,
            "structure_id": str(proposal["structure_id"]),
            "structure_version": str(proposal["structure_version"]),
            "structure_json": str(proposal["structure_json"]),
            "hypothesis_family": str(proposal["hypothesis_family"]),
            "hypothesis_version": str(proposal["hypothesis_version"]),
            "sizing_policy_version": RISK_POLICY_VERSION,
            "max_theoretical_loss_minor": converted_max_loss_eur_minor,
            "cost_model_version": COST_MODEL_VERSION,
            "cost_provenance": COST_PROVENANCE,
            "actor": "SYSTEM",
            "reason_code": "DETERMINISTIC_INTRINSIC_RISK_RESEARCH_ADMISSION",
            "note": (
                "Research-only shadow candidate. Intrinsic trade risk is "
                "recorded independently of any external account balance."
            ),
        }
        candidate_id = create_shadow_candidate(candidate, db_path=db_path)
        event_time = _now_utc()
        append_shadow_state_event(
            candidate_id,
            to_state="INVESTIGATED",
            occurred_at=event_time,
            actor="SYSTEM",
            reason_code="DETERMINISTIC_STRUCTURE_AND_INTRINSIC_RISK_REVIEW",
            note="Automated research-only review; no wallet sizing decision.",
            db_path=db_path,
        )
        append_shadow_state_event(
            candidate_id,
            to_state="DECIDED",
            occurred_at=event_time,
            actor="SYSTEM",
            reason_code="SHADOW_RESEARCH_ADMISSION_DECISION",
            note="Admitted to shadow research only.",
            db_path=db_path,
        )
        append_shadow_state_event(
            candidate_id,
            to_state="SHADOW_TRACKED",
            occurred_at=event_time,
            actor="SYSTEM",
            reason_code="START_SHADOW_OUTCOME_TRACKING",
            note="No live order exists.",
            db_path=db_path,
        )
        append_underlying_pin_event(
            underlying=str(proposal["underlying"]),
            candidate_id=candidate_id,
            action="PIN",
            occurred_at=event_time,
            reason="Active shadow research candidate.",
            db_path=db_path,
        )

        reason_code = "SHADOW_RESEARCH_ADMITTED_INTRINSIC_RISK_VALID"
        _persist_decision(
            proposal=proposal,
            fx_observation_id=fx_observation_id,
            candidate_id=candidate_id,
            decision="ADMITTED",
            reason_code=reason_code,
            proposal_max_loss_usd_minor=max_loss_usd_minor,
            estimated_cost_usd_minor=estimated_cost_usd_minor,
            intrinsic_risk_usd_minor=intrinsic_risk_usd_minor,
            converted_max_loss_eur_minor=converted_max_loss_eur_minor,
            estimated_cost_eur_minor=estimated_cost_eur_minor,
            intrinsic_risk_eur_minor=intrinsic_risk_eur_minor,
            fx=fx,
            db_path=db_path,
        )
        decisions.append(
            ShadowAdmissionDecision(
                int(proposal["id"]),
                "ADMITTED",
                reason_code,
                candidate_id,
                fx_observation_id,
                max_loss_usd_minor,
                estimated_cost_usd_minor,
                intrinsic_risk_usd_minor,
                converted_max_loss_eur_minor,
                estimated_cost_eur_minor,
                intrinsic_risk_eur_minor,
            )
        )

    admitted = sum(item.decision == "ADMITTED" for item in decisions)
    return ShadowAdmissionResult(
        proposal_count=len(decisions),
        admitted_count=admitted,
        blocked_count=len(decisions) - admitted,
        decisions=tuple(decisions),
    )

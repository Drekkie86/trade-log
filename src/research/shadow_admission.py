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
from src.research.shadow_lifecycle import (
    classify_greek_quality,
)

UTC = ZoneInfo("UTC")

SIZING_POLICY_VERSION = (
    "SIZING_POLICY_V1_FIXED_500_EUR_ONE_UNIT"
)
BANKROLL_CAP_EUR_MINOR = 50_000

# Saxo Belgium currently publishes USD 2.00 / contract for the highest
# standard account-price category. Shadow research reserves an additional
# USD 1.00 / contract-side contingency for unmodelled exchange/other charges.
# This is explicitly an ASSUMED research cost ceiling, not an actual-fill cost.
COST_MODEL_VERSION = (
    "SAXO_BE_SHADOW_COST_CEILING_V1"
)
COST_PROVENANCE = (
    "ASSUMED_PUBLIC_TARIFF_PLUS_CONTINGENCY"
)
USD_COST_PER_CONTRACT_SIDE_MINOR = 300

ADMISSION_LABEL = (
    "CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING"
)


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
    reserved_risk_usd_minor: int
    converted_max_loss_eur_minor: int
    estimated_cost_eur_minor: int
    reserved_risk_eur_minor: int
    bankroll_cap_eur_minor: int


@dataclass(frozen=True)
class ShadowAdmissionResult:
    proposal_count: int
    admitted_count: int
    blocked_count: int
    decisions: tuple[ShadowAdmissionDecision, ...]


def _now_utc() -> str:
    return datetime.now(
        UTC
    ).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _persist_fx(
    observation: EcbFxObservation,
    *,
    db_path=None,
) -> int:
    if (
        observation.base_currency != "EUR"
        or observation.quote_currency != "USD"
    ):
        raise ShadowAdmissionError(
            "Shadow admission requires an EUR/USD "
            "observation expressed as USD per EUR."
        )

    if observation.rate <= 0:
        raise ShadowAdmissionError(
            "FX rate must be positive."
        )

    conn = get_connection(db_path)

    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO fx_observations (
                    provider,
                    base_currency,
                    quote_currency,
                    rate,
                    reference_date,
                    observed_at,
                    source_url,
                    provenance
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
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

        return int(
            cursor.lastrowid
        )
    finally:
        conn.close()


def _load_proposals(
    *,
    proposal_ids: list[int] | None,
    db_path=None,
) -> list[dict[str, Any]]:
    conn = get_connection(db_path)

    try:
        if proposal_ids:
            placeholders = ",".join(
                "?"
                for _ in proposal_ids
            )

            rows = conn.execute(
                f"""
                SELECT
                    ssp.*,
                    hse.scanner_run_id,
                    hse.option_quote_id
                        AS target_option_quote_id,
                    hsr.scanner_family_id,
                    hsr.scanner_version,
                    hsr.rule_version
                        AS scanner_rule_version,
                    hsr.hypothesis_family,
                    hsr.hypothesis_version,
                    hsr.evaluated_at
                        AS surfaced_at,
                    pmo.model_input_notes
                FROM shadow_structure_proposals AS ssp
                JOIN hypothesis_scanner_evaluations AS hse
                  ON hse.id = ssp.hypothesis_evaluation_id
                JOIN hypothesis_scanner_runs AS hsr
                  ON hsr.id = hse.scanner_run_id
                JOIN provider_model_observations AS pmo
                  ON pmo.option_quote_id =
                     hse.option_quote_id
                 AND pmo.provider = 'THETADATA'
                WHERE ssp.id IN ({placeholders})
                  AND ssp.proposal_state = 'PROPOSED'
                ORDER BY ssp.id;
                """,
                tuple(proposal_ids),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    ssp.*,
                    hse.scanner_run_id,
                    hse.option_quote_id
                        AS target_option_quote_id,
                    hsr.scanner_family_id,
                    hsr.scanner_version,
                    hsr.rule_version
                        AS scanner_rule_version,
                    hsr.hypothesis_family,
                    hsr.hypothesis_version,
                    hsr.evaluated_at
                        AS surfaced_at,
                    pmo.model_input_notes
                FROM shadow_structure_proposals AS ssp
                JOIN hypothesis_scanner_evaluations AS hse
                  ON hse.id = ssp.hypothesis_evaluation_id
                JOIN hypothesis_scanner_runs AS hsr
                  ON hsr.id = hse.scanner_run_id
                JOIN provider_model_observations AS pmo
                  ON pmo.option_quote_id =
                     hse.option_quote_id
                 AND pmo.provider = 'THETADATA'
                LEFT JOIN shadow_admission_decisions AS sad
                  ON sad.proposal_id = ssp.id
                 AND sad.sizing_policy_version = ?
                 AND sad.cost_model_version = ?
                WHERE ssp.proposal_state = 'PROPOSED'
                  AND sad.id IS NULL
                ORDER BY ssp.id;
                """,
                (
                    SIZING_POLICY_VERSION,
                    COST_MODEL_VERSION,
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]
    finally:
        conn.close()


def _structure_contract_sides(
    structure_json: str,
) -> int:
    try:
        structure = json.loads(
            structure_json
        )
        legs = structure["legs"]
    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ) as exc:
        raise ShadowAdmissionError(
            "Proposal structure_json is invalid."
        ) from exc

    total = 0

    for leg in legs:
        quantity = int(
            leg["quantity"]
        )

        if quantity <= 0:
            raise ShadowAdmissionError(
                "Structure leg quantity must be positive."
            )

        total += quantity

    if total <= 0:
        raise ShadowAdmissionError(
            "Structure must contain contract sides."
        )

    return total


def _to_eur_minor(
    usd_minor: int,
    *,
    eur_to_usd: float,
) -> int:
    # ECB quote: 1 EUR = N USD.
    # Therefore USD -> EUR = USD / N.
    return int(
        round(
            usd_minor
            / eur_to_usd
        )
    )


def _iv_error(
    model_input_notes: str | None,
) -> float | None:
    if not model_input_notes:
        return None

    try:
        payload = json.loads(
            model_input_notes
        )
    except json.JSONDecodeError:
        return None

    value = payload.get(
        "iv_error"
    )

    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _availability(
    *,
    reference_contract_id: int,
    evidence_family: str,
    db_path=None,
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
            (
                reference_contract_id,
                evidence_family,
            ),
        ).fetchone()

        return (
            None
            if row is None
            else dict(row)
        )
    finally:
        conn.close()


def _universe_status(
    *,
    reference_contract_id: int,
    db_path=None,
) -> str:
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
            (
                reference_contract_id,
            ),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return "UNUSABLE"

    if row["state"] == "PRESENT":
        return "CONSISTENT"

    return "DISAGREEMENT_RECORDED"


def _persist_decision(
    *,
    proposal: dict[str, Any],
    fx_observation_id: int,
    candidate_id: int | None,
    decision: str,
    reason_code: str,
    proposal_max_loss_usd_minor: int,
    estimated_cost_usd_minor: int,
    reserved_risk_usd_minor: int,
    converted_max_loss_eur_minor: int,
    estimated_cost_eur_minor: int,
    reserved_risk_eur_minor: int,
    fx: EcbFxObservation,
    db_path=None,
) -> int:
    evidence = json.dumps(
        {
            "admission_label":
                ADMISSION_LABEL,
            "fx":
                asdict(fx),
            "cost_model":
                {
                    "usd_per_contract_side_minor":
                        USD_COST_PER_CONTRACT_SIDE_MINOR,
                    "round_trip":
                        True,
                    "note":
                        (
                            "Public Saxo Belgium highest "
                            "standard USD option tariff is "
                            "USD 2/contract; model reserves "
                            "USD 3/contract-side for shadow "
                            "research to include contingency."
                        ),
                },
            "bankroll":
                {
                    "currency":
                        "EUR",
                    "cap_minor":
                        BANKROLL_CAP_EUR_MINOR,
                    "active_units":
                        1,
                    "automatic_replenishment":
                        False,
                },
        },
        sort_keys=True,
    )

    conn = get_connection(db_path)

    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO shadow_admission_decisions (
                    proposal_id,
                    fx_observation_id,
                    candidate_id,
                    sizing_policy_version,
                    cost_model_version,
                    cost_provenance,
                    proposal_max_loss_usd_minor,
                    estimated_cost_usd_minor,
                    reserved_risk_usd_minor,
                    converted_max_loss_eur_minor,
                    estimated_cost_eur_minor,
                    reserved_risk_eur_minor,
                    bankroll_cap_eur_minor,
                    decision,
                    reason_code,
                    decided_at,
                    evidence_json
                )
                VALUES (
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?
                );
                """,
                (
                    int(proposal["id"]),
                    fx_observation_id,
                    candidate_id,
                    SIZING_POLICY_VERSION,
                    COST_MODEL_VERSION,
                    COST_PROVENANCE,
                    proposal_max_loss_usd_minor,
                    estimated_cost_usd_minor,
                    reserved_risk_usd_minor,
                    converted_max_loss_eur_minor,
                    estimated_cost_eur_minor,
                    reserved_risk_eur_minor,
                    BANKROLL_CAP_EUR_MINOR,
                    decision,
                    reason_code,
                    _now_utc(),
                    evidence,
                ),
            )

        return int(
            cursor.lastrowid
        )
    finally:
        conn.close()


def _existing_decision(
    *,
    proposal_id: int,
    db_path=None,
) -> ShadowAdmissionDecision | None:
    conn = get_connection(db_path)

    try:
        row = conn.execute(
            """
            SELECT *
            FROM shadow_admission_decisions
            WHERE proposal_id = ?
              AND sizing_policy_version = ?
              AND cost_model_version = ?;
            """,
            (
                proposal_id,
                SIZING_POLICY_VERSION,
                COST_MODEL_VERSION,
            ),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    return ShadowAdmissionDecision(
        proposal_id=
            int(row["proposal_id"]),
        decision=
            str(row["decision"]),
        reason_code=
            str(row["reason_code"]),
        candidate_id=
            (
                None
                if row["candidate_id"]
                is None
                else int(
                    row["candidate_id"]
                )
            ),
        fx_observation_id=
            int(
                row["fx_observation_id"]
            ),
        proposal_max_loss_usd_minor=
            int(
                row[
                    "proposal_max_loss_usd_minor"
                ]
            ),
        estimated_cost_usd_minor=
            int(
                row[
                    "estimated_cost_usd_minor"
                ]
            ),
        reserved_risk_usd_minor=
            int(
                row[
                    "reserved_risk_usd_minor"
                ]
            ),
        converted_max_loss_eur_minor=
            int(
                row[
                    "converted_max_loss_eur_minor"
                ]
            ),
        estimated_cost_eur_minor=
            int(
                row[
                    "estimated_cost_eur_minor"
                ]
            ),
        reserved_risk_eur_minor=
            int(
                row[
                    "reserved_risk_eur_minor"
                ]
            ),
        bankroll_cap_eur_minor=
            int(
                row[
                    "bankroll_cap_eur_minor"
                ]
            ),
    )


def admit_shadow_proposals(
    *,
    fx: EcbFxObservation,
    proposal_ids: list[int] | None = None,
    db_path=None,
) -> ShadowAdmissionResult:
    proposals = _load_proposals(
        proposal_ids=proposal_ids,
        db_path=db_path,
    )

    decisions = []

    # Persist the source observation once per admission invocation.
    fx_observation_id = _persist_fx(
        fx,
        db_path=db_path,
    )

    for proposal in proposals:
        existing = _existing_decision(
            proposal_id=
                int(proposal["id"]),
            db_path=db_path,
        )

        if existing is not None:
            decisions.append(
                existing
            )
            continue

        max_loss_usd_minor = int(
            proposal[
                "max_theoretical_loss_minor"
            ]
        )

        contract_sides = _structure_contract_sides(
            str(proposal["structure_json"])
        )

        # Reserve entry + exit commissions/contingency.
        estimated_cost_usd_minor = (
            contract_sides
            * 2
            * USD_COST_PER_CONTRACT_SIDE_MINOR
        )

        reserved_usd_minor = (
            max_loss_usd_minor
            + estimated_cost_usd_minor
        )

        converted_max_loss_eur_minor = (
            _to_eur_minor(
                max_loss_usd_minor,
                eur_to_usd=fx.rate,
            )
        )

        estimated_cost_eur_minor = (
            _to_eur_minor(
                estimated_cost_usd_minor,
                eur_to_usd=fx.rate,
            )
        )

        reserved_eur_minor = (
            _to_eur_minor(
                reserved_usd_minor,
                eur_to_usd=fx.rate,
            )
        )

        universe_status = _universe_status(
            reference_contract_id=
                int(
                    proposal[
                        "target_reference_contract_id"
                    ]
                ),
            db_path=db_path,
        )

        quote_evidence = _availability(
            reference_contract_id=
                int(
                    proposal[
                        "target_reference_contract_id"
                    ]
                ),
            evidence_family=
                "THETADATA_QUOTE",
            db_path=db_path,
        )

        greek_evidence = _availability(
            reference_contract_id=
                int(
                    proposal[
                        "target_reference_contract_id"
                    ]
                ),
            evidence_family=
                "THETADATA_GREEKS",
            db_path=db_path,
        )

        block_reason = None

        if universe_status == "UNUSABLE":
            block_reason = (
                "UNIVERSE_EVIDENCE_UNUSABLE"
            )
        elif quote_evidence is None:
            block_reason = (
                "ENTRY_QUOTE_EVIDENCE_MISSING"
            )
        elif quote_evidence["state"] != "PRESENT":
            block_reason = (
                "ENTRY_QUOTE_NOT_PRESENT"
            )
        elif greek_evidence is None:
            block_reason = (
                "ENTRY_GREEK_EVIDENCE_MISSING"
            )
        elif greek_evidence["state"] != "PRESENT":
            block_reason = (
                "ENTRY_GREEK_NOT_PRESENT"
            )
        elif (
            reserved_eur_minor
            > BANKROLL_CAP_EUR_MINOR
        ):
            block_reason = (
                "ONE_UNIT_EXCEEDS_EUR_500_BANKROLL"
            )

        if block_reason is not None:
            _persist_decision(
                proposal=proposal,
                fx_observation_id=
                    fx_observation_id,
                candidate_id=None,
                decision="BLOCKED",
                reason_code=block_reason,
                proposal_max_loss_usd_minor=
                    max_loss_usd_minor,
                estimated_cost_usd_minor=
                    estimated_cost_usd_minor,
                reserved_risk_usd_minor=
                    reserved_usd_minor,
                converted_max_loss_eur_minor=
                    converted_max_loss_eur_minor,
                estimated_cost_eur_minor=
                    estimated_cost_eur_minor,
                reserved_risk_eur_minor=
                    reserved_eur_minor,
                fx=fx,
                db_path=db_path,
            )

            decisions.append(
                ShadowAdmissionDecision(
                    proposal_id=
                        int(proposal["id"]),
                    decision="BLOCKED",
                    reason_code=
                        block_reason,
                    candidate_id=None,
                    fx_observation_id=
                        fx_observation_id,
                    proposal_max_loss_usd_minor=
                        max_loss_usd_minor,
                    estimated_cost_usd_minor=
                        estimated_cost_usd_minor,
                    reserved_risk_usd_minor=
                        reserved_usd_minor,
                    converted_max_loss_eur_minor=
                        converted_max_loss_eur_minor,
                    estimated_cost_eur_minor=
                        estimated_cost_eur_minor,
                    reserved_risk_eur_minor=
                        reserved_eur_minor,
                    bankroll_cap_eur_minor=
                        BANKROLL_CAP_EUR_MINOR,
                )
            )
            continue

        greek_quality = (
            classify_greek_quality(
                _iv_error(
                    proposal[
                        "model_input_notes"
                    ]
                )
            ).value
        )

        candidate = {
            "research_run_id":
                int(
                    proposal[
                        "research_run_id"
                    ]
                ),
            "reference_contract_id":
                int(
                    proposal[
                        "target_reference_contract_id"
                    ]
                ),
            "underlying":
                str(
                    proposal["underlying"]
                ),
            "scanner_family_id":
                str(
                    proposal[
                        "scanner_family_id"
                    ]
                ),
            "scanner_version":
                str(
                    proposal[
                        "scanner_version"
                    ]
                ),
            "scanner_rule_version":
                str(
                    proposal[
                        "scanner_rule_version"
                    ]
                ),
            "surfaced_at":
                str(
                    proposal["surfaced_at"]
                ),
            "entry_quote_observation_id":
                int(
                    quote_evidence["id"]
                ),
            "entry_greek_observation_id":
                int(
                    greek_evidence["id"]
                ),
            "quote_freshness_class":
                "FRESH",
            "greek_quality_class":
                greek_quality,
            "universe_status":
                universe_status,
            "structure_id":
                str(
                    proposal["structure_id"]
                ),
            "structure_version":
                str(
                    proposal[
                        "structure_version"
                    ]
                ),
            "structure_json":
                str(
                    proposal["structure_json"]
                ),
            "hypothesis_family":
                str(
                    proposal[
                        "hypothesis_family"
                    ]
                ),
            "hypothesis_version":
                str(
                    proposal[
                        "hypothesis_version"
                    ]
                ),
            "sizing_policy_version":
                SIZING_POLICY_VERSION,
            # This legacy candidate field is now explicitly denominated by
            # the admission evidence: EUR theoretical max-loss cents.
            "max_theoretical_loss_minor":
                converted_max_loss_eur_minor,
            "cost_model_version":
                COST_MODEL_VERSION,
            "cost_provenance":
                COST_PROVENANCE,
            "actor":
                "SYSTEM",
            "reason_code":
                "DETERMINISTIC_SHADOW_RESEARCH_ADMISSION",
            "note":
                (
                    "Research-only shadow candidate. "
                    "No live-edge validation and no broker order."
                ),
        }

        candidate_id = create_shadow_candidate(
            candidate,
            db_path=db_path,
        )

        # Deterministic research admission traverses the existing lifecycle
        # explicitly. No human/live-trading approval is implied.
        event_time = _now_utc()

        append_shadow_state_event(
            candidate_id,
            to_state="INVESTIGATED",
            occurred_at=event_time,
            actor="SYSTEM",
            reason_code=
                "DETERMINISTIC_STRUCTURE_AND_RISK_REVIEW",
            note=
                "Automated research-only review.",
            db_path=db_path,
        )

        append_shadow_state_event(
            candidate_id,
            to_state="DECIDED",
            occurred_at=event_time,
            actor="SYSTEM",
            reason_code=
                "SHADOW_RESEARCH_ADMISSION_DECISION",
            note=
                "Admitted to shadow research only.",
            db_path=db_path,
        )

        append_shadow_state_event(
            candidate_id,
            to_state="SHADOW_TRACKED",
            occurred_at=event_time,
            actor="SYSTEM",
            reason_code=
                "START_SHADOW_OUTCOME_TRACKING",
            note=
                "No live order exists.",
            db_path=db_path,
        )

        append_underlying_pin_event(
            underlying=
                str(proposal["underlying"]),
            candidate_id=
                candidate_id,
            action="PIN",
            occurred_at=event_time,
            reason=
                "Active shadow research candidate.",
            db_path=db_path,
        )

        _persist_decision(
            proposal=proposal,
            fx_observation_id=
                fx_observation_id,
            candidate_id=
                candidate_id,
            decision="ADMITTED",
            reason_code=
                "SHADOW_RESEARCH_ADMITTED_WITHIN_EUR_500_CAP",
            proposal_max_loss_usd_minor=
                max_loss_usd_minor,
            estimated_cost_usd_minor=
                estimated_cost_usd_minor,
            reserved_risk_usd_minor=
                reserved_usd_minor,
            converted_max_loss_eur_minor=
                converted_max_loss_eur_minor,
            estimated_cost_eur_minor=
                estimated_cost_eur_minor,
            reserved_risk_eur_minor=
                reserved_eur_minor,
            fx=fx,
            db_path=db_path,
        )

        decisions.append(
            ShadowAdmissionDecision(
                proposal_id=
                    int(proposal["id"]),
                decision="ADMITTED",
                reason_code=
                    "SHADOW_RESEARCH_ADMITTED_WITHIN_EUR_500_CAP",
                candidate_id=
                    candidate_id,
                fx_observation_id=
                    fx_observation_id,
                proposal_max_loss_usd_minor=
                    max_loss_usd_minor,
                estimated_cost_usd_minor=
                    estimated_cost_usd_minor,
                reserved_risk_usd_minor=
                    reserved_usd_minor,
                converted_max_loss_eur_minor=
                    converted_max_loss_eur_minor,
                estimated_cost_eur_minor=
                    estimated_cost_eur_minor,
                reserved_risk_eur_minor=
                    reserved_eur_minor,
                bankroll_cap_eur_minor=
                    BANKROLL_CAP_EUR_MINOR,
            )
        )

    admitted = sum(
        item.decision == "ADMITTED"
        for item in decisions
    )

    return ShadowAdmissionResult(
        proposal_count=
            len(decisions),
        admitted_count=
            admitted,
        blocked_count=
            len(decisions) - admitted,
        decisions=
            tuple(decisions),
    )

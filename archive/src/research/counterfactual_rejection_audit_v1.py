from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from statistics import mean, median
from typing import Any

from src.database.repository import get_connection


PROGRAM_KEY = "COUNTERFACTUAL_REJECTION_AUDIT_V1"
PROTOCOL_VERSION = "1.0.0"
EVALUATION_VERSION = "COUNTERFACTUAL_REJECTION_FINAL_DESCRIPTIVE_V1"

FROZEN_THROUGH_SESSION_DATE = "2026-09-17"

ADMITTED_GROUP = "ADMITTED_AT_TIME"
REJECTED_GROUP = "REJECTED_AT_TIME_WALLET_ONLY"

EXPECTED_ADMITTED = 15
EXPECTED_WALLET_REJECTED = 134
EXPECTED_COHORT = 149
EXPECTED_UNRESOLVED_AT_FREEZE = 6
EXPECTED_RECOVERED_AT_FREEZE = 0


class CounterfactualRejectionAuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class CounterfactualRejectionFreezeResult:
    program_id: int
    program_key: str
    protocol_version: str
    frozen_at: str
    frozen_through_session_date: str
    source_replay_run_id: int
    cohort_n: int
    admitted_n: int
    wallet_rejected_n: int
    cohort_max_expiration: str
    config_hash: str
    created: bool


@dataclass(frozen=True)
class CounterfactualRejectionEvaluationResult:
    program_id: int
    program_key: str
    evaluation_version: str
    latest_completed_session_date: str
    cohort_n: int
    recovered_label_n: int
    unresolved_n: int
    missing_recovery_n: int
    metrics: dict[str, Any]
    persisted_evaluation_id: int | None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _hash_json(payload: dict[str, Any]) -> tuple[str, str]:
    encoded = _canonical_json(payload)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), encoded


def _latest_completed_session_date(conn) -> str | None:
    row = conn.execute(
        """
        SELECT MAX(us_session_date) AS session_date
        FROM research_runs
        WHERE status = 'COMPLETED';
        """
    ).fetchone()
    if row is None or row["session_date"] is None:
        return None
    return str(row["session_date"])


def _source_replay_run_id(conn) -> int:
    rows = conn.execute(
        """
        SELECT DISTINCT replay_run_id
        FROM historical_policy_replay_v1
        WHERE counterfactual_decision = 'WOULD_ADMIT'
        ORDER BY replay_run_id;
        """
    ).fetchall()

    if len(rows) != 1:
        raise CounterfactualRejectionAuditError(
            "Wallet-only WOULD_ADMIT cohort must resolve to exactly one "
            f"historical replay run; found {len(rows)}."
        )

    return int(rows[0]["replay_run_id"])


def _spread_to_mid(bid: float, ask: float) -> float:
    mid = (bid + ask) / 2.0
    if mid <= 0:
        raise CounterfactualRejectionAuditError(
            "Decision-time target quote has non-positive midpoint."
        )
    return (ask - bid) / mid


def _feature_payload(row: dict[str, Any]) -> dict[str, Any]:
    required = (
        "iv_residual",
        "abs_iv_residual",
        "delta",
        "implied_volatility",
        "residual_threshold",
        "bid",
        "ask",
        "structure_id",
        "structure_json",
        "entry_pricing_json",
        "max_theoretical_loss_minor",
    )

    missing = [name for name in required if row.get(name) is None]
    if missing:
        raise CounterfactualRejectionAuditError(
            "Decision-time feature snapshot is incomplete for "
            f"proposal_id={row['proposal_id']}: {missing}."
        )

    bid = float(row["bid"])
    ask = float(row["ask"])
    if bid < 0 or ask < bid:
        raise CounterfactualRejectionAuditError(
            "Decision-time target quote is invalid for "
            f"proposal_id={row['proposal_id']}."
        )

    return {
        "feature_timing": "DECISION_TIME_ONLY",
        "wallet_or_account_balance_included": False,
        "research_run_id": int(row["research_run_id"]),
        "research_session_date": str(row["us_session_date"]),
        "hypothesis_evaluation_id": int(row["hypothesis_evaluation_id"]),
        "underlying": str(row["underlying"]),
        "expiration": str(row["expiration"]),
        "right": str(row["right"]),
        "target_strike": float(row["target_strike"]),
        "lower_strike": (
            None if row["lower_strike"] is None else float(row["lower_strike"])
        ),
        "upper_strike": (
            None if row["upper_strike"] is None else float(row["upper_strike"])
        ),
        "delta": float(row["delta"]),
        "implied_volatility": float(row["implied_volatility"]),
        "iv_residual": float(row["iv_residual"]),
        "abs_iv_residual": float(row["abs_iv_residual"]),
        "residual_threshold": float(row["residual_threshold"]),
        "target_bid": bid,
        "target_ask": ask,
        "target_spread_to_mid": _spread_to_mid(bid, ask),
        "structure_id": str(row["structure_id"]),
        "max_theoretical_loss_minor": int(row["max_theoretical_loss_minor"]),
        "risk_currency": str(row["risk_currency"]),
        "estimated_cost_usd_minor": int(row["estimated_cost_usd_minor"]),
        "intrinsic_risk_usd_minor": int(row["intrinsic_risk_usd_minor"]),
    }


def _admitted_rows(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            sad.id AS source_admission_decision_id,
            sad.candidate_id AS source_candidate_id,
            NULL AS source_policy_replay_id,
            sad.proposal_id,
            sad.decided_at AS original_decided_at,
            sad.reason_code AS original_reason_code,
            sad.estimated_cost_usd_minor,
            sad.reserved_risk_usd_minor AS intrinsic_risk_usd_minor,

            ssp.research_run_id,
            ssp.hypothesis_evaluation_id,
            ssp.underlying,
            ssp.expiration,
            ssp.right,
            ssp.target_strike,
            ssp.structure_id,
            ssp.structure_json,
            ssp.entry_pricing_json,
            ssp.max_theoretical_loss_minor,
            ssp.risk_currency,

            hse.lower_strike,
            hse.upper_strike,
            hse.delta,
            hse.implied_volatility,
            hse.iv_residual,
            hse.abs_iv_residual,
            hse.residual_threshold,

            oq.bid,
            oq.ask,
            rr.us_session_date

        FROM shadow_admission_decisions AS sad
        JOIN shadow_structure_proposals AS ssp
          ON ssp.id = sad.proposal_id
        JOIN hypothesis_scanner_evaluations AS hse
          ON hse.id = ssp.hypothesis_evaluation_id
        JOIN option_quotes AS oq
          ON oq.id = hse.option_quote_id
        JOIN research_runs AS rr
          ON rr.id = ssp.research_run_id

        WHERE sad.decision = 'ADMITTED'
        ORDER BY sad.proposal_id;
        """
    ).fetchall()

    return [dict(row) for row in rows]


def _wallet_rejected_rows(
    conn,
    *,
    replay_run_id: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            sad.id AS source_admission_decision_id,
            NULL AS source_candidate_id,
            hpr.id AS source_policy_replay_id,
            hpr.proposal_id,
            hpr.original_decided_at,
            hpr.original_reason_code,
            hpr.estimated_cost_usd_minor,
            hpr.intrinsic_risk_usd_minor,

            ssp.research_run_id,
            ssp.hypothesis_evaluation_id,
            ssp.underlying,
            ssp.expiration,
            ssp.right,
            ssp.target_strike,
            ssp.structure_id,
            ssp.structure_json,
            ssp.entry_pricing_json,
            ssp.max_theoretical_loss_minor,
            ssp.risk_currency,

            hse.lower_strike,
            hse.upper_strike,
            hse.delta,
            hse.implied_volatility,
            hse.iv_residual,
            hse.abs_iv_residual,
            hse.residual_threshold,

            oq.bid,
            oq.ask,
            rr.us_session_date

        FROM historical_policy_replay_v1 AS hpr
        JOIN shadow_admission_decisions AS sad
          ON sad.id = hpr.original_admission_decision_id
        JOIN shadow_structure_proposals AS ssp
          ON ssp.id = hpr.proposal_id
        JOIN hypothesis_scanner_evaluations AS hse
          ON hse.id = ssp.hypothesis_evaluation_id
        JOIN option_quotes AS oq
          ON oq.id = hse.option_quote_id
        JOIN research_runs AS rr
          ON rr.id = ssp.research_run_id

        WHERE hpr.replay_run_id = ?
          AND hpr.counterfactual_decision = 'WOULD_ADMIT'
        ORDER BY hpr.proposal_id;
        """,
        (replay_run_id,),
    ).fetchall()

    return [dict(row) for row in rows]


def _freeze_inventory(conn) -> dict[str, Any]:
    builder_rows = conn.execute(
        """
        SELECT proposal_state, reason_code, COUNT(*) AS n
        FROM shadow_structure_proposals
        GROUP BY proposal_state, reason_code;
        """
    ).fetchall()
    builder = {
        (str(row["proposal_state"]), str(row["reason_code"])): int(row["n"])
        for row in builder_rows
    }
    expected_builder = {
        ("BLOCKED", "NON_POSITIVE_TERMINAL_UPSIDE"): 799,
        ("BLOCKED", "UNEQUAL_WING_WIDTHS"): 223,
        ("PROPOSED", "DEFINED_RISK_STRUCTURE_CONSTRUCTED"): 149,
    }
    if builder != expected_builder:
        raise CounterfactualRejectionAuditError(
            "Structure-builder inventory changed before freeze: "
            f"{builder!r}."
        )

    legacy_rows = conn.execute(
        """
        SELECT decision, reason_code, COUNT(*) AS n
        FROM shadow_admission_decisions
        GROUP BY decision, reason_code;
        """
    ).fetchall()
    legacy = {
        (str(row["decision"]), str(row["reason_code"])): int(row["n"])
        for row in legacy_rows
    }
    expected_legacy = {
        (
            "ADMITTED",
            "SHADOW_RESEARCH_ADMITTED_WITHIN_EUR_500_CAP",
        ): 15,
        (
            "BLOCKED",
            "ACTIVE_PORTFOLIO_EXCEEDS_EUR_500_BANKROLL",
        ): 133,
        (
            "BLOCKED",
            "ONE_UNIT_EXCEEDS_EUR_500_BANKROLL",
        ): 1,
    }
    if legacy != expected_legacy:
        raise CounterfactualRejectionAuditError(
            "Legacy admission inventory changed before freeze: "
            f"{legacy!r}."
        )

    replay_rows = conn.execute(
        """
        SELECT original_reason_code, counterfactual_reason_code, COUNT(*) AS n
        FROM historical_policy_replay_v1
        WHERE counterfactual_decision = 'WOULD_ADMIT'
        GROUP BY original_reason_code, counterfactual_reason_code;
        """
    ).fetchall()
    replay = {
        (
            str(row["original_reason_code"]),
            str(row["counterfactual_reason_code"]),
        ): int(row["n"])
        for row in replay_rows
    }
    expected_replay = {
        (
            "ACTIVE_PORTFOLIO_EXCEEDS_EUR_500_BANKROLL",
            "LEGACY_WALLET_ONLY_BLOCK_REMOVED",
        ): 133,
        (
            "ONE_UNIT_EXCEEDS_EUR_500_BANKROLL",
            "LEGACY_WALLET_ONLY_BLOCK_REMOVED",
        ): 1,
    }
    if replay != expected_replay:
        raise CounterfactualRejectionAuditError(
            "Historical wallet replay inventory changed before freeze: "
            f"{replay!r}."
        )

    intrinsic_count = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM shadow_intrinsic_admission_decisions_v1;
            """
        ).fetchone()[0]
    )
    if intrinsic_count != 0:
        raise CounterfactualRejectionAuditError(
            "Intrinsic-risk admission evidence already exists; this historical "
            "V1 cohort must remain the pre-intrinsic population."
        )

    return {
        "structure_builder": {
            "blocked_non_positive_terminal_upside": 799,
            "blocked_unequal_wing_widths": 223,
            "defined_risk_proposed": 149,
        },
        "legacy_admission": {
            "admitted": 15,
            "blocked_active_portfolio_wallet": 133,
            "blocked_one_unit_wallet": 1,
            "wallet_blocked_total": 134,
        },
        "wallet_replay": {
            "would_admit_active_portfolio_wallet": 133,
            "would_admit_one_unit_wallet": 1,
            "would_admit_total": 134,
        },
        "intrinsic_risk_admission_decisions": intrinsic_count,
    }


def _future_expiry_distribution(
    rows: list[dict[str, Any]],
    *,
    latest_session_date: str,
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {
        ADMITTED_GROUP: {},
        REJECTED_GROUP: {},
    }

    for row in rows:
        expiration = str(row["expiration"])
        if expiration <= latest_session_date:
            continue
        group = str(row["selection_group"])
        group_counts = result[group]
        group_counts[expiration] = group_counts.get(expiration, 0) + 1

    return result


def _outcome_state_at_freeze(
    conn,
    *,
    replay_run_id: int,
    cohort_rows: list[dict[str, Any]],
    latest_session_date: str,
) -> dict[str, Any]:
    expected_keys = set()
    proposal_ids = set()

    for row in cohort_rows:
        proposal_id = int(row["proposal_id"])
        proposal_ids.add(proposal_id)
        if row["selection_group"] == ADMITTED_GROUP:
            expected_keys.add(
                (
                    "PROSPECTIVE_ORIGINAL",
                    int(row["source_candidate_id"]),
                    None,
                )
            )
        else:
            expected_keys.add(
                (
                    "RETROSPECTIVE_POLICY_REPLAY",
                    None,
                    int(row["source_policy_replay_id"]),
                )
            )

    outcome_rows = conn.execute(
        """
        SELECT
            source_population,
            source_candidate_id,
            policy_replay_id,
            proposal_id,
            recovery_state,
            reason_code,
            measurement_role,
            outcome_eligible
        FROM historical_outcome_recovery_v1
        WHERE replay_run_id = ?;
        """,
        (replay_run_id,),
    ).fetchall()

    relevant = []
    for item in outcome_rows:
        key = (
            str(item["source_population"]),
            (
                None
                if item["source_candidate_id"] is None
                else int(item["source_candidate_id"])
            ),
            (
                None
                if item["policy_replay_id"] is None
                else int(item["policy_replay_id"])
            ),
        )
        if key in expected_keys and int(item["proposal_id"]) in proposal_ids:
            relevant.append(dict(item))

    for row in relevant:
        if str(row["measurement_role"]) != "RETROSPECTIVE_EXPIRY_RECONSTRUCTION":
            raise CounterfactualRejectionAuditError(
                "Unexpected outcome-recovery measurement role in frozen cohort."
            )
        if int(row["outcome_eligible"]) != 0:
            raise CounterfactualRejectionAuditError(
                "Frozen retrospective outcome recovery must remain outcome_eligible=0."
            )

    recovered = sum(row["recovery_state"] == "RECOVERED" for row in relevant)
    unresolved = sum(row["recovery_state"] == "UNRESOLVED" for row in relevant)

    maturity_by_group = {}
    for group in (ADMITTED_GROUP, REJECTED_GROUP):
        group_rows = [
            row for row in cohort_rows
            if row["selection_group"] == group
        ]
        maturity_by_group[group] = {
            "matured_before_latest_session": sum(
                str(row["expiration"]) < latest_session_date
                for row in group_rows
            ),
            "expires_on_latest_session": sum(
                str(row["expiration"]) == latest_session_date
                for row in group_rows
            ),
            "future_expiry": sum(
                str(row["expiration"]) > latest_session_date
                for row in group_rows
            ),
        }

    matured = sum(
        item["matured_before_latest_session"]
        for item in maturity_by_group.values()
    )
    expires_on_latest = sum(
        item["expires_on_latest_session"]
        for item in maturity_by_group.values()
    )
    future = sum(
        item["future_expiry"]
        for item in maturity_by_group.values()
    )

    return {
        "latest_completed_session_date": latest_session_date,
        "matured_before_latest_session": matured,
        "expires_on_latest_session": expires_on_latest,
        "future_expiry": future,
        "maturity_by_selection_group": maturity_by_group,
        "recovered": recovered,
        "unresolved": unresolved,
        "no_recovery_record": len(cohort_rows) - len(relevant),
        "unresolved_reason_counts": {
            reason: sum(
                row["recovery_state"] == "UNRESOLVED"
                and row["reason_code"] == reason
                for row in relevant
            )
            for reason in sorted(
                {
                    str(row["reason_code"])
                    for row in relevant
                    if row["recovery_state"] == "UNRESOLVED"
                }
            )
        },
    }


def _protocol_config(*, cohort_max_expiration: str) -> dict[str, Any]:
    return {
        "program_key": PROGRAM_KEY,
        "protocol_version": PROTOCOL_VERSION,
        "classification": "RETROSPECTIVE_DISCOVERY_NOT_EDGE_EVIDENCE",
        "cohort": {
            "selection_groups": [
                ADMITTED_GROUP,
                REJECTED_GROUP,
            ],
            "fixed_membership_after_freeze": True,
            "wallet_gate_role": "COHORT_PROVENANCE_ONLY",
            "wallet_gate_predictive_feature": False,
        },
        "feature_policy": {
            "decision_time_information_only": True,
            "future_information_may_label_outcome_only": True,
            "silent_feature_backfill": False,
            "wallet_or_account_balance_feature": False,
        },
        "outcome_policy": {
            "source": "historical_outcome_recovery_v1",
            "measurement_role": "RETROSPECTIVE_EXPIRY_RECONSTRUCTION",
            "outcome_eligible_required": False,
            "label_family": [
                "RETROSPECTIVE_EXPIRY_RECON_NET_POSITIVE",
                "RETROSPECTIVE_EXPIRY_RECON_NET_ZERO",
                "RETROSPECTIVE_EXPIRY_RECON_NET_NEGATIVE",
            ],
            "independent_leg_liquidation_replay_as_label": False,
            "validated_package_pnl_claim": False,
            "missing_outcomes_imputed": False,
        },
        "evaluation_policy": {
            "intermediate_outcome_peeking": False,
            "final_evaluation_trigger": (
                "latest completed research session must be strictly after "
                "the maximum frozen cohort expiration"
            ),
            "cohort_max_expiration": cohort_max_expiration,
            "primary_descriptive_metric": (
                "estimated_net_pnl_usd_minor divided by frozen "
                "intrinsic_risk_usd_minor"
            ),
            "secondary_descriptors": [
                "estimated_net_pnl_usd_minor",
                "three_way_outcome_label_counts",
                "positive_vs_non_positive_2x2_counts",
            ],
            "p_values_enabled": False,
            "model_training_enabled": False,
            "admission_change_enabled": False,
            "decision_enabled": False,
        },
        "deferred_populations": {
            "scanner_not_surfaced": (
                "No frozen multi-leg structure exists; separate "
                "counterfactual-expression protocol required."
            ),
            "structure_builder_blocked": (
                "No admitted-equivalent frozen structure exists; separate "
                "counterfactual-expression protocol required."
            ),
        },
    }


def _discovery_context(
    *,
    replay_run_id: int,
    cohort_rows: list[dict[str, Any]],
    latest_session_date: str,
    outcome_state: dict[str, Any],
    freeze_inventory: dict[str, Any],
) -> dict[str, Any]:
    admitted_n = sum(
        row["selection_group"] == ADMITTED_GROUP
        for row in cohort_rows
    )
    rejected_n = sum(
        row["selection_group"] == REJECTED_GROUP
        for row in cohort_rows
    )

    future_distribution = _future_expiry_distribution(
        cohort_rows,
        latest_session_date=latest_session_date,
    )

    return {
        "classification": "RETROSPECTIVE_DISCOVERY_NOT_EDGE_EVIDENCE",
        "freeze_inventory": {
            "latest_completed_session_date": latest_session_date,
            "source_replay_run_id": replay_run_id,
            **freeze_inventory,
        },
        "fixed_cohort": {
            "total": len(cohort_rows),
            "admitted_at_time": admitted_n,
            "rejected_at_time_wallet_only": rejected_n,
            "decision_time_feature_coverage_complete": len(cohort_rows),
            "feature_coverage_fields": [
                "iv_residual",
                "delta",
                "implied_volatility",
                "target_quote_spread",
                "structure_and_entry",
                "defined_max_loss",
            ],
        },
        "outcome_state_at_freeze": outcome_state,
        "future_expiry_distribution": future_distribution,
        "scientific_boundaries": {
            "wallet_gate_is_predictive_feature": False,
            "future_information_role": "OUTCOME_LABEL_ONLY",
            "independent_leg_liquidation_replay_as_label": False,
            "expiry_reconstruction_outcome_eligible": False,
            "edge_claim": False,
            "model_training": False,
            "admission_change": False,
        },
    }


def freeze_counterfactual_rejection_audit_v1(
    *,
    db_path=None,
) -> CounterfactualRejectionFreezeResult:
    conn = get_connection(db_path)
    try:
        existing = conn.execute(
            """
            SELECT *
            FROM counterfactual_rejection_audit_programs_v1
            WHERE program_key = ?;
            """,
            (PROGRAM_KEY,),
        ).fetchone()

        if existing is not None:
            counts = conn.execute(
                """
                SELECT
                    COUNT(*) AS cohort_n,
                    SUM(selection_group = ?) AS admitted_n,
                    SUM(selection_group = ?) AS rejected_n
                FROM counterfactual_rejection_audit_cohort_v1
                WHERE program_id = ?;
                """,
                (
                    ADMITTED_GROUP,
                    REJECTED_GROUP,
                    int(existing["id"]),
                ),
            ).fetchone()
            return CounterfactualRejectionFreezeResult(
                program_id=int(existing["id"]),
                program_key=str(existing["program_key"]),
                protocol_version=str(existing["protocol_version"]),
                frozen_at=str(existing["frozen_at"]),
                frozen_through_session_date=str(
                    existing["frozen_through_session_date"]
                ),
                source_replay_run_id=int(existing["source_replay_run_id"]),
                cohort_n=int(counts["cohort_n"]),
                admitted_n=int(counts["admitted_n"]),
                wallet_rejected_n=int(counts["rejected_n"]),
                cohort_max_expiration=str(existing["cohort_max_expiration"]),
                config_hash=str(existing["config_hash"]),
                created=False,
            )

        latest_session = _latest_completed_session_date(conn)
        if latest_session != FROZEN_THROUGH_SESSION_DATE:
            raise CounterfactualRejectionAuditError(
                "Counterfactual rejection audit freeze refused: latest completed "
                f"research session is {latest_session!r}; expected exactly "
                f"{FROZEN_THROUGH_SESSION_DATE!r} so the cohort is frozen before "
                "Sep-18 outcome evidence."
            )

        replay_run_id = _source_replay_run_id(conn)
        freeze_inventory = _freeze_inventory(conn)
        admitted = _admitted_rows(conn)
        rejected = _wallet_rejected_rows(
            conn,
            replay_run_id=replay_run_id,
        )

        if len(admitted) != EXPECTED_ADMITTED:
            raise CounterfactualRejectionAuditError(
                f"Expected {EXPECTED_ADMITTED} admitted proposals; found {len(admitted)}."
            )
        if len(rejected) != EXPECTED_WALLET_REJECTED:
            raise CounterfactualRejectionAuditError(
                "Expected "
                f"{EXPECTED_WALLET_REJECTED} wallet-only rejected proposals; "
                f"found {len(rejected)}."
            )

        cohort_rows: list[dict[str, Any]] = []

        for group, source_rows in (
            (ADMITTED_GROUP, admitted),
            (REJECTED_GROUP, rejected),
        ):
            for source in source_rows:
                row = dict(source)
                row["selection_group"] = group
                row["decision_time_features"] = _feature_payload(row)
                cohort_rows.append(row)

        proposal_ids = [int(row["proposal_id"]) for row in cohort_rows]
        if len(cohort_rows) != EXPECTED_COHORT:
            raise CounterfactualRejectionAuditError(
                f"Expected {EXPECTED_COHORT} cohort rows; found {len(cohort_rows)}."
            )
        if len(set(proposal_ids)) != EXPECTED_COHORT:
            raise CounterfactualRejectionAuditError(
                "Counterfactual rejection cohort contains duplicate proposals."
            )

        proposed_ids = {
            int(row["id"])
            for row in conn.execute(
                """
                SELECT id
                FROM shadow_structure_proposals
                WHERE proposal_state = 'PROPOSED';
                """
            ).fetchall()
        }
        if set(proposal_ids) != proposed_ids:
            raise CounterfactualRejectionAuditError(
                "Frozen admitted + wallet-rejected cohort does not exactly equal "
                "the complete defined-risk PROPOSED structure population."
            )

        cohort_max_expiration = max(
            str(row["expiration"])
            for row in cohort_rows
        )

        outcome_state = _outcome_state_at_freeze(
            conn,
            replay_run_id=replay_run_id,
            cohort_rows=cohort_rows,
            latest_session_date=latest_session,
        )

        if outcome_state["recovered"] != EXPECTED_RECOVERED_AT_FREEZE:
            raise CounterfactualRejectionAuditError(
                "Freeze refused: recovered outcome labels already exist."
            )
        if outcome_state["unresolved"] != EXPECTED_UNRESOLVED_AT_FREEZE:
            raise CounterfactualRejectionAuditError(
                "Unexpected unresolved-outcome count at freeze: "
                f"{outcome_state['unresolved']}."
            )
        if outcome_state["matured_before_latest_session"] != 6:
            raise CounterfactualRejectionAuditError(
                "Unexpected mature-cohort count at freeze."
            )
        if outcome_state["expires_on_latest_session"] != 0:
            raise CounterfactualRejectionAuditError(
                "Unexpected same-session expiry at freeze."
            )
        if outcome_state["future_expiry"] != 143:
            raise CounterfactualRejectionAuditError(
                "Unexpected future-expiry cohort count at freeze."
            )
        if outcome_state["no_recovery_record"] != 143:
            raise CounterfactualRejectionAuditError(
                "Unexpected no-recovery-record count at freeze."
            )
        if outcome_state["unresolved_reason_counts"] != {
            "MISSING_EXPIRY_SESSION_UNDERLYING_SNAPSHOT": 6
        }:
            raise CounterfactualRejectionAuditError(
                "Unexpected unresolved-outcome reason distribution at freeze."
            )

        config = _protocol_config(
            cohort_max_expiration=cohort_max_expiration,
        )
        config_hash, config_json = _hash_json(config)
        discovery_context = _discovery_context(
            replay_run_id=replay_run_id,
            cohort_rows=cohort_rows,
            latest_session_date=latest_session,
            outcome_state=outcome_state,
            freeze_inventory=freeze_inventory,
        )
        discovery_json = _canonical_json(discovery_context)
        frozen_at = _utc_now()

        with conn:
            cursor = conn.execute(
                """
                INSERT INTO counterfactual_rejection_audit_programs_v1(
                    program_key,
                    protocol_version,
                    frozen_at,
                    frozen_through_session_date,
                    source_replay_run_id,
                    cohort_max_expiration,
                    protocol_state,
                    config_hash,
                    config_json,
                    discovery_context_json,
                    outcome_label_semantics,
                    wallet_feature_enabled,
                    independent_leg_liquidation_label_enabled,
                    p_values_enabled,
                    model_training_enabled,
                    admission_change_enabled,
                    decision_enabled
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    'FROZEN_RETROSPECTIVE_DISCOVERY_OUTCOME_PENDING',
                    ?, ?, ?,
                    'RETROSPECTIVE_EXPIRY_RECONSTRUCTION_ONLY',
                    0, 0, 0, 0, 0, 0
                );
                """,
                (
                    PROGRAM_KEY,
                    PROTOCOL_VERSION,
                    frozen_at,
                    FROZEN_THROUGH_SESSION_DATE,
                    replay_run_id,
                    cohort_max_expiration,
                    config_hash,
                    config_json,
                    discovery_json,
                ),
            )
            program_id = int(cursor.lastrowid)

            conn.executemany(
                """
                INSERT INTO counterfactual_rejection_audit_cohort_v1(
                    program_id,
                    proposal_id,
                    selection_group,
                    source_admission_decision_id,
                    source_candidate_id,
                    source_policy_replay_id,
                    underlying,
                    expiration,
                    original_decided_at,
                    original_reason_code,
                    intrinsic_risk_usd_minor,
                    estimated_cost_usd_minor,
                    decision_time_features_json,
                    cohort_role
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'FIXED_HISTORICAL_SELECTION_COHORT'
                );
                """,
                [
                    (
                        program_id,
                        int(row["proposal_id"]),
                        str(row["selection_group"]),
                        int(row["source_admission_decision_id"]),
                        (
                            None
                            if row["source_candidate_id"] is None
                            else int(row["source_candidate_id"])
                        ),
                        (
                            None
                            if row["source_policy_replay_id"] is None
                            else int(row["source_policy_replay_id"])
                        ),
                        str(row["underlying"]),
                        str(row["expiration"]),
                        str(row["original_decided_at"]),
                        str(row["original_reason_code"]),
                        int(row["intrinsic_risk_usd_minor"]),
                        int(row["estimated_cost_usd_minor"]),
                        _canonical_json(row["decision_time_features"]),
                    )
                    for row in cohort_rows
                ],
            )

        return CounterfactualRejectionFreezeResult(
            program_id=program_id,
            program_key=PROGRAM_KEY,
            protocol_version=PROTOCOL_VERSION,
            frozen_at=frozen_at,
            frozen_through_session_date=FROZEN_THROUGH_SESSION_DATE,
            source_replay_run_id=replay_run_id,
            cohort_n=len(cohort_rows),
            admitted_n=len(admitted),
            wallet_rejected_n=len(rejected),
            cohort_max_expiration=cohort_max_expiration,
            config_hash=config_hash,
            created=True,
        )
    finally:
        conn.close()


def _group_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    recovered = [
        row
        for row in rows
        if row["recovery_state"] == "RECOVERED"
        and row["estimated_net_pnl_usd_minor"] is not None
    ]

    pnl = [
        int(row["estimated_net_pnl_usd_minor"])
        for row in recovered
    ]
    normalized = [
        int(row["estimated_net_pnl_usd_minor"])
        / int(row["intrinsic_risk_usd_minor"])
        for row in recovered
    ]

    labels = {
        "RETROSPECTIVE_EXPIRY_RECON_NET_POSITIVE": 0,
        "RETROSPECTIVE_EXPIRY_RECON_NET_ZERO": 0,
        "RETROSPECTIVE_EXPIRY_RECON_NET_NEGATIVE": 0,
    }
    for row in recovered:
        labels[str(row["outcome_label"])] += 1

    return {
        "cohort_n": len(rows),
        "recovered_label_n": len(recovered),
        "unresolved_n": sum(
            row["recovery_state"] == "UNRESOLVED"
            for row in rows
        ),
        "missing_recovery_n": sum(
            row["recovery_state"] is None
            for row in rows
        ),
        "outcome_label_counts": labels,
        "net_pnl_usd_minor": {
            "mean": None if not pnl else float(mean(pnl)),
            "median": None if not pnl else float(median(pnl)),
        },
        "net_pnl_over_intrinsic_risk": {
            "mean": None if not normalized else float(mean(normalized)),
            "median": None if not normalized else float(median(normalized)),
        },
    }


def evaluate_counterfactual_rejection_audit_v1(
    *,
    db_path=None,
    persist: bool = True,
) -> CounterfactualRejectionEvaluationResult:
    conn = get_connection(db_path)
    try:
        program = conn.execute(
            """
            SELECT *
            FROM counterfactual_rejection_audit_programs_v1
            WHERE program_key = ?;
            """,
            (PROGRAM_KEY,),
        ).fetchone()
        if program is None:
            raise CounterfactualRejectionAuditError(
                "Counterfactual rejection audit is not frozen."
            )

        latest_session = _latest_completed_session_date(conn)
        if latest_session is None:
            raise CounterfactualRejectionAuditError(
                "No completed research session is available."
            )

        max_expiration = str(program["cohort_max_expiration"])
        if latest_session <= max_expiration:
            raise CounterfactualRejectionAuditError(
                "Final rejection-audit evaluation is not yet allowed: latest "
                f"completed session {latest_session} must be strictly after "
                f"cohort maximum expiration {max_expiration}."
            )

        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM v_counterfactual_rejection_audit_labels_v1
                WHERE program_id = ?
                ORDER BY selection_group, proposal_id;
                """,
                (int(program["id"]),),
            ).fetchall()
        ]

        if len(rows) != EXPECTED_COHORT:
            raise CounterfactualRejectionAuditError(
                f"Frozen cohort size changed: expected {EXPECTED_COHORT}, found {len(rows)}."
            )

        by_group = {
            ADMITTED_GROUP: [
                row for row in rows
                if row["selection_group"] == ADMITTED_GROUP
            ],
            REJECTED_GROUP: [
                row for row in rows
                if row["selection_group"] == REJECTED_GROUP
            ],
        }

        group_metrics = {
            group: _group_metrics(items)
            for group, items in by_group.items()
        }

        recovered_n = sum(
            item["recovered_label_n"]
            for item in group_metrics.values()
        )
        unresolved_n = sum(
            item["unresolved_n"]
            for item in group_metrics.values()
        )
        missing_n = sum(
            item["missing_recovery_n"]
            for item in group_metrics.values()
        )

        if missing_n:
            raise CounterfactualRejectionAuditError(
                "Final rejection-audit evaluation refused: outcome recovery has "
                f"not been attempted for {missing_n} frozen cohort member(s). "
                "Run the frozen recovery pipeline first; unresolved outcomes "
                "may remain unresolved, but silent missing records are not "
                "accepted."
            )

        metrics = {
            "classification": "RETROSPECTIVE_DISCOVERY_NOT_EDGE_EVIDENCE",
            "evaluation_trigger": {
                "latest_completed_session_date": latest_session,
                "cohort_max_expiration": max_expiration,
                "trigger_satisfied": True,
                "intermediate_outcome_peeking": False,
            },
            "groups": group_metrics,
            "positive_vs_non_positive_2x2": {
                group: {
                    "positive": data["outcome_label_counts"][
                        "RETROSPECTIVE_EXPIRY_RECON_NET_POSITIVE"
                    ],
                    "non_positive": (
                        data["outcome_label_counts"][
                            "RETROSPECTIVE_EXPIRY_RECON_NET_ZERO"
                        ]
                        + data["outcome_label_counts"][
                            "RETROSPECTIVE_EXPIRY_RECON_NET_NEGATIVE"
                        ]
                    ),
                }
                for group, data in group_metrics.items()
            },
            "missingness": {
                "unresolved_n": unresolved_n,
                "missing_recovery_n": missing_n,
                "imputed": False,
            },
            "guardrails": {
                "wallet_gate_predictive_feature": False,
                "independent_leg_liquidation_replay_as_label": False,
                "validated_package_pnl_claim": False,
                "p_values_enabled": False,
                "model_training_enabled": False,
                "admission_change_enabled": False,
                "decision_enabled": False,
            },
        }

        persisted_id = None
        if persist:
            existing = conn.execute(
                """
                SELECT id
                FROM counterfactual_rejection_audit_evaluations_v1
                WHERE program_id = ?
                  AND evaluation_version = ?;
                """,
                (
                    int(program["id"]),
                    EVALUATION_VERSION,
                ),
            ).fetchone()

            if existing is not None:
                persisted_id = int(existing["id"])
            else:
                with conn:
                    cursor = conn.execute(
                        """
                        INSERT INTO counterfactual_rejection_audit_evaluations_v1(
                            program_id,
                            evaluation_version,
                            evaluated_at,
                            latest_completed_session_date,
                            cohort_n,
                            recovered_label_n,
                            unresolved_n,
                            missing_recovery_n,
                            evaluation_state,
                            metrics_json,
                            p_values_enabled,
                            model_training_enabled,
                            admission_change_enabled,
                            decision_enabled
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?,
                            'FINAL_RETROSPECTIVE_DISCOVERY_AUDIT',
                            ?,
                            0, 0, 0, 0
                        );
                        """,
                        (
                            int(program["id"]),
                            EVALUATION_VERSION,
                            _utc_now(),
                            latest_session,
                            len(rows),
                            recovered_n,
                            unresolved_n,
                            missing_n,
                            _canonical_json(metrics),
                        ),
                    )
                    persisted_id = int(cursor.lastrowid)

        return CounterfactualRejectionEvaluationResult(
            program_id=int(program["id"]),
            program_key=str(program["program_key"]),
            evaluation_version=EVALUATION_VERSION,
            latest_completed_session_date=latest_session,
            cohort_n=len(rows),
            recovered_label_n=recovered_n,
            unresolved_n=unresolved_n,
            missing_recovery_n=missing_n,
            metrics=metrics,
            persisted_evaluation_id=persisted_id,
        )
    finally:
        conn.close()


def freeze_result_as_dict(
    result: CounterfactualRejectionFreezeResult,
) -> dict[str, Any]:
    return asdict(result) | {
        "guardrail": (
            "Frozen retrospective-discovery cohort only. Wallet/account status "
            "is provenance, never a predictive feature. No outcome labels were "
            "available when this programme was frozen."
        )
    }


def evaluation_result_as_dict(
    result: CounterfactualRejectionEvaluationResult,
) -> dict[str, Any]:
    return asdict(result) | {
        "guardrail": (
            "Retrospective discovery only. Expiry reconstruction remains "
            "outcome_eligible=0 and is not validated package P&L or edge evidence."
        )
    }

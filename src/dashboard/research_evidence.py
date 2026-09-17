from __future__ import annotations

import json
from datetime import datetime
from typing import Any


COMPLETE_REPLAY_MARK = "COMPLETE_RECONSTRUCTED_CONSERVATIVE_LIQUIDATION"
LIQUIDATION_STRESS_ROLE = "RETROSPECTIVE_CONSERVATIVE_LIQUIDATION_REPLAY"


def _parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def assess_replay_liquidation_stress(
    row: dict[str, Any],
) -> dict[str, Any]:
    """Describe a replay mark without promoting it to economic P&L.

    Historical replay marks cross each displayed leg independently:
    original longs are liquidated at bid and original shorts at ask.
    This is a useful liquidity-stress measurement, but it is not a
    package-execution quote and is never outcome-eligible.

    The function reconstructs the same package at leg midpoints only as
    a coherence diagnostic. Midpoint values are not treated as executable
    prices or validated outcomes.
    """

    evidence = _parse_json_object(row.get("evidence_json"))
    structure = _parse_json_object(row.get("structure_json"))
    leg_marks = evidence.get("leg_evidence")
    structure_legs = structure.get("legs")

    result: dict[str, Any] = {
        "policy_replay_id": row.get("policy_replay_id"),
        "proposal_id": row.get("proposal_id"),
        "underlying": row.get("underlying"),
        "expiration": row.get("expiration"),
        "structure_id": row.get("structure_id"),
        "quality_state": row.get("quality_state"),
        "measurement_role": row.get("measurement_role"),
        "outcome_eligible": int(row.get("outcome_eligible") or 0),
        "economic_pnl_eligible": False,
        "interpretation": "LEG_CROSS_LIQUIDATION_STRESS",
        "package_coherence_state": "NOT_EVALUABLE",
        "spread_crossing_penalty_eur_minor": None,
        "midpoint_diagnostic_net_eur_minor": None,
        "conservative_stress_net_eur_minor": row.get(
            "estimated_net_pnl_eur_minor"
        ),
        "stress_loss_to_intrinsic_risk": None,
        "midpoint_loss_to_intrinsic_risk": None,
        "max_leg_spread_to_mid": None,
        "quote_time_span_seconds": None,
        "package_mid_value_usd_minor": None,
        "package_value_lower_bound_usd_minor": None,
        "package_value_upper_bound_usd_minor": None,
    }

    intrinsic_risk_eur_minor = row.get("intrinsic_risk_eur_minor")
    stress_net_eur_minor = row.get("estimated_net_pnl_eur_minor")
    if (
        intrinsic_risk_eur_minor is not None
        and int(intrinsic_risk_eur_minor) > 0
        and stress_net_eur_minor is not None
        and int(stress_net_eur_minor) < 0
    ):
        result["stress_loss_to_intrinsic_risk"] = round(
            abs(int(stress_net_eur_minor)) / int(intrinsic_risk_eur_minor),
            4,
        )

    if (
        row.get("quality_state") != COMPLETE_REPLAY_MARK
        or not isinstance(leg_marks, list)
        or not isinstance(structure_legs, list)
        or not leg_marks
        or len(leg_marks) != len(structure_legs)
    ):
        return result

    midpoint_value_usd = 0.0
    spread_penalty_usd = 0.0
    spread_ratios: list[float] = []
    quote_times: list[datetime] = []

    for structure_leg, mark_leg in zip(structure_legs, leg_marks):
        if str(mark_leg.get("state")) != "COMPLETE":
            return result

        try:
            bid = float(mark_leg["bid"])
            ask = float(mark_leg["ask"])
            side = str(structure_leg["side"]).upper()
            quantity = int(structure_leg["quantity"])
            multiplier = float(structure_leg["shares_per_contract"])
        except (KeyError, TypeError, ValueError):
            return result

        if (
            bid < 0
            or ask < bid
            or quantity <= 0
            or multiplier <= 0
            or side not in {"BUY", "SELL"}
        ):
            return result

        midpoint = (bid + ask) / 2.0
        position_sign = 1.0 if side == "BUY" else -1.0
        midpoint_value_usd += (
            position_sign * quantity * multiplier * midpoint
        )

        half_spread = (ask - bid) / 2.0
        spread_penalty_usd += quantity * multiplier * half_spread

        if midpoint > 0:
            spread_ratios.append((ask - bid) / midpoint)

        quote_time = _parse_timestamp(mark_leg.get("quote_at"))
        if quote_time is not None:
            quote_times.append(quote_time)

    entry_cashflow_usd_minor = evidence.get("entry_cashflow_usd_minor")
    estimated_cost_usd_minor = row.get("estimated_cost_usd_minor")
    entry_fx = row.get("entry_eur_to_usd")

    try:
        midpoint_mark_usd_minor = int(round(midpoint_value_usd * 100))
        midpoint_net_usd_minor = (
            int(entry_cashflow_usd_minor)
            + midpoint_mark_usd_minor
            - int(estimated_cost_usd_minor)
        )
        midpoint_net_eur_minor = int(
            round(midpoint_net_usd_minor / float(entry_fx))
        )
        spread_penalty_eur_minor = int(
            round((spread_penalty_usd * 100) / float(entry_fx))
        )
    except (TypeError, ValueError, ZeroDivisionError):
        midpoint_net_eur_minor = None
        spread_penalty_eur_minor = None

    result["package_mid_value_usd_minor"] = int(
        round(midpoint_value_usd * 100)
    )
    result["midpoint_diagnostic_net_eur_minor"] = midpoint_net_eur_minor
    result["spread_crossing_penalty_eur_minor"] = spread_penalty_eur_minor
    result["max_leg_spread_to_mid"] = (
        None if not spread_ratios else round(max(spread_ratios), 6)
    )

    if len(quote_times) >= 2:
        result["quote_time_span_seconds"] = round(
            (max(quote_times) - min(quote_times)).total_seconds(),
            6,
        )
    elif quote_times:
        result["quote_time_span_seconds"] = 0.0

    if (
        intrinsic_risk_eur_minor is not None
        and int(intrinsic_risk_eur_minor) > 0
        and midpoint_net_eur_minor is not None
        and midpoint_net_eur_minor < 0
    ):
        result["midpoint_loss_to_intrinsic_risk"] = round(
            abs(midpoint_net_eur_minor)
            / int(intrinsic_risk_eur_minor),
            4,
        )

    structure_id = str(row.get("structure_id") or "")
    if structure_id in {
        "LONG_1_2_1_BUTTERFLY",
        "REVERSE_1_2_1_BUTTERFLY",
    }:
        try:
            strikes = sorted(
                {float(item["strike"]) for item in structure_legs}
            )
            multipliers = {
                float(item["shares_per_contract"])
                for item in structure_legs
            }
        except (KeyError, TypeError, ValueError):
            return result

        if len(strikes) == 3 and len(multipliers) == 1:
            left_width = strikes[1] - strikes[0]
            right_width = strikes[2] - strikes[1]
            multiplier = next(iter(multipliers))

            if (
                left_width > 0
                and abs(left_width - right_width) <= 1e-9
                and multiplier > 0
            ):
                max_value_usd_minor = int(
                    round(left_width * multiplier * 100)
                )

                if structure_id == "LONG_1_2_1_BUTTERFLY":
                    lower = 0
                    upper = max_value_usd_minor
                else:
                    lower = -max_value_usd_minor
                    upper = 0

                result["package_value_lower_bound_usd_minor"] = lower
                result["package_value_upper_bound_usd_minor"] = upper

                midpoint_minor = int(
                    result["package_mid_value_usd_minor"]
                )
                result["package_coherence_state"] = (
                    "COHERENT_WITH_BUTTERFLY_BOUNDS"
                    if lower <= midpoint_minor <= upper
                    else "MIDPOINT_OUTSIDE_BUTTERFLY_BOUNDS"
                )

    return result

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from statistics import mean
from typing import Any

from src.quant.bench import run_vanilla_bench
from src.quant.types import QuantInputError, VanillaOption
from src.research.settlement_policy import classify_settlement

BANKROLL_CAP_EUR = 500.0


@dataclass(frozen=True)
class RiskPlan:
    configured: bool
    max_trade_risk_eur: float | None
    stop_loss_fraction: float | None
    reserved_risk_eur: float | None
    planned_loss_trigger_eur: float | None
    bankroll_fraction: float | None
    passes_risk_budget: bool
    state: str
    note: str

    def as_dict(self) -> dict:
        return asdict(self)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _minor_to_major(value: Any) -> float | None:
    numeric = _as_float(value)
    return None if numeric is None else numeric / 100.0


def build_risk_plan(
    candidate: dict[str, Any],
    *,
    max_trade_risk_eur: float | None,
    stop_loss_fraction: float | None,
) -> RiskPlan:
    reserved = _minor_to_major(candidate.get("reserved_risk_eur_minor"))
    configured = bool(
        max_trade_risk_eur is not None
        and max_trade_risk_eur > 0
        and stop_loss_fraction is not None
        and 0 < stop_loss_fraction <= 1
    )

    if not configured:
        return RiskPlan(
            configured=False,
            max_trade_risk_eur=max_trade_risk_eur,
            stop_loss_fraction=stop_loss_fraction,
            reserved_risk_eur=reserved,
            planned_loss_trigger_eur=None,
            bankroll_fraction=None if reserved is None else reserved / BANKROLL_CAP_EUR,
            passes_risk_budget=False,
            state="BLOCKED_RISK_POLICY_NOT_CONFIGURED",
            note=(
                "Set an explicit per-trade loss budget and monitoring stop fraction. "
                "A stop threshold is a monitoring rule, not a guaranteed execution price."
            ),
        )

    passes = reserved is not None and reserved <= float(max_trade_risk_eur)
    base = None if reserved is None else min(reserved, float(max_trade_risk_eur))
    trigger = None if base is None else base * float(stop_loss_fraction)

    return RiskPlan(
        configured=True,
        max_trade_risk_eur=float(max_trade_risk_eur),
        stop_loss_fraction=float(stop_loss_fraction),
        reserved_risk_eur=reserved,
        planned_loss_trigger_eur=trigger,
        bankroll_fraction=None if reserved is None else reserved / BANKROLL_CAP_EUR,
        passes_risk_budget=passes,
        state="RISK_POLICY_PASS" if passes else "BLOCKED_RISK_BUDGET_EXCEEDED",
        note=(
            "Defined-risk max loss remains the primary protection. The planned loss trigger "
            "is a manual monitoring threshold, not a guaranteed execution price; option prices can gap through it."
        ),
    )


def _research_priority_key(candidate: dict[str, Any]) -> tuple:
    """Transparent research-review ordering, never a live-trade score."""
    settlement = classify_settlement(
        candidate.get("underlying"),
        observed_exercise_style=candidate.get("exercise_style"),
    )
    validated = int(candidate.get("validated_outcomes") or 0)
    marks = int(candidate.get("mark_count") or 0)
    abs_residual = abs(_as_float(candidate.get("abs_iv_residual")) or 0.0)
    admitted = 1 if candidate.get("admission_decision") == "ADMITTED" else 0
    inputs_complete = 1 if candidate.get("model_input_complete") else 0
    return (
        1 if settlement.live_eligible else 0,
        admitted,
        inputs_complete,
        validated,
        marks,
        abs_residual,
        int(candidate.get("candidate_id") or 0),
    )


def build_candidate_review_board(
    candidates: list[dict[str, Any]],
    *,
    scientific_decision_enabled: bool,
    max_trade_risk_eur: float | None = None,
    stop_loss_fraction: float | None = None,
) -> list[dict[str, Any]]:
    ordered = sorted(candidates, key=_research_priority_key, reverse=True)
    board: list[dict[str, Any]] = []

    for rank, candidate in enumerate(ordered, start=1):
        settlement = classify_settlement(
            candidate.get("underlying"),
            observed_exercise_style=candidate.get("exercise_style"),
        )
        risk = build_risk_plan(
            candidate,
            max_trade_risk_eur=max_trade_risk_eur,
            stop_loss_fraction=stop_loss_fraction,
        )
        blockers: list[str] = []

        if not scientific_decision_enabled:
            blockers.append("SCIENTIFIC_DECISION_GOVERNANCE_DISABLED")
        if not settlement.live_eligible:
            blockers.append(settlement.state)
        if candidate.get("admission_decision") != "ADMITTED":
            blockers.append("NOT_ADMITTED_TO_SHADOW_TRACKING")
        if not candidate.get("model_input_complete"):
            blockers.append("MODEL_INPUTS_INCOMPLETE")
        if not risk.passes_risk_budget:
            blockers.append(risk.state)

        board.append(
            {
                **candidate,
                "research_rank": rank,
                "settlement_state": settlement.state,
                "settlement_type": settlement.settlement_type,
                "exercise_style_policy": settlement.exercise_style,
                "physical_delivery_risk": "NONE" if settlement.live_eligible else "BLOCKING / UNVERIFIED",
                "risk_plan_state": risk.state,
                "planned_loss_trigger_eur": risk.planned_loss_trigger_eur,
                "bankroll_fraction": risk.bankroll_fraction,
                "decision_blockers": blockers,
                "decision_blocker_count": len(blockers),
                "decision_desk_disposition": (
                    "ELIGIBLE FOR MANUAL TRADE REVIEW"
                    if not blockers
                    else "NO TRADE"
                ),
            }
        )

    return board


def _parse_expiration_tte(expiration: Any, surfaced_at: Any) -> float | None:
    if not expiration or not surfaced_at:
        return None
    try:
        expiry = date.fromisoformat(str(expiration)[:10])
        surfaced = datetime.fromisoformat(str(surfaced_at).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None
    days = max((expiry - surfaced).days, 1)
    return days / 365.0


def _leg_option(leg: dict[str, Any], candidate: dict[str, Any]) -> VanillaOption:
    spot = _as_float(leg.get("model_underlying_price"))
    if spot is None:
        spot = _as_float(candidate.get("underlying_price"))
    strike = _as_float(leg.get("strike"))
    volatility = _as_float(leg.get("implied_volatility"))
    if volatility is None:
        volatility = _as_float(leg.get("provider_implied_volatility"))
    rate = _as_float(leg.get("model_rate"))
    dividend = _as_float(leg.get("model_dividend_yield"))
    tte = _parse_expiration_tte(candidate.get("expiration"), candidate.get("surfaced_at"))

    if None in (spot, strike, volatility, rate, dividend, tte):
        raise QuantInputError(
            "Candidate model inputs are incomplete; Christiania will not invent spot, IV, rate, dividend yield, or time-to-expiry inputs."
        )

    return VanillaOption(
        spot=float(spot),
        strike=float(strike),
        time_to_expiry=float(tte),
        rate=float(rate),
        volatility=float(volatility),
        right="CALL" if str(leg.get("right")).upper() in {"C", "CALL"} else "PUT",
        dividend_yield=float(dividend),
    )


def run_candidate_model_dossier(
    candidate: dict[str, Any],
    *,
    mc_paths: int = 10_000,
) -> dict[str, Any]:
    legs = list(candidate.get("structure_legs") or [])
    if not legs:
        return {
            "state": "MODEL_INPUTS_INCOMPLETE",
            "reason": "Candidate has no persisted structure legs.",
            "leg_results": [],
            "structure_models": [],
        }

    leg_results: list[dict[str, Any]] = []
    aggregate_prices: dict[str, float] = {}
    aggregate_greeks: dict[str, float] = {}
    market_entry_per_share = 0.0
    multipliers: set[float] = set()

    for leg in legs:
        try:
            option = _leg_option(leg, candidate)
        except QuantInputError as exc:
            return {
                "state": "MODEL_INPUTS_INCOMPLETE",
                "reason": str(exc),
                "leg_results": leg_results,
                "structure_models": [],
            }

        market_price = _as_float(leg.get("entry_price"))
        result = run_vanilla_bench(
            option,
            market_price=market_price,
            mc_paths=mc_paths,
            tree_steps=300,
        ).as_dict()
        sign = 1.0 if str(leg.get("side")).upper() == "BUY" else -1.0
        quantity = abs(int(leg.get("quantity") or 1))
        multiplier = _as_float(leg.get("shares_per_contract")) or 1.0
        multipliers.add(multiplier)

        if market_price is not None:
            market_entry_per_share += sign * quantity * market_price

        for model, price in result["model_prices"].items():
            aggregate_prices[model] = aggregate_prices.get(model, 0.0) + sign * quantity * float(price)

        for greek, value in result["greeks"].items():
            aggregate_greeks[greek] = aggregate_greeks.get(greek, 0.0) + sign * quantity * float(value) * multiplier

        leg_results.append(
            {
                "option_quote_id": leg.get("option_quote_id"),
                "side": leg.get("side"),
                "quantity": quantity,
                "strike": leg.get("strike"),
                "right": leg.get("right"),
                "entry_price": market_price,
                "implied_volatility": option.volatility,
                "spot": option.spot,
                "time_to_expiry": option.time_to_expiry,
                "model_prices": result["model_prices"],
                "greeks": result["greeks"],
            }
        )

    if len(multipliers) != 1:
        return {
            "state": "MODEL_INPUTS_CONFLICT",
            "reason": "Structure legs have inconsistent contract multipliers.",
            "leg_results": leg_results,
            "structure_models": [],
        }

    multiplier = multipliers.pop()
    model_values = list(aggregate_prices.values())
    consensus = mean(model_values) if model_values else None
    model_range = (max(model_values) - min(model_values)) if model_values else None
    market_minus_consensus = None if consensus is None else market_entry_per_share - consensus

    structure_models = [
        {
            "model": model,
            "fair_value_per_share": value,
            "fair_value_per_contract": value * multiplier,
            "market_entry_per_share": market_entry_per_share,
            "model_minus_entry_per_contract": (value - market_entry_per_share) * multiplier,
        }
        for model, value in aggregate_prices.items()
    ]

    return {
        "state": "RESEARCH_ONLY",
        "reason": (
            "Full model suite evaluated the persisted structure using stored candidate inputs. "
            "This is model disagreement evidence, not calibrated expected value or a trade signal."
        ),
        "leg_results": leg_results,
        "structure_models": structure_models,
        "structure_greeks_per_contract": aggregate_greeks,
        "market_entry_per_share": market_entry_per_share,
        "contract_multiplier": multiplier,
        "consensus_fair_value_per_share": consensus,
        "model_range_per_share": model_range,
        "market_minus_consensus_per_share": market_minus_consensus,
        "expected_value_state": "NOT_CALIBRATED_FOR_DECISION_USE",
        "time_to_expiry_note": "Date-based TTE approximation from surfaced date to expiration date; exact settlement timestamp is not inferred.",
        "governance": {
            "state": "RESEARCH_ONLY",
            "decision_enabled": False,
            "admission_enabled": False,
        },
    }

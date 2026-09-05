from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from statistics import median
from typing import Any

from src.decision.evidence import assess_prospective_evidence
from src.decision.governance import resolve_candidate_governance
from src.decision.market_quality import assess_market_quality
from src.decision.scenarios import run_structure_scenarios
from src.quant.bench import run_vanilla_bench
from src.quant.types import QuantInputError, VanillaOption
from src.research.settlement_policy import classify_settlement

BANKROLL_CAP_EUR = 500.0
BENCHMARK_MODELS = (
    "BLACK_SCHOLES_MERTON",
    "CRR_BINOMIAL",
    "CRANK_NICOLSON_BSM",
    "MONTE_CARLO_GBM",
)
STRESS_MODELS = ("HESTON", "MERTON_JUMP_DIFFUSION")


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
        and max_trade_risk_eur <= BANKROLL_CAP_EUR
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
            note="Set an explicit per-trade loss budget (no more than the €500 active bankroll) and a monitoring loss fraction. A threshold is not a guaranteed fill.",
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
        note="Defined-risk maximum loss remains the primary protection. The planned loss threshold is a manual monitoring threshold, not a guaranteed execution price; option prices can gap through it.",
    )


def resolve_time_to_expiry(candidate: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    exact = candidate.get("expiration_at")
    if exact:
        try:
            expiry = datetime.fromisoformat(str(exact).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            seconds = max((expiry.astimezone(UTC) - now.astimezone(UTC)).total_seconds(), 0.0)
            return {"state": "EXACT_TIMESTAMP", "time_to_expiry": seconds / (365.0 * 24.0 * 3600.0), "decision_eligible": True, "note": "Exact persisted expiration timestamp used."}
        except ValueError:
            pass
    expiration = candidate.get("expiration")
    surfaced_at = candidate.get("surfaced_at")
    if not expiration or not surfaced_at:
        return {"state": "UNAVAILABLE", "time_to_expiry": None, "decision_eligible": False, "note": "Expiration time cannot be resolved."}
    try:
        expiry_date = date.fromisoformat(str(expiration)[:10])
        surfaced = datetime.fromisoformat(str(surfaced_at).replace("Z", "+00:00")).date()
    except ValueError:
        return {"state": "UNAVAILABLE", "time_to_expiry": None, "decision_eligible": False, "note": "Expiration time cannot be resolved."}
    days = max((expiry_date - surfaced).days, 1)
    return {
        "state": "DATE_APPROXIMATION_ONLY",
        "time_to_expiry": days / 365.0,
        "decision_eligible": False,
        "note": "Date-only TTE approximation is allowed for research diagnostics but is not acceptable for live/manual decision use, especially near expiry.",
    }


def _leg_option(leg: dict[str, Any], candidate: dict[str, Any], tte: float) -> VanillaOption:
    spot = _as_float(leg.get("model_underlying_price")) or _as_float(candidate.get("underlying_price"))
    strike = _as_float(leg.get("strike"))
    volatility = _as_float(leg.get("implied_volatility"))
    if volatility is None:
        volatility = _as_float(leg.get("provider_implied_volatility"))
    rate = _as_float(leg.get("model_rate"))
    dividend = _as_float(leg.get("model_dividend_yield"))
    if None in (spot, strike, volatility, rate, dividend):
        raise QuantInputError("Candidate model inputs are incomplete; Christiania will not invent spot, IV, rate, dividend yield, or strike inputs.")
    return VanillaOption(
        spot=float(spot), strike=float(strike), time_to_expiry=float(tte), rate=float(rate),
        volatility=float(volatility), right="CALL" if str(leg.get("right")).upper() in {"C", "CALL"} else "PUT",
        dividend_yield=float(dividend),
    )


def run_candidate_model_dossier(candidate: dict[str, Any], *, mc_paths: int = 10_000) -> dict[str, Any]:
    legs = list(candidate.get("structure_legs") or [])
    if not legs:
        return {"state": "MODEL_INPUTS_INCOMPLETE", "reason": "Candidate has no persisted structure legs.", "leg_results": [], "structure_models": []}
    tte = resolve_time_to_expiry(candidate)
    if tte["time_to_expiry"] is None:
        return {"state": "MODEL_INPUTS_INCOMPLETE", "reason": tte["note"], "leg_results": [], "structure_models": []}

    leg_results: list[dict[str, Any]] = []
    aggregate_prices: dict[str, float] = {}
    aggregate_greeks: dict[str, float] = {}
    market_entry_per_share = 0.0
    multipliers: set[float] = set()
    for leg in legs:
        try:
            option = _leg_option(leg, candidate, float(tte["time_to_expiry"]))
        except QuantInputError as exc:
            return {"state": "MODEL_INPUTS_INCOMPLETE", "reason": str(exc), "leg_results": leg_results, "structure_models": []}
        market_price = _as_float(leg.get("entry_price"))
        result = run_vanilla_bench(option, market_price=market_price, mc_paths=mc_paths, tree_steps=300).as_dict()
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
        leg_results.append({
            "option_quote_id": leg.get("option_quote_id"), "side": leg.get("side"), "quantity": quantity,
            "strike": leg.get("strike"), "right": leg.get("right"), "entry_price": market_price,
            "implied_volatility": option.volatility, "spot": option.spot, "time_to_expiry": option.time_to_expiry,
            "model_prices": result["model_prices"], "greeks": result["greeks"],
        })
    if len(multipliers) != 1:
        return {"state": "MODEL_INPUTS_CONFLICT", "reason": "Structure legs have inconsistent contract multipliers.", "leg_results": leg_results, "structure_models": []}

    multiplier = multipliers.pop()
    structure_models = []
    for model, value in aggregate_prices.items():
        role = "STRESS_MODEL" if model in STRESS_MODELS else ("BENCHMARK_DIAGNOSTIC" if model in BENCHMARK_MODELS else "OTHER_RESEARCH_MODEL")
        structure_models.append({
            "model": model, "role": role, "fair_value_per_share": value, "fair_value_per_contract": value * multiplier,
            "market_entry_per_share": market_entry_per_share, "model_minus_entry_per_contract": (value - market_entry_per_share) * multiplier,
        })
    benchmark_values = [aggregate_prices[name] for name in BENCHMARK_MODELS if name in aggregate_prices]
    stress_values = [aggregate_prices[name] for name in STRESS_MODELS if name in aggregate_prices]
    benchmark_center = median(benchmark_values) if benchmark_values else None
    benchmark_range = (max(benchmark_values) - min(benchmark_values)) if benchmark_values else None
    stress_range = (min(stress_values), max(stress_values)) if stress_values else (None, None)
    scenarios = run_structure_scenarios(candidate, current_tte=float(tte["time_to_expiry"]))

    return {
        "state": "RESEARCH_ONLY",
        "reason": "Pricing models are separated into benchmark diagnostics and uncalibrated stress models. No model vote or average can create trade permission.",
        "leg_results": leg_results,
        "structure_models": structure_models,
        "structure_greeks_per_contract": aggregate_greeks,
        "market_entry_per_share": market_entry_per_share,
        "contract_multiplier": multiplier,
        "benchmark_center_per_share": benchmark_center,
        "benchmark_range_per_share": benchmark_range,
        "stress_min_per_share": stress_range[0],
        "stress_max_per_share": stress_range[1],
        "expected_value_state": "NOT_CALIBRATED_FOR_DECISION_USE",
        "time_to_expiry": tte,
        "scenarios": scenarios,
        "governance": {"state": "RESEARCH_ONLY", "decision_enabled": False, "admission_enabled": False},
    }


def assess_exit_monitor(candidate: dict[str, Any], risk: RiskPlan) -> dict[str, Any]:
    pnl_minor = candidate.get("latest_estimated_net_pnl_eur_minor")
    latest_pnl = None if pnl_minor is None else float(pnl_minor) / 100.0
    breached = bool(
        latest_pnl is not None
        and risk.planned_loss_trigger_eur is not None
        and latest_pnl <= -abs(risk.planned_loss_trigger_eur)
    )
    return {
        "loss_threshold_state": "BREACHED" if breached else ("MONITORING" if risk.planned_loss_trigger_eur is not None else "NOT_CONFIGURED"),
        "latest_net_pnl_eur": latest_pnl,
        "planned_loss_trigger_eur": risk.planned_loss_trigger_eur,
        "thesis_exit_state": "NOT_AUTOMATICALLY_SCORED",
        "time_exit_state": "EXACT_EXPIRATION_TIMESTAMP_REQUIRED",
        "note": "This monitor never submits an exit. It only compares persisted shadow marks with the configured monitoring threshold.",
    }


def _research_priority_key(candidate: dict[str, Any]) -> tuple:
    validated = int(candidate.get("validated_outcomes") or 0)
    marks = int(candidate.get("mark_count") or 0)
    abs_residual = abs(_as_float(candidate.get("abs_iv_residual")) or 0.0)
    admitted = 1 if candidate.get("admission_decision") == "ADMITTED" else 0
    inputs_complete = 1 if candidate.get("model_input_complete") else 0
    return (admitted, inputs_complete, validated, marks, abs_residual, int(candidate.get("candidate_id") or 0))


def build_candidate_review_board(
    candidates: list[dict[str, Any]],
    *,
    models: list[dict[str, Any]] | None = None,
    hypotheses: list[dict[str, Any]] | None = None,
    scientific_decision_enabled: bool | None = None,
    max_trade_risk_eur: float | None = None,
    stop_loss_fraction: float | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    # scientific_decision_enabled remains accepted for backwards compatibility.
    # False may add a conservative blocker; True can never grant permission.
    legacy_global_disabled = scientific_decision_enabled is False
    models = models or []
    hypotheses = hypotheses or []
    ordered = sorted(candidates, key=_research_priority_key, reverse=True)
    board: list[dict[str, Any]] = []
    for rank, candidate in enumerate(ordered, start=1):
        settlement = classify_settlement(
            candidate.get("underlying"), observed_exercise_style=candidate.get("exercise_style"),
            reference_contract_id=candidate.get("reference_contract_id"), shares_per_contract=candidate.get("target_shares_per_contract"),
        )
        risk = build_risk_plan(candidate, max_trade_risk_eur=max_trade_risk_eur, stop_loss_fraction=stop_loss_fraction)
        governance = resolve_candidate_governance(candidate, models=models, hypotheses=hypotheses)
        market = assess_market_quality(candidate, now=now)
        evidence = assess_prospective_evidence(candidate)
        tte = resolve_time_to_expiry(candidate, now=now)

        hard_blockers: list[str] = []
        shadow_blockers: list[str] = []
        warnings: list[str] = list(market.warnings)
        if not settlement.live_eligible:
            hard_blockers.append(settlement.state)
        if candidate.get("admission_decision") != "ADMITTED":
            hard_blockers.append("NOT_ADMITTED_TO_SHADOW_TRACKING")
        if not candidate.get("model_input_complete"):
            shadow_blockers.append("MODEL_INPUTS_INCOMPLETE")
        if not risk.passes_risk_budget:
            hard_blockers.append(risk.state)
        if market.blockers:
            shadow_blockers.extend(market.blockers)
        if legacy_global_disabled:
            shadow_blockers.append("SCIENTIFIC_DECISION_GOVERNANCE_DISABLED")
        if not governance.decision_enabled:
            shadow_blockers.extend(governance.blockers or ("CANDIDATE_GOVERNANCE_DISABLED",))
        if not tte["decision_eligible"]:
            shadow_blockers.append("EXACT_EXPIRATION_TIMESTAMP_UNAVAILABLE")
        # Event/jump calendar integration is deliberately missing in V1 and must fail closed for manual eligibility.
        shadow_blockers.append("EVENT_RISK_CONTEXT_NOT_INTEGRATED")
        # Prospective evidence can inform review but never auto-enables decisions.
        shadow_blockers.append("CALIBRATED_NET_EV_NOT_AVAILABLE")

        all_blockers = list(dict.fromkeys(hard_blockers + shadow_blockers))
        if hard_blockers:
            disposition = "NO TRADE"
            research_action = "CONTINUE SHADOW" if candidate.get("admission_decision") == "ADMITTED" else "REJECT"
        elif shadow_blockers:
            disposition = "CONTINUE SHADOW"
            research_action = "CONTINUE SHADOW"
        else:
            disposition = "ELIGIBLE FOR MANUAL TRADE REVIEW"
            research_action = "MANUAL REVIEW"

        board.append({
            **candidate,
            "research_rank": rank,
            "settlement_state": settlement.state,
            "settlement_type": settlement.settlement_type,
            "contract_identity_state": settlement.contract_identity_state,
            "multiplier_state": settlement.multiplier_state,
            "risk_plan_state": risk.state,
            "planned_loss_trigger_eur": risk.planned_loss_trigger_eur,
            "bankroll_fraction": risk.bankroll_fraction,
            "candidate_governance_state": "ENABLED" if governance.decision_enabled else "DISABLED",
            "market_quality_state": market.state,
            "quote_age_seconds": market.quote_age_seconds,
            "spread_to_mid": market.spread_to_mid,
            "prospective_evidence_state": evidence.state,
            "time_to_expiry_state": tte["state"],
            "decision_blockers": all_blockers,
            "decision_blocker_count": len(all_blockers),
            "decision_warnings": warnings,
            "decision_desk_disposition": disposition,
            "research_action": research_action,
            "primary_research_model": governance.primary_model,
        })
    return board

"""Thesis-first selection contract shared across option structure families.

The strategy is an expression of a *precommitted thesis*, never the thesis.
This is a pure, read-only Stage-1 research gate. No orders, admissions or
production claims are emitted. A favorable hypothetical payoff is NOT edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from src.research.strategy_falsification_v1 import (
    Feasibility, QuoteCostPolicy, Structure, dec, evaluate, utc,
)

VERSION = "THESIS_FIRST_EVIDENCE_GATE_V1"
MIN_PROSPECTIVE_DATES = 10
THESIS_FAMILIES = frozenset({
    "DIRECTIONAL_UP", "DIRECTIONAL_DOWN", "LONG_VOLATILITY",
    "SHORT_VOLATILITY", "LOCAL_IV_CONVERGENCE",
})
EXPIRY_EXIT = "HOLD_TO_EXPIRY"
NO_TRADE = "NO_TRADE"
SHADOW_ONLY = "SHADOW_RESEARCH_ONLY_NOT_TRADING_AUTHORITY"


@dataclass(frozen=True)
class TerminalScenario:
    """Ex-ante forecast state, never generated from observed expiry outcomes."""
    terminal_spot: Decimal
    probability: Decimal


@dataclass(frozen=True)
class FrozenThesis:
    thesis_id: str
    family: str
    frozen_at: str
    underlying: str
    expiration: str
    forecast_model_version: str | None
    forecast_source: str | None
    training_cutoff: str | None
    exit_rule: str | None
    scenarios: tuple[TerminalScenario, ...] = ()
    prospective_independent_dates: int = 0
    matched_placebo_ci_lower_usd: Decimal | None = None


@dataclass(frozen=True)
class SelectionDecision:
    strategy_id: str
    thesis_id: str | None
    state: str
    proof_level: str
    blockers: tuple[str, ...]
    feasibility: Feasibility
    hypothetical_net_ev_usd: Decimal | None
    modeled_gross_max_loss_usd: Decimal | None
    authority: str = "NONE"

    @property
    def eligible_for_live_trading(self) -> bool:
        return False


def _strict_probability_distribution(
    scenarios: Sequence[TerminalScenario],
) -> bool:
    if not scenarios or len(scenarios) > 100:
        return False
    try:
        values = [(dec(s.terminal_spot), dec(s.probability)) for s in scenarios]
        return (
            all(spot > 0 and probability > 0 for spot, probability in values)
            and abs(sum((prob for _, prob in values), Decimal(0)) - 1)
            <= Decimal("0.000001")
        )
    except (TypeError, ValueError):
        return False


def _modeled_expiry_ev(
    structure: Structure, policy: QuoteCostPolicy,
    scenarios: Sequence[TerminalScenario],
) -> Decimal:
    """Full terminal *intrinsic* payoff with entry-side crossing and assumed fees.

    This deliberately cannot evaluate a volatility-convergence early exit.
    """
    entry = Decimal(0)
    fee = Decimal(0)
    for leg in structure.legs:
        if leg.kind not in {"CALL", "PUT"}:
            raise ValueError("OPTION_ONLY_MODEL")
        if leg.bid is None or leg.ask is None or leg.strike is None:
            raise ValueError("ENTRY_QUOTE_OR_STRIKE_UNAVAILABLE")
        amount = leg.ask if leg.side == "BUY" else leg.bid
        signed = Decimal(-1 if leg.side == "BUY" else 1)
        entry += signed * leg.quantity * leg.multiplier * amount
        fee += dec(policy.option_cost_per_contract_side_usd) * leg.quantity * 2
    fee += dec(policy.additional_round_trip_cost_usd)
    fee += dec(policy.tax_cost_usd)
    result = Decimal(0)
    for scenario in scenarios:
        terminal = Decimal(0)
        for leg in structure.legs:
            intrinsic = (
                max(scenario.terminal_spot - leg.strike, Decimal(0))
                if leg.kind == "CALL"
                else max(leg.strike - scenario.terminal_spot, Decimal(0))
            )
            terminal += intrinsic * leg.quantity * leg.multiplier * (
                1 if leg.side == "BUY" else -1
            )
        result += scenario.probability * (entry + terminal - fee)
    return result


def evaluate_candidate(
    structure: Structure,
    policy: QuoteCostPolicy,
    thesis: FrozenThesis | None,
    *, underlying: str, expiration: str,
) -> SelectionDecision:
    """Identical gate for all seven option-only structures and risk namespaces.

    A valid thesis and empirical control authorize a *shadow comparison only*.
    Neither retrospective distributions nor theoretical edge authorize trading.
    """
    feasibility = evaluate(structure, policy)
    reasons: list[str] = list(feasibility.reasons)
    if feasibility.state != "INDICATIVELY_AFFORDABLE_NOT_EXECUTABLE":
        reasons.append("PACKAGE_FEASIBILITY_NOT_FULLY_EVIDENCED")
    if thesis is None:
        reasons.append("NO_PRECOMMITTED_PREDICTIVE_THESIS")
    else:
        try:
            decision_at = utc(structure.decision_at)
            frozen_at = utc(thesis.frozen_at)
            expiry_at = datetime.fromisoformat(expiration).date()
            if frozen_at > decision_at:
                reasons.append("THESIS_FROZEN_AFTER_ENTRY_DECISION")
            if thesis.training_cutoff is None:
                reasons.append("FORECAST_TRAINING_CUTOFF_NOT_EVIDENCED")
            elif utc(thesis.training_cutoff) > frozen_at:
                reasons.append("FORECAST_TRAINING_LEAKAGE")
            if thesis.expiration != expiration or thesis.underlying != underlying:
                reasons.append("THESIS_CONTRACT_IDENTITY_MISMATCH")
            if thesis.family not in THESIS_FAMILIES:
                reasons.append("UNRECOGNIZED_PREDICTIVE_THESIS")
            # A single ex-ante terminal price distribution is evaluated against
            # EVERY strategy payoff. Never require a separate model merely
            # because the payoff shape is a spread rather than a straddle.
            # Early-exit convergence still needs a path-specific payoff model.
            if expiry_at < decision_at.date():
                reasons.append("CANDIDATE_EXPIRED_BEFORE_ASOF")
        except (ValueError, TypeError):
            reasons.append("THESIS_TIME_OR_IDENTITY_INVALID")
        if not thesis.forecast_model_version or not thesis.forecast_source:
            reasons.append("INDEPENDENT_FORECAST_PROVENANCE_MISSING")
        if not thesis.exit_rule:
            reasons.append("EXIT_RULE_NOT_PRECOMMITTED")
        elif thesis.exit_rule != EXPIRY_EXIT:
            reasons.append("EXIT_PATH_PAYOFF_MODEL_NOT_AVAILABLE")
        if not _strict_probability_distribution(thesis.scenarios):
            reasons.append("VALID_FORECAST_DISTRIBUTION_MISSING")
        if thesis.prospective_independent_dates < MIN_PROSPECTIVE_DATES:
            reasons.append("INSUFFICIENT_INDEPENDENT_PROSPECTIVE_DATES")
        if (thesis.matched_placebo_ci_lower_usd is None
                or dec(thesis.matched_placebo_ci_lower_usd) <= 0):
            reasons.append("POSITIVE_MATCHED_CONTROL_EXCESS_NOT_ESTABLISHED")

    ev: Decimal | None = None
    if (
        thesis is not None and thesis.exit_rule == EXPIRY_EXIT
        and _strict_probability_distribution(thesis.scenarios)
        and feasibility.state == "INDICATIVELY_AFFORDABLE_NOT_EXECUTABLE"
    ):
        try:
            ev = _modeled_expiry_ev(structure, policy, thesis.scenarios)
        except (ValueError, TypeError):
            reasons.append("TERMINAL_PAYOFF_NOT_RECONSTRUCTIBLE")
    if ev is None:
        reasons.append("NET_EXPECTANCY_NOT_ESTABLISHED")
    elif ev <= 0:
        reasons.append("NON_POSITIVE_MODELED_NET_EXPECTANCY")

    risk = (
        None if feasibility.gross_max_loss_usd is None
        else dec(feasibility.gross_max_loss_usd)
    )
    blockers = tuple(sorted(set(reasons)))
    return SelectionDecision(
        strategy_id=structure.strategy_id,
        thesis_id=None if thesis is None else thesis.thesis_id,
        state=SHADOW_ONLY if not blockers else NO_TRADE,
        proof_level=(
            "PRECOMMITTED_MODEL_AND_CONTROL_SHADOW_ONLY"
            if not blockers else "INSUFFICIENT_OR_UNVERIFIED_EVIDENCE"
        ),
        blockers=blockers,
        feasibility=feasibility,
        hypothetical_net_ev_usd=ev,
        modeled_gross_max_loss_usd=risk,
    )

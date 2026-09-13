from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Sequence

import numpy as np

from src.quant.risk import OptionLeg
from src.quant.types import QuantInputError


RISK_SELECTION_VERSION = "1.0.0"


@dataclass(frozen=True)
class DistributionAssumptions:
    annual_drift: float
    annual_volatility: float
    jump_intensity: float = 0.0
    jump_mean: float = 0.0
    jump_volatility: float = 0.0

    def validate(self) -> None:
        values = (
            self.annual_drift,
            self.annual_volatility,
            self.jump_intensity,
            self.jump_mean,
            self.jump_volatility,
        )
        if any(not math.isfinite(value) for value in values):
            raise QuantInputError("distribution assumptions must be finite")
        if self.annual_volatility < 0:
            raise QuantInputError("annual_volatility cannot be negative")
        if self.jump_intensity < 0:
            raise QuantInputError("jump_intensity cannot be negative")
        if self.jump_volatility < 0:
            raise QuantInputError("jump_volatility cannot be negative")


@dataclass(frozen=True)
class RiskBudget:
    bankroll: float
    max_loss_fraction: float

    def validate(self) -> None:
        if not math.isfinite(self.bankroll) or self.bankroll <= 0:
            raise QuantInputError("bankroll must be finite and positive")
        if not math.isfinite(self.max_loss_fraction) or not 0 < self.max_loss_fraction <= 1:
            raise QuantInputError("max_loss_fraction must be in (0, 1]")


@dataclass(frozen=True)
class RiskSelectionResult:
    version: str
    structure_defined_risk: bool
    entry_debit: float
    total_costs: float
    max_loss: float | None
    max_profit: float | None
    expected_pnl: float
    median_pnl: float
    pnl_standard_deviation: float
    probability_of_profit: float
    probability_of_loss: float
    probability_of_bankroll_ruin: float | None
    loss_var_95: float
    loss_cvar_95: float
    pnl_p05: float
    pnl_p25: float
    pnl_p50: float
    pnl_p75: float
    pnl_p95: float
    expected_pnl_to_max_loss: float | None
    expected_pnl_to_cvar95: float | None
    max_loss_bankroll_fraction: float | None
    risk_budget_amount: float | None
    max_contracts_at_budget: int | None
    budget_state: str
    decision_authority: str
    assumptions: DistributionAssumptions

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["assumptions"] = asdict(self.assumptions)
        return payload


def _terminal_payoff(legs: Sequence[OptionLeg], terminal: np.ndarray) -> np.ndarray:
    payoff = np.zeros_like(terminal, dtype=float)
    for leg in legs:
        leg.validate()
        if leg.right.upper() == "CALL":
            intrinsic = np.maximum(terminal - leg.strike, 0.0)
        else:
            intrinsic = np.maximum(leg.strike - terminal, 0.0)
        payoff += leg.quantity * intrinsic
    return payoff


def payoff_bounds(
    legs: Sequence[OptionLeg],
    *,
    total_costs: float = 0.0,
) -> tuple[float, float | None, float | None, bool]:
    if not legs:
        raise QuantInputError("structure requires at least one leg")
    if not math.isfinite(total_costs) or total_costs < 0:
        raise QuantInputError("total_costs must be finite and non-negative")
    for leg in legs:
        leg.validate()

    entry_debit = float(sum(leg.quantity * leg.entry_premium for leg in legs))
    strikes = sorted({float(leg.strike) for leg in legs})
    candidates = np.asarray([0.0, *strikes], dtype=float)
    pnl = _terminal_payoff(legs, candidates) - entry_debit - total_costs

    net_call_slope = sum(leg.quantity for leg in legs if leg.right.upper() == "CALL")
    defined_risk = net_call_slope >= 0
    max_loss = max(0.0, -float(np.min(pnl))) if defined_risk else None
    max_profit = None if net_call_slope > 0 else max(0.0, float(np.max(pnl)))
    return entry_debit, max_loss, max_profit, defined_risk


def simulate_terminal_prices(
    *,
    spot: float,
    time_to_expiry: float,
    assumptions: DistributionAssumptions,
    simulation_paths: int,
    seed: int,
) -> np.ndarray:
    assumptions.validate()
    if not math.isfinite(spot) or spot <= 0:
        raise QuantInputError("spot must be finite and positive")
    if not math.isfinite(time_to_expiry) or time_to_expiry < 0:
        raise QuantInputError("time_to_expiry must be finite and non-negative")
    if simulation_paths < 10_000:
        raise QuantInputError("simulation_paths must be >= 10000")

    if time_to_expiry == 0:
        return np.full(simulation_paths, spot, dtype=float)

    rng = np.random.default_rng(seed)
    diffusion_z = rng.standard_normal(simulation_paths)
    diffusion = (
        (assumptions.annual_drift - 0.5 * assumptions.annual_volatility**2) * time_to_expiry
        + assumptions.annual_volatility * math.sqrt(time_to_expiry) * diffusion_z
    )

    jump_component = np.zeros(simulation_paths, dtype=float)
    if assumptions.jump_intensity > 0:
        jump_counts = rng.poisson(assumptions.jump_intensity * time_to_expiry, simulation_paths)
        jump_z = rng.standard_normal(simulation_paths)
        jump_component = (
            jump_counts * assumptions.jump_mean
            + np.sqrt(jump_counts) * assumptions.jump_volatility * jump_z
        )

    return spot * np.exp(diffusion + jump_component)


def evaluate_structure_distribution(
    legs: Sequence[OptionLeg],
    *,
    spot: float,
    time_to_expiry: float,
    assumptions: DistributionAssumptions,
    transaction_costs: float = 0.0,
    slippage: float = 0.0,
    risk_budget: RiskBudget | None = None,
    simulation_paths: int = 100_000,
    seed: int = 4242,
) -> RiskSelectionResult:
    if not math.isfinite(transaction_costs) or transaction_costs < 0:
        raise QuantInputError("transaction_costs must be finite and non-negative")
    if not math.isfinite(slippage) or slippage < 0:
        raise QuantInputError("slippage must be finite and non-negative")
    if risk_budget is not None:
        risk_budget.validate()

    total_costs = float(transaction_costs + slippage)
    entry_debit, max_loss, max_profit, defined_risk = payoff_bounds(
        legs,
        total_costs=total_costs,
    )
    terminal = simulate_terminal_prices(
        spot=spot,
        time_to_expiry=time_to_expiry,
        assumptions=assumptions,
        simulation_paths=simulation_paths,
        seed=seed,
    )
    pnl = _terminal_payoff(legs, terminal) - entry_debit - total_costs

    losses = -pnl
    loss_var_95 = float(np.quantile(losses, 0.95))
    tail = losses[losses >= loss_var_95]
    loss_cvar_95 = float(np.mean(tail)) if len(tail) else loss_var_95
    expected_pnl = float(np.mean(pnl))

    bankroll_ruin_probability: float | None = None
    max_loss_bankroll_fraction: float | None = None
    risk_budget_amount: float | None = None
    max_contracts_at_budget: int | None = None
    budget_state = "NO_RISK_BUDGET"

    if risk_budget is not None:
        risk_budget_amount = float(risk_budget.bankroll * risk_budget.max_loss_fraction)
        bankroll_ruin_probability = float(np.mean(pnl <= -risk_budget.bankroll))
        if max_loss is None:
            budget_state = "REJECT_UNBOUNDED_LOSS"
        elif max_loss == 0:
            max_loss_bankroll_fraction = 0.0
            max_contracts_at_budget = 0
            budget_state = "NO_CAPITAL_AT_RISK"
        else:
            max_loss_bankroll_fraction = float(max_loss / risk_budget.bankroll)
            max_contracts_at_budget = max(0, int(math.floor(risk_budget_amount / max_loss)))
            budget_state = (
                "WITHIN_BOUNDED_RISK_BUDGET"
                if max_loss <= risk_budget_amount
                else "EXCEEDS_SINGLE_STRUCTURE_RISK_BUDGET"
            )

    expected_to_max_loss = None
    if max_loss is not None and max_loss > 0:
        expected_to_max_loss = float(expected_pnl / max_loss)
    expected_to_cvar = None
    if loss_cvar_95 > 0:
        expected_to_cvar = float(expected_pnl / loss_cvar_95)

    quantiles = np.quantile(pnl, [0.05, 0.25, 0.50, 0.75, 0.95])
    return RiskSelectionResult(
        version=RISK_SELECTION_VERSION,
        structure_defined_risk=defined_risk,
        entry_debit=entry_debit,
        total_costs=total_costs,
        max_loss=max_loss,
        max_profit=max_profit,
        expected_pnl=expected_pnl,
        median_pnl=float(np.median(pnl)),
        pnl_standard_deviation=float(np.std(pnl, ddof=1)),
        probability_of_profit=float(np.mean(pnl > 0)),
        probability_of_loss=float(np.mean(pnl < 0)),
        probability_of_bankroll_ruin=bankroll_ruin_probability,
        loss_var_95=loss_var_95,
        loss_cvar_95=loss_cvar_95,
        pnl_p05=float(quantiles[0]),
        pnl_p25=float(quantiles[1]),
        pnl_p50=float(quantiles[2]),
        pnl_p75=float(quantiles[3]),
        pnl_p95=float(quantiles[4]),
        expected_pnl_to_max_loss=expected_to_max_loss,
        expected_pnl_to_cvar95=expected_to_cvar,
        max_loss_bankroll_fraction=max_loss_bankroll_fraction,
        risk_budget_amount=risk_budget_amount,
        max_contracts_at_budget=max_contracts_at_budget,
        budget_state=budget_state,
        decision_authority="NONE_RESEARCH_ONLY",
        assumptions=assumptions,
    )

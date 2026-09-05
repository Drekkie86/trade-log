from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Sequence

import numpy as np

from src.quant.black_scholes import price as bsm_price
from src.quant.types import QuantInputError, VanillaOption


@dataclass(frozen=True)
class OptionLeg:
    right: str
    strike: float
    quantity: int
    entry_premium: float

    def validate(self) -> None:
        if self.right.upper() not in {"CALL", "PUT"}:
            raise QuantInputError("leg right must be CALL or PUT")
        if self.strike <= 0:
            raise QuantInputError("leg strike must be positive")
        if self.quantity == 0:
            raise QuantInputError("leg quantity cannot be zero")
        if self.entry_premium < 0:
            raise QuantInputError("entry_premium cannot be negative")


@dataclass(frozen=True)
class StructureRisk:
    entry_debit: float
    theoretical_value: float
    pricing_measure_ev_before_costs: float
    pricing_measure_ev_after_costs: float
    max_loss: float | None
    max_profit: float | None
    defined_risk: bool
    risk_neutral_probability_of_profit: float | None
    var_95: float | None
    cvar_95: float | None

    def as_dict(self) -> dict:
        return asdict(self)


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


def _payoff_extrema(legs: Sequence[OptionLeg], entry_debit: float, costs: float) -> tuple[float | None, float | None, bool]:
    strikes = sorted({leg.strike for leg in legs})
    candidates = [0.0, *strikes]
    pnl_values = []
    for s in candidates:
        payoff = float(_terminal_payoff(legs, np.array([s]))[0])
        pnl_values.append(payoff - entry_debit - costs)

    call_slope = sum(
        leg.quantity
        for leg in legs
        if leg.right.upper() == "CALL"
    )
    max_loss: float | None
    max_profit: float | None
    defined_risk = call_slope >= 0
    if call_slope < 0:
        max_loss = None
    else:
        max_loss = max(0.0, -min(pnl_values))

    if call_slope > 0:
        max_profit = None
    else:
        max_profit = max(0.0, max(pnl_values))
    return max_loss, max_profit, defined_risk


def evaluate_lognormal(
    legs: Sequence[OptionLeg],
    *,
    spot: float,
    time_to_expiry: float,
    rate: float,
    volatility: float,
    dividend_yield: float = 0.0,
    transaction_costs: float = 0.0,
    slippage: float = 0.0,
    simulation_paths: int = 100_000,
    seed: int = 4242,
) -> StructureRisk:
    if not legs:
        raise QuantInputError("structure requires at least one leg")
    if spot <= 0 or time_to_expiry < 0 or volatility < 0:
        raise QuantInputError("invalid market state")
    if transaction_costs < 0 or slippage < 0:
        raise QuantInputError("costs/slippage cannot be negative")
    if simulation_paths < 10_000:
        raise QuantInputError("simulation_paths must be >=10000")
    for leg in legs:
        leg.validate()

    entry_debit = float(sum(leg.quantity * leg.entry_premium for leg in legs))
    theoretical_value = 0.0
    for leg in legs:
        theoretical_value += leg.quantity * bsm_price(
            VanillaOption(
                spot=spot,
                strike=leg.strike,
                time_to_expiry=time_to_expiry,
                rate=rate,
                volatility=volatility,
                right=leg.right,
                dividend_yield=dividend_yield,
            )
        )
    expected_before = theoretical_value - entry_debit
    total_costs = transaction_costs + slippage
    expected_after = expected_before - total_costs
    max_loss, max_profit, defined_risk = _payoff_extrema(legs, entry_debit, total_costs)

    if time_to_expiry == 0:
        terminal = np.full(simulation_paths, spot)
    else:
        rng = np.random.default_rng(seed)
        z = rng.standard_normal(simulation_paths)
        terminal = spot * np.exp(
            (rate - dividend_yield - 0.5 * volatility**2) * time_to_expiry
            + volatility * math.sqrt(time_to_expiry) * z
        )
    pnl = _terminal_payoff(legs, terminal) - entry_debit - total_costs
    pop = float(np.mean(pnl > 0.0))
    losses = -pnl
    var95 = float(np.quantile(losses, 0.95))
    tail = losses[losses >= var95]
    cvar95 = float(np.mean(tail)) if len(tail) else var95

    return StructureRisk(
        entry_debit=entry_debit,
        theoretical_value=float(theoretical_value),
        pricing_measure_ev_before_costs=float(expected_before),
        pricing_measure_ev_after_costs=float(expected_after),
        max_loss=max_loss,
        max_profit=max_profit,
        defined_risk=defined_risk,
        risk_neutral_probability_of_profit=pop,
        var_95=var95,
        cvar_95=cvar95,
    )

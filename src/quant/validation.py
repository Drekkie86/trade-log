from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from src.quant import black_scholes, greeks, monte_carlo, trees
from src.quant.types import VanillaOption


@dataclass(frozen=True)
class ValidationReport:
    put_call_parity_residual: float
    tree_absolute_error: float
    monte_carlo_absolute_error: float
    monte_carlo_within_95_ci: bool
    delta_absolute_error: float
    gamma_absolute_error: float
    vega_absolute_error: float
    theta_absolute_error: float
    rho_absolute_error: float
    passed: bool

    def as_dict(self) -> dict:
        return asdict(self)


def validate_vanilla_kernel(
    option: VanillaOption,
    *,
    tree_steps: int = 1000,
    mc_paths: int = 200_000,
    seed: int = 777,
    price_tolerance: float = 0.02,
    greek_tolerance: float = 2e-3,
) -> ValidationReport:
    option.validate()
    call = VanillaOption(
        spot=option.spot,
        strike=option.strike,
        time_to_expiry=option.time_to_expiry,
        rate=option.rate,
        volatility=option.volatility,
        right="CALL",
        dividend_yield=option.dividend_yield,
    )
    put = VanillaOption(
        spot=option.spot,
        strike=option.strike,
        time_to_expiry=option.time_to_expiry,
        rate=option.rate,
        volatility=option.volatility,
        right="PUT",
        dividend_yield=option.dividend_yield,
    )
    call_price = black_scholes.price(call)
    put_price = black_scholes.price(put)
    parity_target = (
        option.spot * math.exp(-option.dividend_yield * option.time_to_expiry)
        - option.strike * math.exp(-option.rate * option.time_to_expiry)
    )
    parity_residual = call_price - put_price - parity_target

    reference = black_scholes.price(option)
    tree = trees.crr_price(option, steps=tree_steps)
    mc = monte_carlo.price(option, paths=mc_paths, seed=seed)

    analytic_g = greeks.analytic(option)
    numerical_g = greeks.numerical(option)
    errors = {
        name: abs(getattr(analytic_g, name) - numerical_g[name])
        for name in ("delta", "gamma", "vega", "theta", "rho")
    }
    passed = (
        abs(parity_residual) <= 1e-10
        and abs(tree - reference) <= price_tolerance
        and mc.confidence_low_95 - price_tolerance <= reference <= mc.confidence_high_95 + price_tolerance
        and max(errors.values()) <= greek_tolerance
    )
    return ValidationReport(
        put_call_parity_residual=float(parity_residual),
        tree_absolute_error=float(abs(tree - reference)),
        monte_carlo_absolute_error=float(abs(mc.price - reference)),
        monte_carlo_within_95_ci=bool(mc.confidence_low_95 <= reference <= mc.confidence_high_95),
        delta_absolute_error=float(errors["delta"]),
        gamma_absolute_error=float(errors["gamma"]),
        vega_absolute_error=float(errors["vega"]),
        theta_absolute_error=float(errors["theta"]),
        rho_absolute_error=float(errors["rho"]),
        passed=bool(passed),
    )

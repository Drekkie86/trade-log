from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from scipy.optimize import brentq

from src.quant.black_scholes import no_arbitrage_bounds, price
from src.quant.types import QuantInputError, VanillaOption


@dataclass(frozen=True)
class ImpliedVolResult:
    state: str
    volatility: float | None
    iterations: int | None
    lower_bound: float
    upper_bound: float
    pricing_error: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def solve(
    market_price: float,
    option: VanillaOption,
    *,
    min_vol: float = 1e-8,
    max_vol: float = 5.0,
    hard_max_vol: float = 10.0,
    price_tolerance: float = 1e-9,
) -> ImpliedVolResult:
    option.validate()
    if market_price < 0.0 or not math.isfinite(market_price):
        raise QuantInputError("market_price must be finite and non-negative")
    low_bound, high_bound = no_arbitrage_bounds(option)
    tol = max(price_tolerance, 1e-12)
    if market_price < low_bound - tol or market_price > high_bound + tol:
        return ImpliedVolResult(
            state="NO_ARBITRAGE_VIOLATION",
            volatility=None,
            iterations=None,
            lower_bound=low_bound,
            upper_bound=high_bound,
            pricing_error=None,
        )
    if option.time_to_expiry == 0.0:
        return ImpliedVolResult(
            state="EXPIRED",
            volatility=None,
            iterations=None,
            lower_bound=low_bound,
            upper_bound=high_bound,
            pricing_error=market_price - low_bound,
        )
    if abs(market_price - low_bound) <= tol:
        return ImpliedVolResult(
            state="AT_LOWER_BOUND",
            volatility=0.0,
            iterations=0,
            lower_bound=low_bound,
            upper_bound=high_bound,
            pricing_error=market_price - low_bound,
        )

    def objective(vol: float) -> float:
        candidate = VanillaOption(
            spot=option.spot,
            strike=option.strike,
            time_to_expiry=option.time_to_expiry,
            rate=option.rate,
            volatility=vol,
            right=option.right,
            dividend_yield=option.dividend_yield,
        )
        return price(candidate) - market_price

    upper = max_vol
    while objective(upper) < 0.0 and upper < hard_max_vol:
        upper = min(hard_max_vol, upper * 1.5)

    if objective(upper) < 0.0:
        return ImpliedVolResult(
            state="ABOVE_SOLVER_RANGE",
            volatility=None,
            iterations=None,
            lower_bound=low_bound,
            upper_bound=high_bound,
            pricing_error=objective(upper),
        )

    root, result = brentq(
        objective,
        min_vol,
        upper,
        xtol=1e-12,
        rtol=1e-12,
        full_output=True,
        disp=False,
    )
    return ImpliedVolResult(
        state="SOLVED",
        volatility=float(root),
        iterations=int(result.iterations),
        lower_bound=low_bound,
        upper_bound=high_bound,
        pricing_error=float(objective(root)),
    )

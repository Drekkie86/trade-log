from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import numpy as np

from src.quant.black_scholes import price as bsm_price
from src.quant.types import QuantInputError, VanillaOption


@dataclass(frozen=True)
class MonteCarloResult:
    price: float
    standard_error: float
    confidence_low_95: float
    confidence_high_95: float
    paths: int
    seed: int
    antithetic: bool
    control_variate: bool

    def as_dict(self) -> dict:
        return asdict(self)


def price(
    option: VanillaOption,
    *,
    paths: int = 100_000,
    seed: int = 1729,
    antithetic: bool = True,
    control_variate: bool = True,
) -> MonteCarloResult:
    option.validate()
    if paths < 1_000:
        raise QuantInputError("paths must be >= 1000")
    if option.time_to_expiry == 0.0:
        exact = bsm_price(option)
        return MonteCarloResult(exact, 0.0, exact, exact, paths, seed, antithetic, control_variate)

    rng = np.random.default_rng(seed)
    if antithetic:
        half = (paths + 1) // 2
        z = rng.standard_normal(half)
        z = np.concatenate([z, -z])[:paths]
    else:
        z = rng.standard_normal(paths)

    t = option.time_to_expiry
    sigma = option.volatility
    terminal = option.spot * np.exp(
        (option.rate - option.dividend_yield - 0.5 * sigma * sigma) * t
        + sigma * math.sqrt(t) * z
    )
    if option.normalized_right() == "CALL":
        payoff = np.maximum(terminal - option.strike, 0.0)
    else:
        payoff = np.maximum(option.strike - terminal, 0.0)

    disc = math.exp(-option.rate * t)
    discounted = disc * payoff

    if control_variate:
        control = disc * terminal
        expected_control = option.spot * math.exp(-option.dividend_yield * t)
        variance = float(np.var(control, ddof=1))
        if variance > 0.0:
            covariance = float(np.cov(discounted, control, ddof=1)[0, 1])
            beta = covariance / variance
            discounted = discounted - beta * (control - expected_control)

    estimate = float(np.mean(discounted))
    stderr = float(np.std(discounted, ddof=1) / math.sqrt(paths))
    return MonteCarloResult(
        price=estimate,
        standard_error=stderr,
        confidence_low_95=estimate - 1.96 * stderr,
        confidence_high_95=estimate + 1.96 * stderr,
        paths=paths,
        seed=seed,
        antithetic=antithetic,
        control_variate=control_variate,
    )

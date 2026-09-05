from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from scipy.stats import norm, poisson

from src.quant.types import QuantInputError, VanillaOption


@dataclass(frozen=True)
class MertonJumpParameters:
    jump_intensity: float
    jump_mean: float
    jump_volatility: float

    def validate(self) -> None:
        if self.jump_intensity < 0:
            raise QuantInputError("jump_intensity cannot be negative")
        if self.jump_volatility < 0:
            raise QuantInputError("jump_volatility cannot be negative")

    def as_dict(self) -> dict:
        return asdict(self)


def price(
    option: VanillaOption,
    params: MertonJumpParameters,
    *,
    tail_probability: float = 1e-12,
    max_terms: int = 500,
) -> float:
    option.validate()
    params.validate()
    if not 0 < tail_probability < 1:
        raise QuantInputError("tail_probability must be between 0 and 1")
    if max_terms < 1:
        raise QuantInputError("max_terms must be positive")
    t = option.time_to_expiry
    if t == 0:
        if option.normalized_right() == "CALL":
            return max(option.spot - option.strike, 0.0)
        return max(option.strike - option.spot, 0.0)

    lam_t = params.jump_intensity * t
    compensator = math.exp(
        params.jump_mean + 0.5 * params.jump_volatility**2
    ) - 1.0

    if lam_t == 0.0:
        n_max = 0
    else:
        quantile = poisson.ppf(1.0 - tail_probability, lam_t)
        n_max = int(min(max_terms - 1, max(0, math.ceil(float(quantile)))))

    total = 0.0
    call = option.normalized_right() == "CALL"
    for n in range(n_max + 1):
        weight = math.exp(-lam_t) * (lam_t**n) / math.factorial(n)
        variance = option.volatility**2 * t + n * params.jump_volatility**2
        mean_log = (
            math.log(option.spot)
            + (
                option.rate
                - option.dividend_yield
                - params.jump_intensity * compensator
                - 0.5 * option.volatility**2
            )
            * t
            + n * params.jump_mean
        )
        if variance <= 1e-18:
            terminal = math.exp(mean_log)
            payoff = (
                max(terminal - option.strike, 0.0)
                if call
                else max(option.strike - terminal, 0.0)
            )
            conditional = math.exp(-option.rate * t) * payoff
        else:
            std = math.sqrt(variance)
            d2 = (mean_log - math.log(option.strike)) / std
            d1 = d2 + std
            expected_terminal_positive = math.exp(mean_log + 0.5 * variance)
            if call:
                conditional = math.exp(-option.rate * t) * (
                    expected_terminal_positive * norm.cdf(d1)
                    - option.strike * norm.cdf(d2)
                )
            else:
                conditional = math.exp(-option.rate * t) * (
                    option.strike * norm.cdf(-d2)
                    - expected_terminal_positive * norm.cdf(-d1)
                )
        total += weight * conditional

    return float(total)

from __future__ import annotations

import math

from src.quant.types import QuantInputError, VanillaOption


def crr_price(
    option: VanillaOption,
    *,
    steps: int = 500,
    american: bool = False,
) -> float:
    option.validate()
    if steps < 1:
        raise QuantInputError("steps must be >= 1")
    t = option.time_to_expiry
    if t == 0.0:
        if option.normalized_right() == "CALL":
            return max(option.spot - option.strike, 0.0)
        return max(option.strike - option.spot, 0.0)
    if option.volatility == 0.0:
        terminal = option.spot * math.exp(
            (option.rate - option.dividend_yield) * t
        )
        payoff = (
            max(terminal - option.strike, 0.0)
            if option.normalized_right() == "CALL"
            else max(option.strike - terminal, 0.0)
        )
        return math.exp(-option.rate * t) * payoff

    dt = t / steps
    u = math.exp(option.volatility * math.sqrt(dt))
    d = 1.0 / u
    growth = math.exp((option.rate - option.dividend_yield) * dt)
    p = (growth - d) / (u - d)
    if not 0.0 <= p <= 1.0:
        raise QuantInputError(
            "CRR risk-neutral probability outside [0,1]; increase steps or inspect inputs"
        )
    disc = math.exp(-option.rate * dt)
    call = option.normalized_right() == "CALL"

    values = []
    spots = []
    for j in range(steps + 1):
        s = option.spot * (u ** j) * (d ** (steps - j))
        spots.append(s)
        values.append(
            max(s - option.strike, 0.0)
            if call
            else max(option.strike - s, 0.0)
        )

    for i in range(steps - 1, -1, -1):
        next_values = []
        for j in range(i + 1):
            continuation = disc * (
                p * values[j + 1] + (1.0 - p) * values[j]
            )
            if american:
                s = option.spot * (u ** j) * (d ** (i - j))
                exercise = (
                    max(s - option.strike, 0.0)
                    if call
                    else max(option.strike - s, 0.0)
                )
                next_values.append(max(continuation, exercise))
            else:
                next_values.append(continuation)
        values = next_values

    return float(values[0])

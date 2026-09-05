from __future__ import annotations

import math

import numpy as np
from scipy.linalg import solve_banded

from src.quant.types import QuantInputError, VanillaOption


def crank_nicolson_price(
    option: VanillaOption,
    *,
    spot_steps: int = 400,
    time_steps: int = 400,
    spot_max_multiple: float = 4.0,
) -> float:
    """Price a European vanilla under the BSM PDE using Crank-Nicolson.

    This is a cross-validation engine, not the primary production pricer.
    """
    option.validate()
    if spot_steps < 40 or time_steps < 40:
        raise QuantInputError("finite-difference grid requires >=40 spot/time steps")
    if spot_max_multiple <= 1.2:
        raise QuantInputError("spot_max_multiple must exceed 1.2")
    if option.time_to_expiry == 0.0:
        if option.normalized_right() == "CALL":
            return max(option.spot - option.strike, 0.0)
        return max(option.strike - option.spot, 0.0)

    s_max = max(
        option.spot * spot_max_multiple,
        option.strike * spot_max_multiple,
    )
    m = int(spot_steps)
    n = int(time_steps)
    ds = s_max / m
    dt = option.time_to_expiry / n
    grid_s = np.linspace(0.0, s_max, m + 1)
    call = option.normalized_right() == "CALL"
    values = (
        np.maximum(grid_s - option.strike, 0.0)
        if call
        else np.maximum(option.strike - grid_s, 0.0)
    )

    j = np.arange(1, m, dtype=float)
    sigma2j2 = option.volatility**2 * j**2
    driftj = (option.rate - option.dividend_yield) * j

    # Operator L coefficients on interior nodes.
    a = 0.5 * (sigma2j2 - driftj)
    b = -(sigma2j2 + option.rate)
    c = 0.5 * (sigma2j2 + driftj)

    # (I - .5 dt L) V^new = (I + .5 dt L) V^old
    lower_l = -0.5 * dt * a
    diag_l = 1.0 - 0.5 * dt * b
    upper_l = -0.5 * dt * c
    lower_r = 0.5 * dt * a
    diag_r = 1.0 + 0.5 * dt * b
    upper_r = 0.5 * dt * c

    banded = np.zeros((3, m - 1))
    banded[0, 1:] = upper_l[:-1]
    banded[1, :] = diag_l
    banded[2, :-1] = lower_l[1:]

    for step in range(n):
        tau_old = step * dt
        tau_new = (step + 1) * dt
        if call:
            low_old = 0.0
            low_new = 0.0
            high_old = (
                s_max * math.exp(-option.dividend_yield * tau_old)
                - option.strike * math.exp(-option.rate * tau_old)
            )
            high_new = (
                s_max * math.exp(-option.dividend_yield * tau_new)
                - option.strike * math.exp(-option.rate * tau_new)
            )
        else:
            low_old = option.strike * math.exp(-option.rate * tau_old)
            low_new = option.strike * math.exp(-option.rate * tau_new)
            high_old = 0.0
            high_new = 0.0

        interior = values[1:m]
        rhs = diag_r * interior
        rhs[1:] += lower_r[1:] * interior[:-1]
        rhs[:-1] += upper_r[:-1] * interior[1:]

        # Boundary contributions from both CN halves.
        rhs[0] += lower_r[0] * low_old - lower_l[0] * low_new
        rhs[-1] += upper_r[-1] * high_old - upper_l[-1] * high_new

        solved = solve_banded((1, 1), banded, rhs)
        values[0] = low_new
        values[m] = high_new
        values[1:m] = solved

    return float(np.interp(option.spot, grid_s, values))

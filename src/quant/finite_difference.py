from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import numpy as np
from scipy.linalg import solve_banded

from src.quant.types import QuantInputError, VanillaOption


@dataclass(frozen=True)
class FiniteDifferenceConvergence:
    price: float
    converged: bool
    state: str
    initial_spot_max_multiple: float
    final_spot_max_multiple: float
    base_spot_steps: int
    final_spot_steps: int
    final_time_steps: int
    domain_refinements: int
    domain_shift: float | None
    resolution_shift: float | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _validate_grid(
    *,
    spot_steps: int,
    time_steps: int,
    spot_max_multiple: float,
    max_domain_refinements: int,
) -> None:
    if spot_steps < 40 or time_steps < 40:
        raise QuantInputError("finite-difference grid requires >=40 spot/time steps")
    if not math.isfinite(float(spot_max_multiple)) or spot_max_multiple <= 1.2:
        raise QuantInputError("spot_max_multiple must be finite and exceed 1.2")
    if max_domain_refinements < 1:
        raise QuantInputError("max_domain_refinements must be positive")


def _crank_nicolson_on_grid(
    option: VanillaOption,
    *,
    spot_steps: int,
    time_steps: int,
    spot_max_multiple: float,
) -> float:
    """Solve the BSM PDE on one explicit finite computational domain."""
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

    result = float(np.interp(option.spot, grid_s, values))
    if not math.isfinite(result) or result < 0:
        raise QuantInputError("finite-difference solver produced an invalid price")
    return result


def crank_nicolson_diagnostic(
    option: VanillaOption,
    *,
    spot_steps: int = 400,
    time_steps: int = 400,
    spot_max_multiple: float = 4.0,
    max_domain_refinements: int = 5,
) -> FiniteDifferenceConvergence:
    """Price with an explicit numerical-adequacy check for domain truncation.

    The BSM PDE itself is unchanged. The computational domain is doubled while
    the original spatial step size is preserved. At each widened domain, the
    same domain is also solved at twice the spatial and temporal resolution.
    Domain truncation is considered resolved only when the price sensitivity to
    another domain widening is no larger than the observed grid-resolution
    sensitivity. This uses the solver's own numerical evidence rather than a
    volatility cutoff or a hand-picked pricing-error threshold.
    """
    option.validate()
    _validate_grid(
        spot_steps=spot_steps,
        time_steps=time_steps,
        spot_max_multiple=spot_max_multiple,
        max_domain_refinements=max_domain_refinements,
    )

    if option.time_to_expiry == 0.0:
        price = (
            max(option.spot - option.strike, 0.0)
            if option.normalized_right() == "CALL"
            else max(option.strike - option.spot, 0.0)
        )
        return FiniteDifferenceConvergence(
            price=float(price),
            converged=True,
            state="EXACT_EXPIRY_PAYOFF",
            initial_spot_max_multiple=float(spot_max_multiple),
            final_spot_max_multiple=float(spot_max_multiple),
            base_spot_steps=int(spot_steps),
            final_spot_steps=int(spot_steps),
            final_time_steps=int(time_steps),
            domain_refinements=0,
            domain_shift=0.0,
            resolution_shift=0.0,
        )

    previous = _crank_nicolson_on_grid(
        option,
        spot_steps=spot_steps,
        time_steps=time_steps,
        spot_max_multiple=spot_max_multiple,
    )
    last_refined = previous
    last_domain_shift: float | None = None
    last_resolution_shift: float | None = None
    last_multiple = float(spot_max_multiple)
    last_spot_steps = int(spot_steps)
    last_time_steps = int(time_steps)

    for refinement in range(1, max_domain_refinements + 1):
        scale = 2**refinement
        current_multiple = float(spot_max_multiple) * scale
        current_spot_steps = int(spot_steps) * scale

        # The domain widens while ds is held constant, isolating sensitivity to
        # the far-field truncation from ordinary spatial-grid refinement.
        current = _crank_nicolson_on_grid(
            option,
            spot_steps=current_spot_steps,
            time_steps=time_steps,
            spot_max_multiple=current_multiple,
        )

        # Independently estimate the numerical resolution scale on this same
        # domain by refining both spatial and temporal grids.
        refined = _crank_nicolson_on_grid(
            option,
            spot_steps=current_spot_steps * 2,
            time_steps=time_steps * 2,
            spot_max_multiple=current_multiple,
        )
        domain_shift = abs(current - previous)
        resolution_shift = abs(refined - current)
        roundoff_allowance = np.finfo(float).eps * max(1.0, abs(refined), abs(current))

        last_refined = refined
        last_domain_shift = domain_shift
        last_resolution_shift = resolution_shift
        last_multiple = current_multiple
        last_spot_steps = current_spot_steps * 2
        last_time_steps = int(time_steps) * 2

        if domain_shift <= resolution_shift + roundoff_allowance:
            return FiniteDifferenceConvergence(
                price=float(refined),
                converged=True,
                state="CONVERGED_DOMAIN_AND_RESOLUTION",
                initial_spot_max_multiple=float(spot_max_multiple),
                final_spot_max_multiple=current_multiple,
                base_spot_steps=int(spot_steps),
                final_spot_steps=current_spot_steps * 2,
                final_time_steps=int(time_steps) * 2,
                domain_refinements=refinement,
                domain_shift=float(domain_shift),
                resolution_shift=float(resolution_shift),
            )

        previous = current

    return FiniteDifferenceConvergence(
        price=float(last_refined),
        converged=False,
        state="DOMAIN_CONVERGENCE_NOT_DEMONSTRATED",
        initial_spot_max_multiple=float(spot_max_multiple),
        final_spot_max_multiple=last_multiple,
        base_spot_steps=int(spot_steps),
        final_spot_steps=last_spot_steps,
        final_time_steps=last_time_steps,
        domain_refinements=max_domain_refinements,
        domain_shift=last_domain_shift,
        resolution_shift=last_resolution_shift,
    )


def crank_nicolson_price(
    option: VanillaOption,
    *,
    spot_steps: int = 400,
    time_steps: int = 400,
    spot_max_multiple: float = 4.0,
    max_domain_refinements: int = 5,
) -> float:
    """Price a European vanilla under the BSM PDE using Crank-Nicolson.

    This cross-validation engine fails closed unless its own domain-truncation
    check demonstrates that widening the far-field boundary no longer matters
    more than ordinary grid-resolution error.
    """
    result = crank_nicolson_diagnostic(
        option,
        spot_steps=spot_steps,
        time_steps=time_steps,
        spot_max_multiple=spot_max_multiple,
        max_domain_refinements=max_domain_refinements,
    )
    if not result.converged:
        raise QuantInputError(
            "Crank-Nicolson domain convergence was not demonstrated within the configured refinement budget"
        )
    return result.price

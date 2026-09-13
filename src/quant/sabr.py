from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Sequence

import numpy as np

from src.quant.black_scholes import price as bsm_price
from src.quant.surface import diagnose_call_slice
from src.quant.types import QuantInputError, VanillaOption


@dataclass(frozen=True)
class SABRParameters:
    alpha: float
    beta: float
    rho: float
    nu: float

    def validate(self) -> None:
        if self.alpha <= 0:
            raise QuantInputError("SABR alpha must be positive")
        if not 0 <= self.beta <= 1:
            raise QuantInputError("SABR beta must be in [0,1]")
        if not -1 < self.rho < 1:
            raise QuantInputError("SABR rho must be strictly between -1 and 1")
        if self.nu < 0:
            raise QuantInputError("SABR nu cannot be negative")

    def as_dict(self) -> dict:
        return asdict(self)


def hagan_lognormal_iv(
    forward: float,
    strike: float,
    time_to_expiry: float,
    params: SABRParameters,
) -> float:
    """Return Hagan's lognormal SABR implied-volatility approximation.

    This is a pointwise approximation. A finite IV at one strike does *not*
    establish that a complete smile is free of butterfly arbitrage. Callers
    that intend to use a SABR smile downstream must run
    :func:`sampled_static_arbitrage` or :func:`checked_smile` across the
    relevant strike domain first.
    """
    params.validate()
    if forward <= 0 or strike <= 0:
        raise QuantInputError("forward and strike must be positive")
    if time_to_expiry < 0:
        raise QuantInputError("time_to_expiry cannot be negative")

    alpha, beta, rho, nu = params.alpha, params.beta, params.rho, params.nu
    one_minus_beta = 1.0 - beta
    fk = forward * strike

    if abs(forward - strike) <= 1e-12 * max(forward, strike):
        f_pow = forward ** one_minus_beta
        correction = (
            (one_minus_beta**2 / 24.0) * alpha**2 / (f_pow**2)
            + 0.25 * rho * beta * nu * alpha / f_pow
            + (2.0 - 3.0 * rho**2) * nu**2 / 24.0
        )
        result = alpha / f_pow * (1.0 + correction * time_to_expiry)
    else:
        log_fk = math.log(forward / strike)
        fk_pow = fk ** (0.5 * one_minus_beta)
        denominator = fk_pow * (
            1.0
            + (one_minus_beta**2 / 24.0) * log_fk**2
            + (one_minus_beta**4 / 1920.0) * log_fk**4
        )
        z = (nu / alpha) * fk_pow * log_fk if nu > 0 else 0.0
        if abs(z) < 1e-10:
            z_over_x = 1.0
        else:
            x_z = math.log(
                (math.sqrt(1.0 - 2.0 * rho * z + z * z) + z - rho)
                / (1.0 - rho)
            )
            z_over_x = z / x_z

        correction = (
            (one_minus_beta**2 / 24.0) * alpha**2 / (fk_pow**2)
            + 0.25 * rho * beta * nu * alpha / fk_pow
            + (2.0 - 3.0 * rho**2) * nu**2 / 24.0
        )
        result = alpha / denominator * z_over_x * (1.0 + correction * time_to_expiry)

    if not math.isfinite(result) or result <= 0:
        raise QuantInputError("Hagan SABR approximation produced non-positive/non-finite IV")
    return float(result)


def sampled_static_arbitrage(
    forward: float,
    time_to_expiry: float,
    params: SABRParameters,
    *,
    strike_min: float | None = None,
    strike_max: float | None = None,
    points: int = 121,
    tolerance: float = 1e-8,
) -> dict[str, object]:
    """Check a sampled Hagan-SABR smile for static call-price arbitrage.

    SABR's Hagan approximation is not globally arbitrage free. This function
    converts the sampled IV smile to undiscounted Black-Scholes call prices
    (spot=forward, r=q=0) and checks bounds, monotonicity and convexity.
    """
    params.validate()
    if not math.isfinite(forward) or forward <= 0:
        raise QuantInputError("forward must be finite and positive")
    if not math.isfinite(time_to_expiry) or time_to_expiry <= 0:
        raise QuantInputError("time_to_expiry must be finite and positive")
    if points < 5:
        raise QuantInputError("points must be >=5")

    lo = float(strike_min if strike_min is not None else 0.5 * forward)
    hi = float(strike_max if strike_max is not None else 1.5 * forward)
    if not math.isfinite(lo) or not math.isfinite(hi) or lo <= 0 or lo >= hi:
        raise QuantInputError("invalid SABR diagnostic strike range")

    strikes = np.linspace(lo, hi, points)
    ivs = np.asarray(
        [hagan_lognormal_iv(forward, float(k), time_to_expiry, params) for k in strikes],
        dtype=float,
    )
    calls = np.asarray(
        [
            bsm_price(
                VanillaOption(
                    spot=forward,
                    strike=float(k),
                    time_to_expiry=time_to_expiry,
                    rate=0.0,
                    volatility=float(iv),
                    right="CALL",
                    dividend_yield=0.0,
                )
            )
            for k, iv in zip(strikes, ivs)
        ],
        dtype=float,
    )
    call_diag = diagnose_call_slice(
        forward,
        strikes,
        calls,
        time_to_expiry=time_to_expiry,
        rate=0.0,
        tolerance=tolerance,
    )
    static_arbitrage = any(int(value) > 0 for value in call_diag.values())
    return {
        **call_diag,
        "sampled_static_arbitrage": bool(static_arbitrage),
        "minimum_iv": float(np.min(ivs)),
        "maximum_iv": float(np.max(ivs)),
        "strike_min": lo,
        "strike_max": hi,
        "points": int(points),
    }


def checked_smile(
    forward: float,
    strikes: Sequence[float],
    time_to_expiry: float,
    params: SABRParameters,
    *,
    tolerance: float = 1e-8,
) -> np.ndarray:
    """Return SABR IVs only when the supplied strike slice passes static checks."""
    k = np.asarray(strikes, dtype=float)
    if len(k) < 3 or np.any(~np.isfinite(k)) or np.any(k <= 0):
        raise QuantInputError("checked SABR smile requires >=3 finite positive strikes")
    if np.any(np.diff(np.sort(k)) <= 0):
        raise QuantInputError("checked SABR smile strikes must be unique")

    ivs = np.asarray(
        [hagan_lognormal_iv(forward, float(strike), time_to_expiry, params) for strike in k],
        dtype=float,
    )
    calls = np.asarray(
        [
            bsm_price(
                VanillaOption(
                    spot=forward,
                    strike=float(strike),
                    time_to_expiry=time_to_expiry,
                    rate=0.0,
                    volatility=float(iv),
                    right="CALL",
                    dividend_yield=0.0,
                )
            )
            for strike, iv in zip(k, ivs)
        ],
        dtype=float,
    )
    diagnostics = diagnose_call_slice(
        forward,
        k,
        calls,
        time_to_expiry=time_to_expiry,
        rate=0.0,
        tolerance=tolerance,
    )
    if any(int(value) > 0 for value in diagnostics.values()):
        raise QuantInputError(
            "Hagan SABR smile fails sampled static-arbitrage checks: "
            f"{diagnostics}"
        )
    return ivs

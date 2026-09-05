from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Sequence

import numpy as np
from scipy.interpolate import PchipInterpolator

from src.quant.types import QuantInputError


@dataclass(frozen=True)
class SurfaceDiagnostics:
    call_monotonicity_violations: int
    call_convexity_violations: int
    call_bound_violations: int
    calendar_total_variance_violations: int

    @property
    def static_arbitrage_free_on_sampled_grid(self) -> bool:
        return (
            self.call_monotonicity_violations == 0
            and self.call_convexity_violations == 0
            and self.call_bound_violations == 0
            and self.calendar_total_variance_violations == 0
        )

    def as_dict(self) -> dict:
        result = asdict(self)
        result["static_arbitrage_free_on_sampled_grid"] = self.static_arbitrage_free_on_sampled_grid
        return result


class SmileSlice:
    def __init__(
        self,
        log_moneyness: Sequence[float],
        implied_volatility: Sequence[float],
        time_to_expiry: float,
    ) -> None:
        k = np.asarray(log_moneyness, dtype=float)
        iv = np.asarray(implied_volatility, dtype=float)
        if len(k) != len(iv) or len(k) < 3:
            raise QuantInputError("smile slice requires >=3 matched points")
        if time_to_expiry <= 0 or np.any(iv <= 0):
            raise QuantInputError("time and IV must be positive")
        order = np.argsort(k)
        k = k[order]
        iv = iv[order]
        if np.any(np.diff(k) <= 0):
            raise QuantInputError("log-moneyness points must be unique")
        self.log_moneyness = k
        self.implied_volatility = iv
        self.time_to_expiry = float(time_to_expiry)
        self._total_variance = iv * iv * self.time_to_expiry
        self._interpolator = PchipInterpolator(k, self._total_variance, extrapolate=False)

    def total_variance(self, k: float) -> float:
        value = self._interpolator(float(k))
        if np.isnan(value):
            raise QuantInputError("requested log-moneyness outside smile interpolation domain")
        return max(float(value), 0.0)

    def iv(self, k: float) -> float:
        return math.sqrt(self.total_variance(k) / self.time_to_expiry)


def diagnose_call_slice(
    spot: float,
    strikes: Sequence[float],
    call_prices: Sequence[float],
    *,
    time_to_expiry: float,
    rate: float,
    dividend_yield: float = 0.0,
    tolerance: float = 1e-8,
) -> dict[str, int]:
    k = np.asarray(strikes, dtype=float)
    c = np.asarray(call_prices, dtype=float)
    if len(k) != len(c) or len(k) < 3:
        raise QuantInputError("call slice requires >=3 matched strikes/prices")
    if spot <= 0 or time_to_expiry < 0 or np.any(k <= 0) or np.any(c < 0):
        raise QuantInputError("invalid call-slice inputs")
    order = np.argsort(k)
    k = k[order]
    c = c[order]
    if np.any(np.diff(k) <= 0):
        raise QuantInputError("strikes must be unique")

    monotonic = int(np.sum(np.diff(c) > tolerance))
    slopes = np.diff(c) / np.diff(k)
    convexity = int(np.sum(np.diff(slopes) < -tolerance))
    s_disc = spot * math.exp(-dividend_yield * time_to_expiry)
    lower = np.maximum(0.0, s_disc - k * math.exp(-rate * time_to_expiry))
    upper = np.full_like(k, s_disc)
    bounds = int(np.sum((c < lower - tolerance) | (c > upper + tolerance)))
    return {
        "call_monotonicity_violations": monotonic,
        "call_convexity_violations": convexity,
        "call_bound_violations": bounds,
    }


def diagnose_calendar_total_variance(
    expiries: Sequence[float],
    implied_volatilities: Sequence[float],
    *,
    tolerance: float = 1e-10,
) -> int:
    t = np.asarray(expiries, dtype=float)
    iv = np.asarray(implied_volatilities, dtype=float)
    if len(t) != len(iv) or len(t) < 2 or np.any(t <= 0) or np.any(iv <= 0):
        raise QuantInputError("calendar check requires >=2 positive matched expiry/IV points")
    order = np.argsort(t)
    w = (iv[order] ** 2) * t[order]
    return int(np.sum(np.diff(w) < -tolerance))

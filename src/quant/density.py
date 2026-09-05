from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Sequence

import numpy as np

from src.quant.types import QuantInputError


@dataclass(frozen=True)
class DensityPoint:
    strike: float
    density: float
    state: str

    def as_dict(self) -> dict:
        return asdict(self)


def breeden_litzenberger(
    strikes: Sequence[float],
    call_prices: Sequence[float],
    *,
    time_to_expiry: float,
    rate: float,
    negative_tolerance: float = 1e-8,
) -> list[DensityPoint]:
    k = np.asarray(strikes, dtype=float)
    c = np.asarray(call_prices, dtype=float)
    if len(k) != len(c) or len(k) < 5:
        raise QuantInputError("density extraction requires >=5 matched strikes/calls")
    if np.any(k <= 0) or np.any(c < 0) or time_to_expiry <= 0:
        raise QuantInputError("invalid density inputs")
    order = np.argsort(k)
    k = k[order]
    c = c[order]
    if np.any(np.diff(k) <= 0):
        raise QuantInputError("strikes must be unique")

    first = np.gradient(c, k, edge_order=2)
    second = np.gradient(first, k, edge_order=2)
    density = math.exp(rate * time_to_expiry) * second
    points: list[DensityPoint] = []
    for strike, value in zip(k[1:-1], density[1:-1]):
        value = float(value)
        if value < -negative_tolerance:
            points.append(DensityPoint(float(strike), value, "NEGATIVE_DENSITY"))
        else:
            points.append(DensityPoint(float(strike), max(value, 0.0), "VALID"))
    return points


def approximate_mass(points: Sequence[DensityPoint]) -> float:
    if len(points) < 2:
        raise QuantInputError("mass approximation requires >=2 density points")
    k = np.array([p.strike for p in points], dtype=float)
    f = np.array([max(p.density, 0.0) for p in points], dtype=float)
    return float(np.trapezoid(f, k))

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Sequence

import numpy as np

from src.quant.types import QuantInputError


@dataclass(frozen=True)
class LocalVolPoint:
    strike: float
    time_to_expiry: float
    local_variance: float | None
    local_volatility: float | None
    numerator: float
    denominator: float
    state: str

    def as_dict(self) -> dict:
        return asdict(self)


def dupire_from_call_grid(
    strikes: Sequence[float],
    expiries: Sequence[float],
    call_prices: Sequence[Sequence[float]],
    *,
    rate: float,
    dividend_yield: float = 0.0,
) -> list[LocalVolPoint]:
    k = np.asarray(strikes, dtype=float)
    t = np.asarray(expiries, dtype=float)
    c = np.asarray(call_prices, dtype=float)
    if len(k) < 3 or len(t) < 3 or c.shape != (len(t), len(k)):
        raise QuantInputError("Dupire grid requires >=3x3 matched expiry/strike call prices")
    if np.any(k <= 0) or np.any(t <= 0) or np.any(c < 0):
        raise QuantInputError("Dupire grid inputs must be positive/non-negative")
    if np.any(np.diff(k) <= 0) or np.any(np.diff(t) <= 0):
        raise QuantInputError("strikes and expiries must be strictly increasing")

    dcdt = np.gradient(c, t, axis=0, edge_order=2)
    dcdk = np.gradient(c, k, axis=1, edge_order=2)
    d2cdk2 = np.gradient(dcdk, k, axis=1, edge_order=2)

    points: list[LocalVolPoint] = []
    for i in range(1, len(t) - 1):
        for j in range(1, len(k) - 1):
            numerator = (
                dcdt[i, j]
                + (rate - dividend_yield) * k[j] * dcdk[i, j]
                + dividend_yield * c[i, j]
            )
            denominator = 0.5 * k[j] * k[j] * d2cdk2[i, j]
            if denominator <= 1e-12 or numerator <= 0 or not math.isfinite(float(numerator / denominator)):
                points.append(
                    LocalVolPoint(
                        strike=float(k[j]),
                        time_to_expiry=float(t[i]),
                        local_variance=None,
                        local_volatility=None,
                        numerator=float(numerator),
                        denominator=float(denominator),
                        state="NOT_IDENTIFIABLE",
                    )
                )
            else:
                variance = float(numerator / denominator)
                points.append(
                    LocalVolPoint(
                        strike=float(k[j]),
                        time_to_expiry=float(t[i]),
                        local_variance=variance,
                        local_volatility=math.sqrt(variance),
                        numerator=float(numerator),
                        denominator=float(denominator),
                        state="VALID",
                    )
                )
    return points

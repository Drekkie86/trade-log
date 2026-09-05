from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Mapping

import numpy as np

from src.quant.types import QuantInputError


@dataclass(frozen=True)
class ModelDisagreement:
    model_count: int
    minimum: float
    maximum: float
    mean: float
    median: float
    standard_deviation: float
    absolute_range: float
    relative_range_to_mean: float | None
    market_price: float | None
    market_minus_consensus: float | None
    market_z_score: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def summarize(
    model_prices: Mapping[str, float],
    *,
    market_price: float | None = None,
) -> ModelDisagreement:
    if len(model_prices) < 2:
        raise QuantInputError("model disagreement requires at least two models")
    values = np.asarray(list(model_prices.values()), dtype=float)
    if np.any(~np.isfinite(values)) or np.any(values < 0):
        raise QuantInputError("model prices must be finite and non-negative")
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    absolute_range = float(np.max(values) - np.min(values))
    relative = None if abs(mean) <= 1e-12 else absolute_range / abs(mean)
    market_minus = None
    z = None
    if market_price is not None:
        if market_price < 0 or not math.isfinite(market_price):
            raise QuantInputError("market_price must be finite and non-negative")
        market_minus = float(market_price - mean)
        if std > 1e-12:
            z = market_minus / std
    return ModelDisagreement(
        model_count=len(values),
        minimum=float(np.min(values)),
        maximum=float(np.max(values)),
        mean=mean,
        median=float(np.median(values)),
        standard_deviation=std,
        absolute_range=absolute_range,
        relative_range_to_mean=relative,
        market_price=market_price,
        market_minus_consensus=market_minus,
        market_z_score=z,
    )

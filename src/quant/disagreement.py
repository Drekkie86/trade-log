from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Mapping

import numpy as np

from src.quant.types import QuantInputError


DESCRIPTIVE_INTERPRETATION = "DESCRIPTIVE_HETEROGENEOUS_MODEL_DISPERSION"


@dataclass(frozen=True)
class ModelDisagreement:
    model_count: int
    minimum: float
    maximum: float
    mean: float
    median: float
    standard_deviation: float
    median_absolute_deviation: float
    absolute_range: float
    relative_range_to_mean: float | None
    most_distant_model_from_median: str
    most_distant_model_abs_deviation: float
    market_price: float | None
    market_minus_consensus: float | None
    market_minus_model_median: float | None
    market_distance_in_model_standard_deviations: float | None
    statistical_inference_valid: bool
    interpretation: str

    def as_dict(self) -> dict:
        return asdict(self)


def summarize(
    model_prices: Mapping[str, float],
    *,
    market_price: float | None = None,
) -> ModelDisagreement:
    """Summarize descriptive dispersion across heterogeneous pricing models.

    The model prices are deterministic outputs from models with different
    structural assumptions. Their cross-model standard deviation is therefore
    a *descriptive dispersion scale*, not a sampling standard deviation. Any
    market distance expressed in those units must not be interpreted as a
    statistical z-score, p-value, confidence level, or probability.
    """
    if len(model_prices) < 2:
        raise QuantInputError("model disagreement requires at least two models")

    model_names = list(model_prices.keys())
    values = np.asarray(list(model_prices.values()), dtype=float)
    if np.any(~np.isfinite(values)) or np.any(values < 0):
        raise QuantInputError("model prices must be finite and non-negative")

    mean = float(np.mean(values))
    median = float(np.median(values))
    std = float(np.std(values, ddof=1))
    deviations_from_median = np.abs(values - median)
    median_absolute_deviation = float(np.median(deviations_from_median))
    farthest_index = int(np.argmax(deviations_from_median))
    absolute_range = float(np.max(values) - np.min(values))
    relative = None if abs(mean) <= 1e-12 else absolute_range / abs(mean)

    market_minus_mean = None
    market_minus_median = None
    market_distance_in_model_stddevs = None
    if market_price is not None:
        if market_price < 0 or not math.isfinite(market_price):
            raise QuantInputError("market_price must be finite and non-negative")
        market_minus_mean = float(market_price - mean)
        market_minus_median = float(market_price - median)
        if std > 1e-12:
            market_distance_in_model_stddevs = market_minus_mean / std

    return ModelDisagreement(
        model_count=len(values),
        minimum=float(np.min(values)),
        maximum=float(np.max(values)),
        mean=mean,
        median=median,
        standard_deviation=std,
        median_absolute_deviation=median_absolute_deviation,
        absolute_range=absolute_range,
        relative_range_to_mean=relative,
        most_distant_model_from_median=model_names[farthest_index],
        most_distant_model_abs_deviation=float(deviations_from_median[farthest_index]),
        market_price=market_price,
        market_minus_consensus=market_minus_mean,
        market_minus_model_median=market_minus_median,
        market_distance_in_model_standard_deviations=market_distance_in_model_stddevs,
        statistical_inference_valid=False,
        interpretation=DESCRIPTIVE_INTERPRETATION,
    )

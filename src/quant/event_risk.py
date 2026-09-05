from __future__ import annotations

import math

from src.quant.types import QuantInputError


def total_variance(implied_volatility: float, time_to_expiry: float) -> float:
    if implied_volatility < 0 or time_to_expiry < 0:
        raise QuantInputError("IV and time cannot be negative")
    return implied_volatility * implied_volatility * time_to_expiry


def implied_event_variance(
    event_expiry_iv: float,
    event_expiry_time: float,
    baseline_variance_rate: float,
) -> dict[str, float]:
    if baseline_variance_rate < 0:
        raise QuantInputError("baseline_variance_rate cannot be negative")
    observed = total_variance(event_expiry_iv, event_expiry_time)
    baseline = baseline_variance_rate * event_expiry_time
    event_var = max(observed - baseline, 0.0)
    return {
        "observed_total_variance": observed,
        "baseline_total_variance": baseline,
        "event_variance": event_var,
        "event_standard_deviation": math.sqrt(event_var),
    }

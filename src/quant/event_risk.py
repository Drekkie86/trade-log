from __future__ import annotations

import math

from src.quant.types import QuantInputError


def _finite_non_negative(value: float, name: str) -> float:
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise QuantInputError(f"{name} must be finite and non-negative")
    return numeric


def total_variance(implied_volatility: float, time_to_expiry: float) -> float:
    implied_volatility = _finite_non_negative(implied_volatility, "implied_volatility")
    time_to_expiry = _finite_non_negative(time_to_expiry, "time_to_expiry")
    return implied_volatility * implied_volatility * time_to_expiry


def implied_event_variance(
    event_expiry_iv: float,
    event_expiry_time: float,
    baseline_variance_rate: float,
) -> dict[str, float]:
    event_expiry_iv = _finite_non_negative(event_expiry_iv, "event_expiry_iv")
    event_expiry_time = _finite_non_negative(event_expiry_time, "event_expiry_time")
    baseline_variance_rate = _finite_non_negative(baseline_variance_rate, "baseline_variance_rate")
    observed = event_expiry_iv * event_expiry_iv * event_expiry_time
    baseline = baseline_variance_rate * event_expiry_time
    event_var = max(observed - baseline, 0.0)
    return {
        "observed_total_variance": observed,
        "baseline_total_variance": baseline,
        "event_variance": event_var,
        "event_standard_deviation": math.sqrt(event_var),
    }

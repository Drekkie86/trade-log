from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from src.quant.forecast_validation import ForecastObservation
from src.quant.types import QuantInputError
from src.quant.vol_forecast import ewma_variance, fit_garch11


HISTORICAL_VARIANCE_MODEL_ID = "HISTORICAL_VARIANCE_V1"
EWMA_MODEL_ID = "EWMA_VARIANCE_V1"
GARCH11_MODEL_ID = "GARCH11_VARIANCE_V1"


@dataclass(frozen=True)
class RollingForecastConfig:
    train_window: int = 60
    horizon_days: int = 5
    ewma_decay: float = 0.94
    include_garch: bool = True


def _validate_returns(returns: Sequence[float]) -> np.ndarray:
    values = np.asarray(returns, dtype=float)
    if len(values) < 3 or np.any(~np.isfinite(values)):
        raise QuantInputError("rolling variance forecast requires finite returns")
    return values


def _garch_horizon_average_variance(
    *,
    omega: float,
    alpha: float,
    beta: float,
    next_variance: float,
    horizon_days: int,
) -> float:
    persistence = alpha + beta
    value = float(next_variance)
    path: list[float] = []
    for _ in range(horizon_days):
        path.append(value)
        value = omega + persistence * value
    return float(np.mean(path))


def _regime_label(training_returns: np.ndarray) -> str:
    if len(training_returns) < 20:
        return "UNCLASSIFIED"
    split = max(5, len(training_returns) // 3)
    recent = float(np.var(training_returns[-split:], ddof=1))
    baseline = float(np.var(training_returns, ddof=1))
    if baseline <= 0:
        return "CALM"
    ratio = recent / baseline
    if ratio >= 1.50:
        return "STRESS"
    if ratio <= 0.70:
        return "CALM"
    return "NORMAL"


def rolling_variance_forecasts(
    returns: Sequence[float],
    *,
    config: RollingForecastConfig | None = None,
) -> tuple[ForecastObservation, ...]:
    values = _validate_returns(returns)
    config = config or RollingForecastConfig()
    if config.train_window < 30:
        raise QuantInputError("train_window must be at least 30")
    if config.horizon_days < 1:
        raise QuantInputError("horizon_days must be positive")
    if not 0 < config.ewma_decay < 1:
        raise QuantInputError("ewma_decay must be between 0 and 1")
    minimum = config.train_window + config.horizon_days
    if len(values) < minimum:
        raise QuantInputError(
            f"need at least {minimum} returns for the configured rolling experiment"
        )

    observations: list[ForecastObservation] = []
    last_origin = len(values) - config.horizon_days
    for origin in range(config.train_window, last_origin + 1):
        training = values[origin - config.train_window : origin]
        future = values[origin : origin + config.horizon_days]
        realized_variance = float(np.mean(future * future))
        if realized_variance <= 0:
            realized_variance = float(np.finfo(float).tiny)
        regime = _regime_label(training)

        historical = float(np.var(training, ddof=1))
        historical = max(historical, float(np.finfo(float).tiny))
        observations.append(
            ForecastObservation(
                model_id=HISTORICAL_VARIANCE_MODEL_ID,
                forecast_variance=historical,
                realized_variance=realized_variance,
                horizon_days=config.horizon_days,
                regime=regime,
            )
        )

        ewma = max(
            float(ewma_variance(training, decay=config.ewma_decay)),
            float(np.finfo(float).tiny),
        )
        observations.append(
            ForecastObservation(
                model_id=EWMA_MODEL_ID,
                forecast_variance=ewma,
                realized_variance=realized_variance,
                horizon_days=config.horizon_days,
                regime=regime,
            )
        )

        if config.include_garch:
            fit = fit_garch11(training)
            garch = _garch_horizon_average_variance(
                omega=fit.omega,
                alpha=fit.alpha,
                beta=fit.beta,
                next_variance=fit.next_variance,
                horizon_days=config.horizon_days,
            )
            observations.append(
                ForecastObservation(
                    model_id=GARCH11_MODEL_ID,
                    forecast_variance=max(garch, float(np.finfo(float).tiny)),
                    realized_variance=realized_variance,
                    horizon_days=config.horizon_days,
                    regime=regime,
                )
            )

    return tuple(observations)

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable, Mapping, Sequence

import numpy as np

from src.quant.types import QuantInputError


@dataclass(frozen=True)
class ForecastObservation:
    model_id: str
    forecast_variance: float
    realized_variance: float
    horizon_days: int
    regime: str = "ALL"
    lower_variance: float | None = None
    upper_variance: float | None = None


@dataclass(frozen=True)
class ForecastSummary:
    model_id: str
    regime: str
    count: int
    mean_forecast_variance: float
    mean_realized_variance: float
    bias: float
    mae: float
    rmse: float
    qlike: float
    interval_count: int
    interval_coverage: float | None
    mean_interval_width: float | None
    calibration_error: float | None
    mean_loss_ci_low: float | None
    mean_loss_ci_high: float | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ForecastTournament:
    scoring_rule: str
    summaries: tuple[ForecastSummary, ...]
    ranking: tuple[str, ...]
    winner: str | None
    winner_margin: float | None
    comparable_model_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "scoring_rule": self.scoring_rule,
            "summaries": [item.as_dict() for item in self.summaries],
            "ranking": list(self.ranking),
            "winner": self.winner,
            "winner_margin": self.winner_margin,
            "comparable_model_count": self.comparable_model_count,
        }


def _validate_observation(item: ForecastObservation) -> None:
    if not item.model_id.strip():
        raise QuantInputError("model_id is required")
    if item.horizon_days < 1:
        raise QuantInputError("horizon_days must be positive")
    for name, value in (
        ("forecast_variance", item.forecast_variance),
        ("realized_variance", item.realized_variance),
    ):
        if not math.isfinite(value) or value <= 0:
            raise QuantInputError(f"{name} must be finite and positive")
    if (item.lower_variance is None) != (item.upper_variance is None):
        raise QuantInputError("forecast intervals require both lower_variance and upper_variance")
    if item.lower_variance is not None and item.upper_variance is not None:
        if not (
            math.isfinite(item.lower_variance)
            and math.isfinite(item.upper_variance)
            and 0 <= item.lower_variance <= item.upper_variance
        ):
            raise QuantInputError("forecast interval must be finite, non-negative and ordered")


def qlike_loss(forecast_variance: float, realized_variance: float) -> float:
    if forecast_variance <= 0 or realized_variance <= 0:
        raise QuantInputError("QLIKE requires positive forecast and realized variance")
    ratio = realized_variance / forecast_variance
    return float(ratio - math.log(ratio) - 1.0)


def _bootstrap_mean_ci(
    values: np.ndarray,
    *,
    confidence: float,
    bootstrap_samples: int,
    seed: int,
) -> tuple[float | None, float | None]:
    if len(values) < 2 or bootstrap_samples < 1:
        return None, None
    if not 0 < confidence < 1:
        raise QuantInputError("confidence must be between 0 and 1")
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(values), size=(bootstrap_samples, len(values)))
    means = values[indices].mean(axis=1)
    alpha = (1.0 - confidence) / 2.0
    return (
        float(np.quantile(means, alpha)),
        float(np.quantile(means, 1.0 - alpha)),
    )


def summarize_forecasts(
    observations: Sequence[ForecastObservation],
    *,
    model_id: str,
    regime: str = "ALL",
    expected_interval_coverage: float | None = None,
    bootstrap_samples: int = 2000,
    confidence: float = 0.95,
    seed: int = 17,
) -> ForecastSummary:
    selected = [
        item
        for item in observations
        if item.model_id == model_id and (regime == "ALL" or item.regime == regime)
    ]
    if not selected:
        raise QuantInputError("no matching forecast observations")
    for item in selected:
        _validate_observation(item)

    forecasts = np.asarray([item.forecast_variance for item in selected], dtype=float)
    realized = np.asarray([item.realized_variance for item in selected], dtype=float)
    errors = forecasts - realized
    losses = np.asarray(
        [qlike_loss(item.forecast_variance, item.realized_variance) for item in selected],
        dtype=float,
    )
    ci_low, ci_high = _bootstrap_mean_ci(
        losses,
        confidence=confidence,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
    )

    interval_rows = [
        item
        for item in selected
        if item.lower_variance is not None and item.upper_variance is not None
    ]
    coverage: float | None = None
    width: float | None = None
    calibration_error: float | None = None
    if interval_rows:
        covered = [
            float(item.lower_variance) <= item.realized_variance <= float(item.upper_variance)
            for item in interval_rows
        ]
        widths = [float(item.upper_variance) - float(item.lower_variance) for item in interval_rows]
        coverage = float(np.mean(covered))
        width = float(np.mean(widths))
        if expected_interval_coverage is not None:
            if not 0 < expected_interval_coverage < 1:
                raise QuantInputError("expected_interval_coverage must be between 0 and 1")
            calibration_error = coverage - expected_interval_coverage

    return ForecastSummary(
        model_id=model_id,
        regime=regime,
        count=len(selected),
        mean_forecast_variance=float(np.mean(forecasts)),
        mean_realized_variance=float(np.mean(realized)),
        bias=float(np.mean(errors)),
        mae=float(np.mean(np.abs(errors))),
        rmse=float(np.sqrt(np.mean(errors * errors))),
        qlike=float(np.mean(losses)),
        interval_count=len(interval_rows),
        interval_coverage=coverage,
        mean_interval_width=width,
        calibration_error=calibration_error,
        mean_loss_ci_low=ci_low,
        mean_loss_ci_high=ci_high,
    )


def tournament(
    observations: Sequence[ForecastObservation],
    *,
    regime: str = "ALL",
    scoring_rule: str = "QLIKE",
    expected_interval_coverage: float | None = None,
    bootstrap_samples: int = 2000,
    confidence: float = 0.95,
    seed: int = 17,
) -> ForecastTournament:
    scoring_rule = scoring_rule.upper()
    if scoring_rule not in {"QLIKE", "MAE", "RMSE"}:
        raise QuantInputError("scoring_rule must be QLIKE, MAE or RMSE")
    model_ids = sorted({item.model_id for item in observations})
    summaries = tuple(
        summarize_forecasts(
            observations,
            model_id=model_id,
            regime=regime,
            expected_interval_coverage=expected_interval_coverage,
            bootstrap_samples=bootstrap_samples,
            confidence=confidence,
            seed=seed + index,
        )
        for index, model_id in enumerate(model_ids)
        if any(item.model_id == model_id and (regime == "ALL" or item.regime == regime) for item in observations)
    )
    if not summaries:
        return ForecastTournament(scoring_rule, (), (), None, None, 0)

    metric_name = {"QLIKE": "qlike", "MAE": "mae", "RMSE": "rmse"}[scoring_rule]
    ordered = sorted(summaries, key=lambda item: (getattr(item, metric_name), item.model_id))
    ranking = tuple(item.model_id for item in ordered)
    margin = None
    if len(ordered) >= 2:
        margin = float(getattr(ordered[1], metric_name) - getattr(ordered[0], metric_name))
    return ForecastTournament(
        scoring_rule=scoring_rule,
        summaries=summaries,
        ranking=ranking,
        winner=ranking[0],
        winner_margin=margin,
        comparable_model_count=len(ordered),
    )


def summarize_by_regime(
    observations: Sequence[ForecastObservation],
    *,
    expected_interval_coverage: float | None = None,
    bootstrap_samples: int = 2000,
    confidence: float = 0.95,
    seed: int = 17,
) -> Mapping[str, ForecastTournament]:
    regimes = sorted({item.regime for item in observations})
    return {
        regime: tournament(
            observations,
            regime=regime,
            expected_interval_coverage=expected_interval_coverage,
            bootstrap_samples=bootstrap_samples,
            confidence=confidence,
            seed=seed + index,
        )
        for index, regime in enumerate(regimes)
    }

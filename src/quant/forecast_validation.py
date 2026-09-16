from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from statistics import NormalDist
from typing import Mapping, Sequence

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
    origin_index: int | None = None


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
    bootstrap_method: str
    bootstrap_block_length: int | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ForecastPairwiseComparison:
    candidate_model_id: str
    challenger_model_id: str
    scoring_rule: str
    paired_count: int
    mean_loss_difference: float | None
    ci_low: float | None
    ci_high: float | None
    confidence: float
    comparison_method: str
    hac_max_lag: int | None
    state: str
    supports_candidate: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ForecastTournament:
    scoring_rule: str
    summaries: tuple[ForecastSummary, ...]
    ranking: tuple[str, ...]
    winner: str | None
    winner_margin: float | None
    observed_margin: float | None
    comparable_model_count: int
    selection_state: str
    pairwise_confidence: float | None
    comparisons: tuple[ForecastPairwiseComparison, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "scoring_rule": self.scoring_rule,
            "summaries": [item.as_dict() for item in self.summaries],
            "ranking": list(self.ranking),
            "winner": self.winner,
            "winner_margin": self.winner_margin,
            "observed_margin": self.observed_margin,
            "comparable_model_count": self.comparable_model_count,
            "selection_state": self.selection_state,
            "pairwise_confidence": self.pairwise_confidence,
            "comparisons": [item.as_dict() for item in self.comparisons],
        }


def _validate_observation(item: ForecastObservation) -> None:
    if not item.model_id.strip():
        raise QuantInputError("model_id is required")
    if item.horizon_days < 1:
        raise QuantInputError("horizon_days must be positive")
    if item.origin_index is not None and item.origin_index < 0:
        raise QuantInputError("origin_index cannot be negative")
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


def _common_horizon_days(observations: Sequence[ForecastObservation]) -> int:
    horizons = {int(item.horizon_days) for item in observations}
    if len(horizons) != 1:
        raise QuantInputError("forecast comparison requires one common horizon_days value")
    return horizons.pop()


def _moving_block_bootstrap_mean_ci(
    values: np.ndarray,
    *,
    block_length: int,
    confidence: float,
    bootstrap_samples: int,
    seed: int,
) -> tuple[float | None, float | None]:
    """Dependence-aware CI for a serial loss series.

    The block length is set by the forecast horizon at the caller. That covers
    the structural dependence introduced by overlapping h-step outcomes without
    pretending the loss observations are IID.
    """
    values = np.asarray(values, dtype=float)
    if np.any(~np.isfinite(values)):
        raise QuantInputError("bootstrap values must be finite")
    if block_length < 1:
        raise QuantInputError("block_length must be positive")
    if not 0 < confidence < 1:
        raise QuantInputError("confidence must be between 0 and 1")
    if len(values) <= block_length or bootstrap_samples < 1:
        return None, None

    rng = np.random.default_rng(seed)
    n = len(values)
    blocks_per_sample = math.ceil(n / block_length)
    offsets = np.arange(block_length, dtype=int)
    means = np.empty(bootstrap_samples, dtype=float)
    for sample_index in range(bootstrap_samples):
        starts = rng.integers(0, n, size=blocks_per_sample)
        indices = ((starts[:, None] + offsets[None, :]) % n).reshape(-1)[:n]
        means[sample_index] = float(np.mean(values[indices]))

    alpha = (1.0 - confidence) / 2.0
    return (
        float(np.quantile(means, alpha)),
        float(np.quantile(means, 1.0 - alpha)),
    )


def _score_contributions(
    observations: Sequence[ForecastObservation],
    *,
    scoring_rule: str,
) -> np.ndarray:
    if scoring_rule == "QLIKE":
        return np.asarray(
            [qlike_loss(item.forecast_variance, item.realized_variance) for item in observations],
            dtype=float,
        )

    errors = np.asarray(
        [item.forecast_variance - item.realized_variance for item in observations],
        dtype=float,
    )
    if scoring_rule == "MAE":
        return np.abs(errors)
    if scoring_rule == "RMSE":
        # RMSE ranking is monotonic in mean squared error, so paired comparison
        # is performed on per-origin squared-error contributions.
        return errors * errors
    raise QuantInputError("scoring_rule must be QLIKE, MAE or RMSE")


def _model_observations(
    observations: Sequence[ForecastObservation],
    *,
    model_id: str,
    regime: str,
) -> list[ForecastObservation]:
    return [
        item
        for item in observations
        if item.model_id == model_id and (regime == "ALL" or item.regime == regime)
    ]


def _paired_observations(
    candidate: Sequence[ForecastObservation],
    challenger: Sequence[ForecastObservation],
) -> tuple[list[ForecastObservation], list[ForecastObservation]] | None:
    if len(candidate) != len(challenger) or not candidate:
        return None

    candidate_origins = [item.origin_index for item in candidate]
    challenger_origins = [item.origin_index for item in challenger]
    has_explicit_origins = all(
        value is not None for value in candidate_origins + challenger_origins
    )
    if has_explicit_origins:
        challenger_by_origin = {int(item.origin_index): item for item in challenger}
        if len(challenger_by_origin) != len(challenger):
            return None
        aligned_challenger: list[ForecastObservation] = []
        for item in candidate:
            match = challenger_by_origin.get(int(item.origin_index))
            if match is None:
                return None
            aligned_challenger.append(match)
        challenger = aligned_challenger

    for left, right in zip(candidate, challenger):
        if left.horizon_days != right.horizon_days or left.regime != right.regime:
            return None
        if not math.isclose(
            left.realized_variance,
            right.realized_variance,
            rel_tol=1e-12,
            abs_tol=1e-15,
        ):
            return None
    return list(candidate), list(challenger)


def _paired_hac_mean_ci(
    differences: np.ndarray,
    *,
    horizon_days: int,
    confidence: float,
) -> tuple[float | None, float | None, int]:
    """Paired-loss CI using a Bartlett/Newey-West HAC variance estimate.

    For h-step forecasts, overlap creates serial dependence through at least
    h-1 lags. Using that lag structure avoids treating daily rolling origins as
    independent forecast experiments.
    """
    differences = np.asarray(differences, dtype=float)
    if np.any(~np.isfinite(differences)):
        raise QuantInputError("paired loss differences must be finite")
    if not 0 < confidence < 1:
        raise QuantInputError("confidence must be between 0 and 1")
    if horizon_days < 1:
        raise QuantInputError("horizon_days must be positive")

    n = len(differences)
    max_lag = min(horizon_days - 1, max(n - 1, 0))
    if n <= max_lag + 1:
        return None, None, max_lag

    mean_difference = float(np.mean(differences))
    centered = differences - mean_difference
    long_run_variance = float(np.dot(centered, centered) / n)
    for lag in range(1, max_lag + 1):
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / n)
        weight = 1.0 - lag / (max_lag + 1.0)
        long_run_variance += 2.0 * weight * covariance

    if not math.isfinite(long_run_variance) or long_run_variance <= 0:
        return None, None, max_lag

    standard_error = math.sqrt(long_run_variance / n)
    if not math.isfinite(standard_error) or standard_error <= 0:
        return None, None, max_lag

    z = NormalDist().inv_cdf(0.5 + confidence / 2.0)
    return (
        float(mean_difference - z * standard_error),
        float(mean_difference + z * standard_error),
        max_lag,
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
    selected = _model_observations(observations, model_id=model_id, regime=regime)
    if not selected:
        raise QuantInputError("no matching forecast observations")
    for item in selected:
        _validate_observation(item)

    horizon_days = _common_horizon_days(selected)
    forecasts = np.asarray([item.forecast_variance for item in selected], dtype=float)
    realized = np.asarray([item.realized_variance for item in selected], dtype=float)
    errors = forecasts - realized
    losses = np.asarray(
        [qlike_loss(item.forecast_variance, item.realized_variance) for item in selected],
        dtype=float,
    )
    ci_low, ci_high = _moving_block_bootstrap_mean_ci(
        losses,
        block_length=horizon_days,
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
        bootstrap_method="CIRCULAR_MOVING_BLOCK",
        bootstrap_block_length=horizon_days,
    )


def _pairwise_comparison(
    observations: Sequence[ForecastObservation],
    *,
    candidate_model_id: str,
    challenger_model_id: str,
    regime: str,
    scoring_rule: str,
    confidence: float,
) -> ForecastPairwiseComparison:
    candidate = _model_observations(
        observations,
        model_id=candidate_model_id,
        regime=regime,
    )
    challenger = _model_observations(
        observations,
        model_id=challenger_model_id,
        regime=regime,
    )
    paired = _paired_observations(candidate, challenger)
    if paired is None:
        return ForecastPairwiseComparison(
            candidate_model_id=candidate_model_id,
            challenger_model_id=challenger_model_id,
            scoring_rule=scoring_rule,
            paired_count=0,
            mean_loss_difference=None,
            ci_low=None,
            ci_high=None,
            confidence=confidence,
            comparison_method="PAIRED_HAC_BARTLETT",
            hac_max_lag=None,
            state="UNPAIRED_OR_MISALIGNED_OBSERVATIONS",
            supports_candidate=False,
        )

    candidate, challenger = paired
    horizon_days = _common_horizon_days(candidate)
    candidate_losses = _score_contributions(candidate, scoring_rule=scoring_rule)
    challenger_losses = _score_contributions(challenger, scoring_rule=scoring_rule)
    differences = candidate_losses - challenger_losses
    mean_difference = float(np.mean(differences))
    ci_low, ci_high, max_lag = _paired_hac_mean_ci(
        differences,
        horizon_days=horizon_days,
        confidence=confidence,
    )
    if ci_low is None or ci_high is None:
        state = "INSUFFICIENT_HAC_EVIDENCE"
        supports_candidate = False
    elif ci_high < 0.0:
        state = "CANDIDATE_SUPERIOR"
        supports_candidate = True
    else:
        state = "SUPERIORITY_NOT_ESTABLISHED"
        supports_candidate = False

    return ForecastPairwiseComparison(
        candidate_model_id=candidate_model_id,
        challenger_model_id=challenger_model_id,
        scoring_rule=scoring_rule,
        paired_count=len(candidate),
        mean_loss_difference=mean_difference,
        ci_low=ci_low,
        ci_high=ci_high,
        confidence=confidence,
        comparison_method="PAIRED_HAC_BARTLETT",
        hac_max_lag=max_lag,
        state=state,
        supports_candidate=supports_candidate,
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
    if not 0 < confidence < 1:
        raise QuantInputError("confidence must be between 0 and 1")

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
        if any(
            item.model_id == model_id and (regime == "ALL" or item.regime == regime)
            for item in observations
        )
    )
    if not summaries:
        return ForecastTournament(
            scoring_rule=scoring_rule,
            summaries=(),
            ranking=(),
            winner=None,
            winner_margin=None,
            observed_margin=None,
            comparable_model_count=0,
            selection_state="NO_MODELS",
            pairwise_confidence=None,
            comparisons=(),
        )

    metric_name = {"QLIKE": "qlike", "MAE": "mae", "RMSE": "rmse"}[scoring_rule]
    ordered = sorted(
        summaries,
        key=lambda item: (getattr(item, metric_name), item.model_id),
    )
    ranking = tuple(item.model_id for item in ordered)

    observed_margin = None
    if len(ordered) >= 2:
        observed_margin = float(
            getattr(ordered[1], metric_name) - getattr(ordered[0], metric_name)
        )
    if len(ordered) < 2:
        return ForecastTournament(
            scoring_rule=scoring_rule,
            summaries=summaries,
            ranking=ranking,
            winner=None,
            winner_margin=None,
            observed_margin=observed_margin,
            comparable_model_count=len(ordered),
            selection_state="SINGLE_MODEL_NO_SUPERIORITY_TEST",
            pairwise_confidence=None,
            comparisons=(),
        )

    # The candidate was selected from the same model family being compared.
    # Bonferroni across all possible model pairs keeps the family-wise confidence
    # tied to the caller's requested confidence rather than inventing a threshold.
    model_count = len(ordered)
    family_comparison_count = model_count * (model_count - 1) // 2
    pairwise_confidence = 1.0 - (1.0 - confidence) / family_comparison_count
    comparisons = tuple(
        _pairwise_comparison(
            observations,
            candidate_model_id=ranking[0],
            challenger_model_id=challenger.model_id,
            regime=regime,
            scoring_rule=scoring_rule,
            confidence=pairwise_confidence,
        )
        for challenger in ordered[1:]
    )

    has_insufficient = any(
        item.state in {
            "UNPAIRED_OR_MISALIGNED_OBSERVATIONS",
            "INSUFFICIENT_HAC_EVIDENCE",
        }
        for item in comparisons
    )
    winner_supported = bool(comparisons) and all(
        item.supports_candidate for item in comparisons
    )
    winner = ranking[0] if winner_supported else None
    if winner_supported:
        selection_state = "EVIDENCE_SUPPORTED_WINNER"
    elif has_insufficient:
        selection_state = "INSUFFICIENT_COMPARISON_EVIDENCE"
    else:
        selection_state = "NO_SIGNIFICANT_WINNER"

    return ForecastTournament(
        scoring_rule=scoring_rule,
        summaries=summaries,
        ranking=ranking,
        winner=winner,
        winner_margin=observed_margin if winner_supported else None,
        observed_margin=observed_margin,
        comparable_model_count=len(ordered),
        selection_state=selection_state,
        pairwise_confidence=pairwise_confidence,
        comparisons=comparisons,
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

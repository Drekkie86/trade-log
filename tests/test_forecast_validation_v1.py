import math

import pytest

from src.quant.forecast_validation import (
    ForecastObservation,
    qlike_loss,
    summarize_by_regime,
    summarize_forecasts,
    tournament,
)
from src.quant.types import QuantInputError


def _obs(model: str, forecast: float, realized: float, regime: str = "CALM") -> ForecastObservation:
    return ForecastObservation(
        model_id=model,
        forecast_variance=forecast,
        realized_variance=realized,
        horizon_days=5,
        regime=regime,
        lower_variance=max(forecast * 0.5, 1e-8),
        upper_variance=forecast * 1.5,
    )


def test_qlike_is_zero_for_perfect_variance_forecast() -> None:
    assert qlike_loss(0.04, 0.04) == pytest.approx(0.0)


def test_summary_reports_bias_error_and_interval_calibration() -> None:
    rows = [
        _obs("A", 0.04, 0.04),
        _obs("A", 0.05, 0.04),
        _obs("A", 0.03, 0.04),
    ]
    summary = summarize_forecasts(
        rows,
        model_id="A",
        expected_interval_coverage=0.80,
        bootstrap_samples=200,
        seed=1,
    )
    assert summary.count == 3
    assert summary.bias == pytest.approx(0.0)
    assert summary.mae == pytest.approx((0.0 + 0.01 + 0.01) / 3.0)
    assert summary.interval_count == 3
    assert 0 <= summary.interval_coverage <= 1
    assert summary.calibration_error == pytest.approx(summary.interval_coverage - 0.80)
    assert summary.mean_loss_ci_low is not None
    assert summary.mean_loss_ci_high is not None


def test_tournament_prefers_better_model_on_qlike() -> None:
    rows = []
    realized = [0.03, 0.04, 0.05, 0.06]
    for value in realized:
        rows.append(_obs("GOOD", value * 1.01, value))
        rows.append(_obs("BAD", value * 1.50, value))

    result = tournament(rows, scoring_rule="QLIKE", bootstrap_samples=100)

    assert result.winner == "GOOD"
    assert result.ranking[0] == "GOOD"
    assert result.comparable_model_count == 2
    assert result.winner_margin is not None and result.winner_margin > 0


def test_regime_tournaments_are_kept_separate() -> None:
    rows = [
        _obs("A", 0.04, 0.04, "CALM"),
        _obs("B", 0.05, 0.04, "CALM"),
        _obs("A", 0.09, 0.10, "STRESS"),
        _obs("B", 0.10, 0.10, "STRESS"),
    ]
    regimes = summarize_by_regime(rows, bootstrap_samples=50)
    assert set(regimes) == {"CALM", "STRESS"}
    assert regimes["CALM"].winner == "A"
    assert regimes["STRESS"].winner == "B"


def test_invalid_forecast_is_rejected() -> None:
    with pytest.raises(QuantInputError):
        summarize_forecasts(
            [ForecastObservation("A", 0.0, 0.04, 5)],
            model_id="A",
        )

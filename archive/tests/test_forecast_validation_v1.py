import math

import numpy as np
import pytest

from src.quant.forecast_validation import (
    ForecastObservation,
    qlike_loss,
    summarize_by_regime,
    summarize_forecasts,
    tournament,
)
from src.quant.types import QuantInputError


def _obs(
    model: str,
    forecast: float,
    realized: float,
    regime: str = "CALM",
    *,
    horizon_days: int = 5,
    origin_index: int | None = None,
) -> ForecastObservation:
    return ForecastObservation(
        model_id=model,
        forecast_variance=forecast,
        realized_variance=realized,
        horizon_days=horizon_days,
        regime=regime,
        lower_variance=max(forecast * 0.5, 1e-8),
        upper_variance=forecast * 1.5,
        origin_index=origin_index,
    )


def test_qlike_is_zero_for_perfect_variance_forecast() -> None:
    assert qlike_loss(0.04, 0.04) == pytest.approx(0.0)


def test_summary_reports_bias_error_and_dependence_aware_interval_calibration() -> None:
    rows = [
        _obs("A", 0.04, 0.04, horizon_days=1, origin_index=0),
        _obs("A", 0.05, 0.04, horizon_days=1, origin_index=1),
        _obs("A", 0.03, 0.04, horizon_days=1, origin_index=2),
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
    assert summary.bootstrap_method == "CIRCULAR_MOVING_BLOCK"
    assert summary.bootstrap_block_length == 1


def test_tournament_declares_winner_only_with_paired_hac_evidence() -> None:
    rows = []
    for origin, realized in enumerate(np.linspace(0.02, 0.06, 50)):
        good_multiplier = 1.01 + 0.002 * math.sin(origin)
        bad_multiplier = 1.35 + 0.03 * math.cos(origin)
        rows.append(
            _obs(
                "GOOD",
                realized * good_multiplier,
                realized,
                origin_index=origin,
            )
        )
        rows.append(
            _obs(
                "BAD",
                realized * bad_multiplier,
                realized,
                origin_index=origin,
            )
        )

    result = tournament(rows, scoring_rule="QLIKE", bootstrap_samples=200)

    assert result.winner == "GOOD"
    assert result.ranking[0] == "GOOD"
    assert result.comparable_model_count == 2
    assert result.selection_state == "EVIDENCE_SUPPORTED_WINNER"
    assert result.winner_margin is not None and result.winner_margin > 0
    assert result.observed_margin == result.winner_margin
    assert len(result.comparisons) == 1
    assert result.comparisons[0].comparison_method == "PAIRED_HAC_BARTLETT"
    assert result.comparisons[0].supports_candidate is True
    assert result.comparisons[0].ci_high is not None
    assert result.comparisons[0].ci_high < 0


def test_tournament_refuses_noise_winner_when_models_are_indistinguishable() -> None:
    rows = []
    for origin, realized in enumerate(np.linspace(0.02, 0.06, 60)):
        if origin % 2 == 0:
            a_multiplier, b_multiplier = 1.06, 1.04
        else:
            a_multiplier, b_multiplier = 1.04, 1.06
        rows.append(_obs("A", realized * a_multiplier, realized, origin_index=origin))
        rows.append(_obs("B", realized * b_multiplier, realized, origin_index=origin))

    result = tournament(rows, scoring_rule="QLIKE", bootstrap_samples=200)

    assert result.winner is None
    assert result.selection_state == "NO_SIGNIFICANT_WINNER"
    assert result.winner_margin is None
    assert result.observed_margin == pytest.approx(0.0, abs=1e-12)
    assert len(result.comparisons) == 1
    assert result.comparisons[0].supports_candidate is False
    assert result.comparisons[0].ci_low is not None
    assert result.comparisons[0].ci_high is not None
    assert result.comparisons[0].ci_low <= 0 <= result.comparisons[0].ci_high


def test_overlapping_horizon_summary_uses_horizon_sized_blocks() -> None:
    rows = [
        _obs(
            "A",
            0.04 + 0.0002 * origin,
            0.041 + 0.0001 * origin,
            horizon_days=5,
            origin_index=origin,
        )
        for origin in range(20)
    ]
    summary = summarize_forecasts(rows, model_id="A", bootstrap_samples=100, seed=7)

    assert summary.bootstrap_method == "CIRCULAR_MOVING_BLOCK"
    assert summary.bootstrap_block_length == 5
    assert summary.mean_loss_ci_low is not None
    assert summary.mean_loss_ci_high is not None


def test_regime_tournaments_are_kept_separate() -> None:
    rows = []
    for origin, realized in enumerate(np.linspace(0.02, 0.04, 30)):
        rows.append(
            _obs(
                "A",
                realized * (1.01 + 0.002 * math.sin(origin)),
                realized,
                "CALM",
                origin_index=origin,
            )
        )
        rows.append(
            _obs(
                "B",
                realized * (1.35 + 0.02 * math.cos(origin)),
                realized,
                "CALM",
                origin_index=origin,
            )
        )

    for offset, realized in enumerate(np.linspace(0.05, 0.09, 30)):
        origin = 100 + offset
        rows.append(
            _obs(
                "A",
                realized * (1.35 + 0.02 * math.cos(offset)),
                realized,
                "STRESS",
                origin_index=origin,
            )
        )
        rows.append(
            _obs(
                "B",
                realized * (1.01 + 0.002 * math.sin(offset)),
                realized,
                "STRESS",
                origin_index=origin,
            )
        )

    regimes = summarize_by_regime(rows, bootstrap_samples=100)
    assert set(regimes) == {"CALM", "STRESS"}
    assert regimes["CALM"].winner == "A"
    assert regimes["STRESS"].winner == "B"


def test_misaligned_model_outcomes_cannot_support_a_winner() -> None:
    rows = []
    for origin in range(10):
        rows.append(_obs("A", 0.04, 0.04, origin_index=origin))
        rows.append(_obs("B", 0.05, 0.041, origin_index=origin))

    result = tournament(rows, bootstrap_samples=50)

    assert result.winner is None
    assert result.selection_state == "INSUFFICIENT_COMPARISON_EVIDENCE"
    assert result.comparisons[0].state == "UNPAIRED_OR_MISALIGNED_OBSERVATIONS"


def test_invalid_forecast_is_rejected() -> None:
    with pytest.raises(QuantInputError):
        summarize_forecasts(
            [ForecastObservation("A", 0.0, 0.04, 5)],
            model_id="A",
        )

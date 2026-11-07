from __future__ import annotations

import pytest

from src.quant.types import QuantInputError
from src.research.calibration_tournament_v1 import (
    ProbabilityObservation,
    calibration_summary,
    compare_models_paired,
    promotion_review,
)


def _rows() -> list[ProbabilityObservation]:
    rows: list[ProbabilityObservation] = []
    for index in range(40):
        outcome = 1 if index % 2 == 0 else 0
        probability = 0.80 if outcome else 0.20
        rows.append(
            ProbabilityObservation(
                observation_key=f"obs-{index}",
                model_id="INCUMBENT",
                channel="PROFIT",
                probability=probability,
                outcome=outcome,
                independent_date=f"2026-09-{1 + (index % 10):02d}",
            )
        )
        rows.append(
            ProbabilityObservation(
                observation_key=f"obs-{index}",
                model_id="CHALLENGER",
                channel="PROFIT",
                probability=(0.90 if outcome else 0.10),
                outcome=outcome,
                independent_date=f"2026-09-{1 + (index % 10):02d}",
            )
        )
    return rows


def test_calibration_summary_keeps_profit_channel_separate() -> None:
    rows = _rows()
    rows.append(
        ProbabilityObservation(
            observation_key="thesis-1",
            model_id="INCUMBENT",
            channel="THESIS",
            probability=0.95,
            outcome=1,
            independent_date="2026-09-11",
        )
    )
    summary = calibration_summary(rows, model_id="INCUMBENT", channel="PROFIT", bin_count=5)
    assert summary.observation_count == 40
    assert summary.independent_date_count == 10
    assert summary.brier_score == pytest.approx(0.04)
    assert summary.observed_frequency == pytest.approx(0.5)
    assert 0 <= summary.expected_calibration_error <= 1
    assert sum(item.count for item in summary.bins) == 40


def test_paired_tournament_detects_descriptively_better_challenger() -> None:
    comparison = compare_models_paired(
        _rows(),
        incumbent_model_id="INCUMBENT",
        challenger_model_id="CHALLENGER",
        channel="PROFIT",
        bootstrap_samples=1000,
        seed=7,
    )
    assert comparison.paired_count == 40
    assert comparison.independent_date_count == 10
    assert comparison.challenger_brier < comparison.incumbent_brier
    assert comparison.challenger_minus_incumbent_brier < 0
    assert comparison.delta_ci_high is not None
    assert comparison.delta_ci_high < 0
    assert comparison.tournament_state == "CHALLENGER_DESCRIPTIVELY_BETTER"
    assert comparison.challenger_win_rate == pytest.approx(1.0)


def test_tournament_requires_shared_observations_and_matching_outcomes() -> None:
    no_shared = [
        ProbabilityObservation("a", "A", "PROFIT", 0.5, 1, "2026-09-01"),
        ProbabilityObservation("b", "B", "PROFIT", 0.5, 1, "2026-09-01"),
    ]
    result = compare_models_paired(
        no_shared,
        incumbent_model_id="A",
        challenger_model_id="B",
        channel="PROFIT",
        bootstrap_samples=100,
    )
    assert result.tournament_state == "INSUFFICIENT_PAIRED_EVIDENCE"

    mismatched = [
        ProbabilityObservation("same", "A", "PROFIT", 0.5, 1, "2026-09-01"),
        ProbabilityObservation("same", "B", "PROFIT", 0.5, 0, "2026-09-01"),
    ]
    with pytest.raises(QuantInputError):
        compare_models_paired(
            mismatched,
            incumbent_model_id="A",
            challenger_model_id="B",
            channel="PROFIT",
            bootstrap_samples=100,
        )


def test_promotion_review_is_review_only_and_sample_gated() -> None:
    summary = calibration_summary(_rows(), model_id="CHALLENGER", channel="PROFIT", bin_count=5)
    insufficient = promotion_review(
        summary,
        model_id="CHALLENGER",
        channel="PROFIT",
        robustness_passed=True,
        minimum_observations=100,
        minimum_independent_dates=20,
    )
    assert insufficient.review_state == "CONTINUE_SHADOW"
    assert "INSUFFICIENT_OBSERVATIONS" in insufficient.reasons
    assert "INSUFFICIENT_INDEPENDENT_DATES" in insufficient.reasons
    assert insufficient.decision_authority == "NONE_AUTOMATIC_REVIEW_ONLY"

    eligible = promotion_review(
        summary,
        model_id="CHALLENGER",
        channel="PROFIT",
        robustness_passed=True,
        minimum_observations=40,
        minimum_independent_dates=10,
        maximum_brier=0.10,
        maximum_ece=0.20,
    )
    assert eligible.review_state == "ELIGIBLE_FOR_PROMOTION_REVIEW"
    assert eligible.reasons == ()


def test_invalid_probability_inputs_fail_closed() -> None:
    with pytest.raises(QuantInputError):
        ProbabilityObservation("x", "M", "PROFIT", 1.1, 1, "2026-09-01").validate()
    with pytest.raises(QuantInputError):
        ProbabilityObservation("x", "M", "OTHER", 0.5, 1, "2026-09-01").validate()
    with pytest.raises(QuantInputError):
        calibration_summary(
            [ProbabilityObservation("x", "M", "PROFIT", 0.5, 1, "2026-09-01")],
            model_id="M",
            channel="PROFIT",
            bin_count=1,
        )

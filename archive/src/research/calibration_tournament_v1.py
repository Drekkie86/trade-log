from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable, Sequence

import numpy as np

from src.quant.types import QuantInputError


CALIBRATION_TOURNAMENT_VERSION = "1.0.0"
VALID_CHANNELS = frozenset({"THESIS", "PROFIT"})


@dataclass(frozen=True)
class ProbabilityObservation:
    observation_key: str
    model_id: str
    channel: str
    probability: float
    outcome: int
    independent_date: str
    cohort: str = "DEFAULT"

    def validate(self) -> None:
        if not self.observation_key.strip():
            raise QuantInputError("observation_key is required")
        if not self.model_id.strip():
            raise QuantInputError("model_id is required")
        if self.channel not in VALID_CHANNELS:
            raise QuantInputError("channel must be THESIS or PROFIT")
        if not math.isfinite(self.probability) or not 0.0 <= self.probability <= 1.0:
            raise QuantInputError("probability must be finite and in [0,1]")
        if self.outcome not in {0, 1}:
            raise QuantInputError("outcome must be 0 or 1")
        if not self.independent_date.strip():
            raise QuantInputError("independent_date is required")
        if not self.cohort.strip():
            raise QuantInputError("cohort is required")


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_probability: float
    observed_frequency: float
    calibration_gap: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CalibrationSummary:
    version: str
    model_id: str
    channel: str
    cohort: str
    observation_count: int
    independent_date_count: int
    brier_score: float
    log_loss: float
    mean_probability: float
    observed_frequency: float
    calibration_in_the_large: float
    expected_calibration_error: float
    mean_absolute_calibration_gap: float
    bins: tuple[CalibrationBin, ...]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["bins"] = [item.as_dict() for item in self.bins]
        return payload


@dataclass(frozen=True)
class TournamentComparison:
    version: str
    incumbent_model_id: str
    challenger_model_id: str
    channel: str
    paired_count: int
    independent_date_count: int
    incumbent_brier: float | None
    challenger_brier: float | None
    challenger_minus_incumbent_brier: float | None
    delta_ci_low: float | None
    delta_ci_high: float | None
    challenger_win_rate: float | None
    tournament_state: str
    detail: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PromotionReview:
    version: str
    model_id: str
    channel: str
    observation_count: int
    independent_date_count: int
    brier_score: float | None
    expected_calibration_error: float | None
    robustness_passed: bool
    review_state: str
    reasons: tuple[str, ...]
    decision_authority: str

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


def _validated(observations: Sequence[ProbabilityObservation]) -> tuple[ProbabilityObservation, ...]:
    rows = tuple(observations)
    for item in rows:
        item.validate()
    return rows


def _selected(
    observations: Sequence[ProbabilityObservation],
    *,
    model_id: str,
    channel: str,
    cohort: str,
) -> tuple[ProbabilityObservation, ...]:
    if channel not in VALID_CHANNELS:
        raise QuantInputError("channel must be THESIS or PROFIT")
    rows = _validated(observations)
    selected = tuple(
        item
        for item in rows
        if item.model_id == model_id
        and item.channel == channel
        and item.cohort == cohort
    )
    if not selected:
        raise QuantInputError("no matching calibration observations")
    keys = [item.observation_key for item in selected]
    if len(keys) != len(set(keys)):
        raise QuantInputError("duplicate observation_key within calibration slice")
    return selected


def calibration_summary(
    observations: Sequence[ProbabilityObservation],
    *,
    model_id: str,
    channel: str,
    cohort: str = "DEFAULT",
    bin_count: int = 10,
    log_loss_epsilon: float = 1e-12,
) -> CalibrationSummary:
    if bin_count < 2 or bin_count > 100:
        raise QuantInputError("bin_count must be between 2 and 100")
    if not 0 < log_loss_epsilon < 0.5:
        raise QuantInputError("log_loss_epsilon must be in (0,0.5)")

    selected = _selected(
        observations,
        model_id=model_id,
        channel=channel,
        cohort=cohort,
    )
    probabilities = np.asarray([item.probability for item in selected], dtype=float)
    outcomes = np.asarray([item.outcome for item in selected], dtype=float)

    brier = float(np.mean((probabilities - outcomes) ** 2))
    clipped = np.clip(probabilities, log_loss_epsilon, 1.0 - log_loss_epsilon)
    log_loss = float(
        -np.mean(outcomes * np.log(clipped) + (1.0 - outcomes) * np.log(1.0 - clipped))
    )

    edges = np.linspace(0.0, 1.0, bin_count + 1)
    bins: list[CalibrationBin] = []
    weighted_gap = 0.0
    absolute_gaps: list[float] = []
    for index in range(bin_count):
        lower = float(edges[index])
        upper = float(edges[index + 1])
        if index == bin_count - 1:
            mask = (probabilities >= lower) & (probabilities <= upper)
        else:
            mask = (probabilities >= lower) & (probabilities < upper)
        count = int(np.sum(mask))
        if count == 0:
            continue
        mean_probability = float(np.mean(probabilities[mask]))
        observed_frequency = float(np.mean(outcomes[mask]))
        gap = observed_frequency - mean_probability
        weighted_gap += (count / len(selected)) * abs(gap)
        absolute_gaps.append(abs(gap))
        bins.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                count=count,
                mean_probability=mean_probability,
                observed_frequency=observed_frequency,
                calibration_gap=float(gap),
            )
        )

    mean_probability = float(np.mean(probabilities))
    observed_frequency = float(np.mean(outcomes))
    return CalibrationSummary(
        version=CALIBRATION_TOURNAMENT_VERSION,
        model_id=model_id,
        channel=channel,
        cohort=cohort,
        observation_count=len(selected),
        independent_date_count=len({item.independent_date for item in selected}),
        brier_score=brier,
        log_loss=log_loss,
        mean_probability=mean_probability,
        observed_frequency=observed_frequency,
        calibration_in_the_large=float(observed_frequency - mean_probability),
        expected_calibration_error=float(weighted_gap),
        mean_absolute_calibration_gap=(
            float(np.mean(np.asarray(absolute_gaps, dtype=float))) if absolute_gaps else 0.0
        ),
        bins=tuple(bins),
    )


def compare_models_paired(
    observations: Sequence[ProbabilityObservation],
    *,
    incumbent_model_id: str,
    challenger_model_id: str,
    channel: str,
    cohort: str = "DEFAULT",
    bootstrap_samples: int = 5000,
    confidence: float = 0.95,
    seed: int = 41,
) -> TournamentComparison:
    if channel not in VALID_CHANNELS:
        raise QuantInputError("channel must be THESIS or PROFIT")
    if bootstrap_samples < 100:
        raise QuantInputError("bootstrap_samples must be at least 100")
    if not 0 < confidence < 1:
        raise QuantInputError("confidence must be between 0 and 1")

    rows = _validated(observations)
    incumbent = {
        item.observation_key: item
        for item in rows
        if item.model_id == incumbent_model_id and item.channel == channel and item.cohort == cohort
    }
    challenger = {
        item.observation_key: item
        for item in rows
        if item.model_id == challenger_model_id and item.channel == channel and item.cohort == cohort
    }
    shared = sorted(set(incumbent) & set(challenger))
    if not shared:
        return TournamentComparison(
            version=CALIBRATION_TOURNAMENT_VERSION,
            incumbent_model_id=incumbent_model_id,
            challenger_model_id=challenger_model_id,
            channel=channel,
            paired_count=0,
            independent_date_count=0,
            incumbent_brier=None,
            challenger_brier=None,
            challenger_minus_incumbent_brier=None,
            delta_ci_low=None,
            delta_ci_high=None,
            challenger_win_rate=None,
            tournament_state="INSUFFICIENT_PAIRED_EVIDENCE",
            detail="No common observation keys are available for a paired comparison.",
        )

    for key in shared:
        left = incumbent[key]
        right = challenger[key]
        if left.outcome != right.outcome:
            raise QuantInputError(f"paired outcome mismatch for observation_key={key}")
        if left.independent_date != right.independent_date:
            raise QuantInputError(f"paired independent_date mismatch for observation_key={key}")

    incumbent_loss = np.asarray(
        [(incumbent[key].probability - incumbent[key].outcome) ** 2 for key in shared],
        dtype=float,
    )
    challenger_loss = np.asarray(
        [(challenger[key].probability - challenger[key].outcome) ** 2 for key in shared],
        dtype=float,
    )
    delta = challenger_loss - incumbent_loss

    ci_low: float | None = None
    ci_high: float | None = None
    if len(shared) >= 2:
        rng = np.random.default_rng(seed)
        indices = rng.integers(0, len(shared), size=(bootstrap_samples, len(shared)))
        boot = delta[indices].mean(axis=1)
        alpha = (1.0 - confidence) / 2.0
        ci_low = float(np.quantile(boot, alpha))
        ci_high = float(np.quantile(boot, 1.0 - alpha))

    date_count = len({incumbent[key].independent_date for key in shared})
    mean_delta = float(np.mean(delta))
    if len(shared) < 20 or date_count < 5:
        state = "ACCUMULATING_PAIRED_EVIDENCE"
        detail = "Paired comparison is descriptive until minimum sample/date sufficiency is met."
    elif ci_high is not None and ci_high < 0:
        state = "CHALLENGER_DESCRIPTIVELY_BETTER"
        detail = "Challenger has lower paired Brier loss with the bootstrap interval below zero; no automatic promotion."
    elif ci_low is not None and ci_low > 0:
        state = "INCUMBENT_DESCRIPTIVELY_BETTER"
        detail = "Incumbent has lower paired Brier loss with the bootstrap interval above zero."
    else:
        state = "NO_CLEAR_PAIRED_WINNER"
        detail = "Paired Brier difference remains uncertain."

    return TournamentComparison(
        version=CALIBRATION_TOURNAMENT_VERSION,
        incumbent_model_id=incumbent_model_id,
        challenger_model_id=challenger_model_id,
        channel=channel,
        paired_count=len(shared),
        independent_date_count=date_count,
        incumbent_brier=float(np.mean(incumbent_loss)),
        challenger_brier=float(np.mean(challenger_loss)),
        challenger_minus_incumbent_brier=mean_delta,
        delta_ci_low=ci_low,
        delta_ci_high=ci_high,
        challenger_win_rate=float(np.mean(challenger_loss < incumbent_loss)),
        tournament_state=state,
        detail=detail,
    )


def promotion_review(
    summary: CalibrationSummary | None,
    *,
    model_id: str,
    channel: str,
    robustness_passed: bool,
    minimum_observations: int = 100,
    minimum_independent_dates: int = 20,
    maximum_brier: float = 0.25,
    maximum_ece: float = 0.10,
) -> PromotionReview:
    if channel not in VALID_CHANNELS:
        raise QuantInputError("channel must be THESIS or PROFIT")
    if minimum_observations < 1 or minimum_independent_dates < 1:
        raise QuantInputError("minimum sample/date requirements must be positive")
    if not 0 <= maximum_brier <= 1 or not 0 <= maximum_ece <= 1:
        raise QuantInputError("calibration thresholds must be in [0,1]")

    reasons: list[str] = []
    if summary is None:
        reasons.append("NO_CALIBRATION_EVIDENCE")
        observation_count = 0
        date_count = 0
        brier = None
        ece = None
    else:
        if summary.model_id != model_id or summary.channel != channel:
            raise QuantInputError("summary identity does not match requested review")
        observation_count = summary.observation_count
        date_count = summary.independent_date_count
        brier = summary.brier_score
        ece = summary.expected_calibration_error
        if observation_count < minimum_observations:
            reasons.append("INSUFFICIENT_OBSERVATIONS")
        if date_count < minimum_independent_dates:
            reasons.append("INSUFFICIENT_INDEPENDENT_DATES")
        if brier > maximum_brier:
            reasons.append("BRIER_ABOVE_REVIEW_THRESHOLD")
        if ece > maximum_ece:
            reasons.append("CALIBRATION_ERROR_ABOVE_REVIEW_THRESHOLD")

    if not robustness_passed:
        reasons.append("ROBUSTNESS_NOT_PASSED")

    review_state = "ELIGIBLE_FOR_PROMOTION_REVIEW" if not reasons else "CONTINUE_SHADOW"
    return PromotionReview(
        version=CALIBRATION_TOURNAMENT_VERSION,
        model_id=model_id,
        channel=channel,
        observation_count=observation_count,
        independent_date_count=date_count,
        brier_score=brier,
        expected_calibration_error=ece,
        robustness_passed=robustness_passed,
        review_state=review_state,
        reasons=tuple(reasons),
        decision_authority="NONE_AUTOMATIC_REVIEW_ONLY",
    )

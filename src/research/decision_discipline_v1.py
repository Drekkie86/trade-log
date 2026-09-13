from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable


DECISION_ENGINE_VERSION = "1.0.0"

DECISION_NO_TRADE = "NO_TRADE"
DECISION_CONTINUE_SHADOW = "CONTINUE_SHADOW"
DECISION_ELIGIBLE_MANUAL_REVIEW = "ELIGIBLE_FOR_MANUAL_REVIEW"

APPROVED_EXECUTION = "MODEL_APPROVED"
DISCRETIONARY_EXECUTION = "DISCRETIONARY_UNAPPROVED"


@dataclass(frozen=True)
class DecisionEvidence:
    structure_defined_risk: bool
    family_activation_state: str
    calibration_state: str
    robustness_state: str
    sample_state: str
    expected_pnl_to_max_loss: float | None
    expected_pnl_to_cvar95: float | None
    probability_of_profit: float | None
    evidence_quality_score: float
    calibration_score: float
    robustness_score: float
    risk_compensation_score: float

    def validate(self) -> None:
        for name, value in (
            ("evidence_quality_score", self.evidence_quality_score),
            ("calibration_score", self.calibration_score),
            ("robustness_score", self.robustness_score),
            ("risk_compensation_score", self.risk_compensation_score),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and in [0, 1]")
        if self.probability_of_profit is not None and (
            not math.isfinite(self.probability_of_profit)
            or not 0.0 <= self.probability_of_profit <= 1.0
        ):
            raise ValueError("probability_of_profit must be in [0, 1]")
        for name, value in (
            ("expected_pnl_to_max_loss", self.expected_pnl_to_max_loss),
            ("expected_pnl_to_cvar95", self.expected_pnl_to_cvar95),
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite when supplied")


@dataclass(frozen=True)
class DecisionResult:
    version: str
    decision: str
    score: float
    hard_block_reasons: tuple[str, ...]
    soft_review_reasons: tuple[str, ...]
    decision_authority: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_manual_review_eligibility(
    evidence: DecisionEvidence,
    *,
    minimum_score: float = 0.70,
    minimum_expected_to_max_loss: float = 0.02,
    minimum_expected_to_cvar95: float = 0.02,
) -> DecisionResult:
    evidence.validate()
    if not math.isfinite(minimum_score) or not 0.0 <= minimum_score <= 1.0:
        raise ValueError("minimum_score must be in [0, 1]")

    hard_blocks: list[str] = []
    soft: list[str] = []

    if not evidence.structure_defined_risk:
        hard_blocks.append("UNBOUNDED_OR_UNDEFINED_DOWNSIDE")
    if evidence.family_activation_state != "ACTIVATED_FOR_MANUAL_REVIEW":
        hard_blocks.append("EDGE_FAMILY_NOT_ACTIVATED")
    if evidence.calibration_state != "CALIBRATED":
        soft.append("CALIBRATION_NOT_READY")
    if evidence.robustness_state != "ROBUST":
        soft.append("ROBUSTNESS_NOT_READY")
    if evidence.sample_state != "SUFFICIENT":
        soft.append("SAMPLE_NOT_SUFFICIENT")

    if evidence.expected_pnl_to_max_loss is None:
        soft.append("MAX_LOSS_COMPENSATION_UNAVAILABLE")
    elif evidence.expected_pnl_to_max_loss < minimum_expected_to_max_loss:
        soft.append("MAX_LOSS_COMPENSATION_TOO_LOW")

    if evidence.expected_pnl_to_cvar95 is None:
        soft.append("TAIL_COMPENSATION_UNAVAILABLE")
    elif evidence.expected_pnl_to_cvar95 < minimum_expected_to_cvar95:
        soft.append("TAIL_COMPENSATION_TOO_LOW")

    score = (
        0.30 * evidence.evidence_quality_score
        + 0.25 * evidence.calibration_score
        + 0.25 * evidence.robustness_score
        + 0.20 * evidence.risk_compensation_score
    )

    if hard_blocks:
        decision = DECISION_NO_TRADE
    elif soft or score < minimum_score:
        if score < minimum_score:
            soft.append("COMPOSITE_SCORE_BELOW_THRESHOLD")
        decision = DECISION_CONTINUE_SHADOW
    else:
        decision = DECISION_ELIGIBLE_MANUAL_REVIEW

    return DecisionResult(
        version=DECISION_ENGINE_VERSION,
        decision=decision,
        score=float(score),
        hard_block_reasons=tuple(hard_blocks),
        soft_review_reasons=tuple(dict.fromkeys(soft)),
        decision_authority="MANUAL_REVIEW_ONLY_NO_EXECUTION_AUTHORITY",
    )


@dataclass(frozen=True)
class ExecutionObservation:
    sequence: int
    execution_class: str
    pnl: float
    model_expected_pnl: float | None = None

    def validate(self) -> None:
        if self.sequence < 1:
            raise ValueError("sequence must be positive")
        if self.execution_class not in {APPROVED_EXECUTION, DISCRETIONARY_EXECUTION}:
            raise ValueError("unsupported execution_class")
        if not math.isfinite(self.pnl):
            raise ValueError("pnl must be finite")
        if self.model_expected_pnl is not None and not math.isfinite(self.model_expected_pnl):
            raise ValueError("model_expected_pnl must be finite when supplied")


@dataclass(frozen=True)
class DisciplineSegment:
    count: int
    total_pnl: float
    average_pnl: float | None
    realized_win_rate: float | None
    average_model_expected_pnl: float | None


@dataclass(frozen=True)
class DisciplineLeakageResult:
    version: str
    total_count: int
    approved: DisciplineSegment
    discretionary: DisciplineSegment
    discretionary_share: float
    discretionary_after_approved_win_count: int
    discretionary_after_approved_win_rate: float | None
    discipline_leakage_state: str
    failure_attribution: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _segment(rows: list[ExecutionObservation]) -> DisciplineSegment:
    if not rows:
        return DisciplineSegment(0, 0.0, None, None, None)
    expected = [row.model_expected_pnl for row in rows if row.model_expected_pnl is not None]
    return DisciplineSegment(
        count=len(rows),
        total_pnl=float(sum(row.pnl for row in rows)),
        average_pnl=float(sum(row.pnl for row in rows) / len(rows)),
        realized_win_rate=float(sum(row.pnl > 0 for row in rows) / len(rows)),
        average_model_expected_pnl=(
            float(sum(expected) / len(expected)) if expected else None
        ),
    )


def analyze_discipline_leakage(
    observations: Iterable[ExecutionObservation],
) -> DisciplineLeakageResult:
    rows = sorted(list(observations), key=lambda item: item.sequence)
    for row in rows:
        row.validate()
    if len({row.sequence for row in rows}) != len(rows):
        raise ValueError("sequence values must be unique")

    approved_rows = [row for row in rows if row.execution_class == APPROVED_EXECUTION]
    discretionary_rows = [row for row in rows if row.execution_class == DISCRETIONARY_EXECUTION]
    approved = _segment(approved_rows)
    discretionary = _segment(discretionary_rows)
    total = len(rows)
    discretionary_share = float(len(discretionary_rows) / total) if total else 0.0

    discretionary_after_win = 0
    eligible_after_win = 0
    previous: ExecutionObservation | None = None
    for row in rows:
        if previous is not None and previous.execution_class == APPROVED_EXECUTION and previous.pnl > 0:
            eligible_after_win += 1
            if row.execution_class == DISCRETIONARY_EXECUTION:
                discretionary_after_win += 1
        previous = row
    after_win_rate = (
        float(discretionary_after_win / eligible_after_win)
        if eligible_after_win
        else None
    )

    if total == 0:
        leakage_state = "NO_EXECUTION_EVIDENCE"
    elif discretionary_share == 0:
        leakage_state = "NO_DISCIPLINE_LEAKAGE_OBSERVED"
    elif discretionary_share <= 0.10 and (after_win_rate is None or after_win_rate <= 0.10):
        leakage_state = "LOW_DISCIPLINE_LEAKAGE"
    elif after_win_rate is not None and after_win_rate >= 0.50:
        leakage_state = "POST_WIN_DISCIPLINE_LEAKAGE"
    else:
        leakage_state = "DISCIPLINE_LEAKAGE_PRESENT"

    if approved.count < 5:
        attribution = "INSUFFICIENT_APPROVED_SAMPLE"
    elif approved.average_pnl is not None and approved.average_pnl <= 0:
        attribution = "STRATEGY_OR_MODEL_FAILURE_CANDIDATE"
    elif discretionary.count and discretionary.average_pnl is not None and discretionary.average_pnl < 0:
        attribution = "OPERATOR_DISCIPLINE_FAILURE_CANDIDATE"
    else:
        attribution = "NO_FAILURE_ATTRIBUTION"

    return DisciplineLeakageResult(
        version=DECISION_ENGINE_VERSION,
        total_count=total,
        approved=approved,
        discretionary=discretionary,
        discretionary_share=discretionary_share,
        discretionary_after_approved_win_count=discretionary_after_win,
        discretionary_after_approved_win_rate=after_win_rate,
        discipline_leakage_state=leakage_state,
        failure_attribution=attribution,
    )

from __future__ import annotations

import pytest

from src.research.decision_discipline_v1 import (
    APPROVED_EXECUTION,
    DECISION_CONTINUE_SHADOW,
    DECISION_ELIGIBLE_MANUAL_REVIEW,
    DECISION_NO_TRADE,
    DISCRETIONARY_EXECUTION,
    DecisionEvidence,
    ExecutionObservation,
    analyze_discipline_leakage,
    evaluate_manual_review_eligibility,
)


def _ready_evidence(**overrides) -> DecisionEvidence:
    payload = dict(
        structure_defined_risk=True,
        family_activation_state="ACTIVATED_FOR_MANUAL_REVIEW",
        calibration_state="CALIBRATED",
        robustness_state="ROBUST",
        sample_state="SUFFICIENT",
        expected_pnl_to_max_loss=0.08,
        expected_pnl_to_cvar95=0.06,
        probability_of_profit=0.58,
        evidence_quality_score=0.85,
        calibration_score=0.82,
        robustness_score=0.80,
        risk_compensation_score=0.78,
    )
    payload.update(overrides)
    return DecisionEvidence(**payload)


def test_manual_review_eligibility_requires_all_governance_gates() -> None:
    result = evaluate_manual_review_eligibility(_ready_evidence())
    assert result.decision == DECISION_ELIGIBLE_MANUAL_REVIEW
    assert result.score >= 0.70
    assert result.decision_authority == "MANUAL_REVIEW_ONLY_NO_EXECUTION_AUTHORITY"


def test_unactivated_family_fails_closed_to_no_trade() -> None:
    result = evaluate_manual_review_eligibility(
        _ready_evidence(family_activation_state="NOT_ACTIVATED")
    )
    assert result.decision == DECISION_NO_TRADE
    assert "EDGE_FAMILY_NOT_ACTIVATED" in result.hard_block_reasons


def test_unbounded_risk_fails_closed_to_no_trade() -> None:
    result = evaluate_manual_review_eligibility(
        _ready_evidence(structure_defined_risk=False)
    )
    assert result.decision == DECISION_NO_TRADE
    assert "UNBOUNDED_OR_UNDEFINED_DOWNSIDE" in result.hard_block_reasons


def test_incomplete_calibration_continues_shadow() -> None:
    result = evaluate_manual_review_eligibility(
        _ready_evidence(calibration_state="ACCUMULATING")
    )
    assert result.decision == DECISION_CONTINUE_SHADOW
    assert "CALIBRATION_NOT_READY" in result.soft_review_reasons


def test_probability_of_profit_alone_does_not_control_decision() -> None:
    result = evaluate_manual_review_eligibility(
        _ready_evidence(probability_of_profit=0.99, expected_pnl_to_max_loss=0.0)
    )
    assert result.decision == DECISION_CONTINUE_SHADOW
    assert "MAX_LOSS_COMPENSATION_TOO_LOW" in result.soft_review_reasons


def test_invalid_scores_fail_closed() -> None:
    with pytest.raises(ValueError):
        evaluate_manual_review_eligibility(
            _ready_evidence(evidence_quality_score=1.01)
        )


def test_discipline_leakage_separates_approved_and_discretionary_pnl() -> None:
    rows = [
        ExecutionObservation(1, APPROVED_EXECUTION, 10.0, 4.0),
        ExecutionObservation(2, APPROVED_EXECUTION, 5.0, 3.0),
        ExecutionObservation(3, DISCRETIONARY_EXECUTION, -20.0, None),
        ExecutionObservation(4, APPROVED_EXECUTION, 3.0, 2.0),
        ExecutionObservation(5, APPROVED_EXECUTION, 4.0, 2.0),
        ExecutionObservation(6, APPROVED_EXECUTION, 2.0, 1.0),
        ExecutionObservation(7, DISCRETIONARY_EXECUTION, -10.0, None),
    ]
    result = analyze_discipline_leakage(rows)
    assert result.approved.count == 5
    assert result.approved.total_pnl == pytest.approx(24.0)
    assert result.discretionary.count == 2
    assert result.discretionary.total_pnl == pytest.approx(-30.0)
    assert result.failure_attribution == "OPERATOR_DISCIPLINE_FAILURE_CANDIDATE"


def test_post_win_leakage_is_detected() -> None:
    rows = [
        ExecutionObservation(1, APPROVED_EXECUTION, 5.0),
        ExecutionObservation(2, DISCRETIONARY_EXECUTION, -2.0),
        ExecutionObservation(3, APPROVED_EXECUTION, 4.0),
        ExecutionObservation(4, DISCRETIONARY_EXECUTION, -3.0),
        ExecutionObservation(5, APPROVED_EXECUTION, 3.0),
        ExecutionObservation(6, DISCRETIONARY_EXECUTION, -1.0),
    ]
    result = analyze_discipline_leakage(rows)
    assert result.discretionary_after_approved_win_count == 3
    assert result.discretionary_after_approved_win_rate == pytest.approx(1.0)
    assert result.discipline_leakage_state == "POST_WIN_DISCIPLINE_LEAKAGE"


def test_strategy_failure_is_not_mislabelled_operator_failure() -> None:
    rows = [
        ExecutionObservation(1, APPROVED_EXECUTION, -2.0),
        ExecutionObservation(2, APPROVED_EXECUTION, -1.0),
        ExecutionObservation(3, APPROVED_EXECUTION, 1.0),
        ExecutionObservation(4, APPROVED_EXECUTION, -3.0),
        ExecutionObservation(5, APPROVED_EXECUTION, 0.5),
    ]
    result = analyze_discipline_leakage(rows)
    assert result.failure_attribution == "STRATEGY_OR_MODEL_FAILURE_CANDIDATE"
    assert result.discretionary.count == 0


def test_empty_execution_history_is_explicit() -> None:
    result = analyze_discipline_leakage([])
    assert result.discipline_leakage_state == "NO_EXECUTION_EVIDENCE"
    assert result.failure_attribution == "INSUFFICIENT_APPROVED_SAMPLE"

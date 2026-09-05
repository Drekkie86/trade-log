from src.decision.desk import (
    build_candidate_review_board,
    build_risk_plan,
)


def _candidate(**overrides):
    row = {
        "candidate_id": 7,
        "underlying": "XSP",
        "exercise_style": "EUROPEAN",
        "admission_decision": "ADMITTED",
        "model_input_complete": True,
        "reserved_risk_eur_minor": 2_000,
        "validated_outcomes": 3,
        "mark_count": 8,
        "abs_iv_residual": 0.08,
    }
    row.update(overrides)
    return row


def test_scientific_governance_is_a_hard_no_trade_gate():
    board = build_candidate_review_board(
        [_candidate()],
        scientific_decision_enabled=False,
        max_trade_risk_eur=25.0,
        stop_loss_fraction=0.5,
    )

    assert board[0]["decision_desk_disposition"] == "NO TRADE"
    assert "SCIENTIFIC_DECISION_GOVERNANCE_DISABLED" in board[0]["decision_blockers"]


def test_cash_settlement_is_a_hard_gate_even_if_other_inputs_pass():
    board = build_candidate_review_board(
        [_candidate(underlying="SPY", exercise_style="AMERICAN")],
        scientific_decision_enabled=True,
        max_trade_risk_eur=25.0,
        stop_loss_fraction=0.5,
    )

    assert board[0]["decision_desk_disposition"] == "NO TRADE"
    assert "BLOCKED_ASSIGNMENT_OR_PHYSICAL_RISK" in board[0]["decision_blockers"]


def test_risk_plan_requires_explicit_configuration():
    plan = build_risk_plan(
        _candidate(),
        max_trade_risk_eur=None,
        stop_loss_fraction=None,
    )

    assert plan.configured is False
    assert plan.passes_risk_budget is False
    assert plan.state == "BLOCKED_RISK_POLICY_NOT_CONFIGURED"


def test_risk_plan_computes_monitoring_trigger_without_calling_it_guaranteed():
    plan = build_risk_plan(
        _candidate(reserved_risk_eur_minor=2_000),
        max_trade_risk_eur=25.0,
        stop_loss_fraction=0.5,
    )

    assert plan.passes_risk_budget is True
    assert plan.reserved_risk_eur == 20.0
    assert plan.planned_loss_trigger_eur == 10.0
    assert "not a guaranteed execution price" in plan.note.lower()


def test_risk_budget_blocks_candidate_above_explicit_limit():
    plan = build_risk_plan(
        _candidate(reserved_risk_eur_minor=4_000),
        max_trade_risk_eur=25.0,
        stop_loss_fraction=0.5,
    )

    assert plan.passes_risk_budget is False
    assert plan.state == "BLOCKED_RISK_BUDGET_EXCEEDED"

from datetime import UTC, datetime

from src.decision.desk import build_candidate_review_board, build_risk_plan


def _candidate(**overrides):
    row = {
        "candidate_id": 7,
        "underlying": "XSP",
        "reference_contract_id": 44,
        "target_shares_per_contract": 100,
        "exercise_style": "EUROPEAN",
        "scanner_family_id": "LOCAL_IV_RESIDUAL_V1",
        "admission_decision": "ADMITTED",
        "model_input_complete": True,
        "reserved_risk_eur_minor": 2_000,
        "validated_outcomes": 3,
        "mark_count": 8,
        "abs_iv_residual": 0.08,
        "target_bid": 1.00,
        "target_ask": 1.02,
        "target_quote_at": "2026-09-05T20:00:00Z",
        "collection_status": "SUCCESS",
        "retry_count": 0,
        "expiration": "2026-09-12",
        "surfaced_at": "2026-09-05T19:59:00Z",
    }
    row.update(overrides)
    return row


def _models(enabled=False):
    return [
        {"model_key": "LOCAL_SURFACE_QUADRATIC_V2", "decision_enabled": enabled, "admission_enabled": False},
        {"model_key": "NEAREST_BRACKET_LINEAR_V1", "decision_enabled": enabled, "admission_enabled": False},
    ]


def _hypotheses(enabled=False):
    return [
        {"hypothesis_key": key, "decision_enabled": enabled}
        for key in (
            "H1_DTE_14_20_TRANSFER_STABILITY",
            "H2_MODEL_FORM_GENERALIZATION",
            "H3_MARKET_QUALITY_CONDITIONING",
            "H4_PERSISTENT_EPISODE_RECURRENCE",
        )
    ]


def test_scientific_governance_is_candidate_specific_and_false_legacy_flag_is_conservative():
    board = build_candidate_review_board(
        [_candidate()], models=_models(False), hypotheses=_hypotheses(False),
        scientific_decision_enabled=False, max_trade_risk_eur=25.0, stop_loss_fraction=0.5,
        now=datetime(2026, 9, 5, 20, 0, 20, tzinfo=UTC),
    )
    assert board[0]["decision_desk_disposition"] in {"CONTINUE SHADOW", "NO TRADE"}
    assert "SCIENTIFIC_DECISION_GOVERNANCE_DISABLED" in board[0]["decision_blockers"]
    assert board[0]["candidate_governance_state"] == "DISABLED"


def test_cash_settlement_is_hard_gate_even_if_other_inputs_pass():
    board = build_candidate_review_board(
        [_candidate(underlying="SPY", exercise_style="AMERICAN")], models=_models(True), hypotheses=_hypotheses(True),
        max_trade_risk_eur=25.0, stop_loss_fraction=0.5,
        now=datetime(2026, 9, 5, 20, 0, 20, tzinfo=UTC),
    )
    assert board[0]["decision_desk_disposition"] == "NO TRADE"
    assert "BLOCKED_ASSIGNMENT_OR_PHYSICAL_RISK" in board[0]["decision_blockers"]


def test_risk_plan_requires_explicit_configuration():
    plan = build_risk_plan(_candidate(), max_trade_risk_eur=None, stop_loss_fraction=None)
    assert plan.configured is False
    assert plan.passes_risk_budget is False
    assert plan.state == "BLOCKED_RISK_POLICY_NOT_CONFIGURED"


def test_risk_plan_computes_monitoring_trigger_without_calling_it_guaranteed():
    plan = build_risk_plan(_candidate(reserved_risk_eur_minor=2_000), max_trade_risk_eur=25.0, stop_loss_fraction=0.5)
    assert plan.passes_risk_budget is True
    assert plan.reserved_risk_eur == 20.0
    assert plan.planned_loss_trigger_eur == 10.0
    assert "not a guaranteed execution price" in plan.note.lower()


def test_risk_budget_blocks_candidate_above_explicit_limit():
    plan = build_risk_plan(_candidate(reserved_risk_eur_minor=4_000), max_trade_risk_eur=25.0, stop_loss_fraction=0.5)
    assert plan.passes_risk_budget is False
    assert plan.state == "BLOCKED_RISK_BUDGET_EXCEEDED"


def test_manual_review_cannot_be_reached_while_event_ev_and_exact_tte_are_missing():
    board = build_candidate_review_board(
        [_candidate()], models=_models(True), hypotheses=_hypotheses(True),
        max_trade_risk_eur=25.0, stop_loss_fraction=0.5,
        now=datetime(2026, 9, 5, 20, 0, 20, tzinfo=UTC),
    )
    assert board[0]["decision_desk_disposition"] == "CONTINUE SHADOW"
    assert "EVENT_RISK_CONTEXT_NOT_INTEGRATED" in board[0]["decision_blockers"]
    assert "CALIBRATED_NET_EV_NOT_AVAILABLE" in board[0]["decision_blockers"]
    assert "EXACT_EXPIRATION_TIMESTAMP_UNAVAILABLE" in board[0]["decision_blockers"]

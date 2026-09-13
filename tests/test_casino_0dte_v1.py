from __future__ import annotations

import pytest

from src.research.casino_0dte_v1 import (
    CASINO_NO_TRADE,
    CASINO_SHADOW_CANDIDATE,
    CasinoRiskPolicy,
    ScenarioOutcome,
    ZeroDteDiagnostics,
    evaluate_0dte_diagnostics,
    evaluate_casino_experiment,
)


def test_0dte_variance_gap_is_measured_over_remaining_time() -> None:
    result = evaluate_0dte_diagnostics(
        ZeroDteDiagnostics(
            implied_volatility_annualized=0.30,
            forecast_realized_volatility_annualized=0.20,
            remaining_year_fraction=1 / (252 * 2),
            jump_variance_remaining=0.00001,
            call_iv=0.28,
            put_iv=0.32,
            gamma_exposure_cash=120.0,
            theta_decay_cash_per_day=-40.0,
            bid_ask_spread_fraction=0.04,
        )
    )
    assert result.implied_remaining_variance > 0
    assert result.forecast_remaining_variance > 0
    assert result.skew_put_minus_call == pytest.approx(0.04)
    assert result.gamma_theta_abs_ratio == pytest.approx(3.0)
    assert result.liquidity_state == "LIQUIDITY_ACCEPTABLE_FOR_RESEARCH"
    assert result.dealer_positioning_state == "NOT_MEASURED_DO_NOT_INFER"
    assert result.evidence_label == "CASINO_RESEARCH_DIAGNOSTIC_NOT_EDGE_PROOF"


def test_dealer_positioning_cannot_be_fabricated_without_source() -> None:
    with pytest.raises(ValueError):
        evaluate_0dte_diagnostics(
            ZeroDteDiagnostics(
                implied_volatility_annualized=0.30,
                forecast_realized_volatility_annualized=0.20,
                remaining_year_fraction=1 / 252,
                dealer_positioning_value=10.0,
            )
        )


def test_positive_ev_defined_risk_liquid_experiment_can_enter_shadow_only() -> None:
    result = evaluate_casino_experiment(
        [
            ScenarioOutcome(0.60, 18.0),
            ScenarioOutcome(0.30, -10.0),
            ScenarioOutcome(0.10, -20.0),
        ],
        risk_policy=CasinoRiskPolicy(bankroll=500.0, casino_cap=500.0, max_loss_fraction=0.05),
        defined_risk=True,
        max_loss=20.0,
        transaction_costs=1.0,
        slippage=1.0,
        liquidity_state="LIQUIDITY_ACCEPTABLE_FOR_RESEARCH",
    )
    assert result.state == CASINO_SHADOW_CANDIDATE
    assert result.risk_budget == pytest.approx(25.0)
    assert result.max_loss == pytest.approx(22.0)
    assert result.expected_pnl_net > 0
    assert result.decision_authority == "CASINO_RESEARCH_SHADOW_ONLY_NO_EXECUTION"


def test_friction_is_included_in_hard_loss_budget() -> None:
    result = evaluate_casino_experiment(
        [ScenarioOutcome(0.9, 10.0), ScenarioOutcome(0.1, -24.0)],
        risk_policy=CasinoRiskPolicy(bankroll=500.0, casino_cap=500.0, max_loss_fraction=0.05),
        defined_risk=True,
        max_loss=24.0,
        transaction_costs=1.0,
        slippage=1.0,
        liquidity_state="LIQUIDITY_ACCEPTABLE_FOR_RESEARCH",
    )
    assert result.max_loss == pytest.approx(26.0)
    assert result.state == CASINO_NO_TRADE
    assert "EXCEEDS_CASINO_EXPERIMENT_LOSS_BUDGET" in result.reasons


def test_experiment_over_hard_loss_budget_is_no_trade() -> None:
    result = evaluate_casino_experiment(
        [ScenarioOutcome(0.8, 20.0), ScenarioOutcome(0.2, -100.0)],
        risk_policy=CasinoRiskPolicy(bankroll=500.0, casino_cap=500.0, max_loss_fraction=0.05),
        defined_risk=True,
        max_loss=100.0,
        transaction_costs=0.0,
        slippage=0.0,
        liquidity_state="LIQUIDITY_ACCEPTABLE_FOR_RESEARCH",
    )
    assert result.state == CASINO_NO_TRADE
    assert "EXCEEDS_CASINO_EXPERIMENT_LOSS_BUDGET" in result.reasons


def test_unbounded_experiment_is_no_trade_even_with_attractive_scenarios() -> None:
    result = evaluate_casino_experiment(
        [ScenarioOutcome(0.95, 10.0), ScenarioOutcome(0.05, -5.0)],
        risk_policy=CasinoRiskPolicy(bankroll=500.0, casino_cap=500.0, max_loss_fraction=0.10),
        defined_risk=False,
        max_loss=None,
        transaction_costs=0.0,
        slippage=0.0,
        liquidity_state="LIQUIDITY_ACCEPTABLE_FOR_RESEARCH",
    )
    assert result.state == CASINO_NO_TRADE
    assert "UNBOUNDED_OR_UNKNOWN_MAX_LOSS" in result.reasons


def test_negative_ev_after_costs_is_no_trade() -> None:
    result = evaluate_casino_experiment(
        [ScenarioOutcome(0.5, 3.0), ScenarioOutcome(0.5, -1.0)],
        risk_policy=CasinoRiskPolicy(bankroll=500.0, casino_cap=500.0, max_loss_fraction=0.05),
        defined_risk=True,
        max_loss=5.0,
        transaction_costs=1.5,
        slippage=1.0,
        liquidity_state="LIQUIDITY_ACCEPTABLE_FOR_RESEARCH",
    )
    assert result.expected_pnl_net < 0
    assert result.state == CASINO_NO_TRADE
    assert "NON_POSITIVE_SCENARIO_EV_AFTER_COSTS" in result.reasons


def test_spectacular_win_probability_does_not_override_bad_liquidity() -> None:
    result = evaluate_casino_experiment(
        [ScenarioOutcome(0.99, 5.0), ScenarioOutcome(0.01, -5.0)],
        risk_policy=CasinoRiskPolicy(bankroll=500.0, casino_cap=500.0, max_loss_fraction=0.05),
        defined_risk=True,
        max_loss=5.0,
        transaction_costs=0.0,
        slippage=0.0,
        liquidity_state="LIQUIDITY_REJECT",
    )
    assert result.probability_of_profit_net == pytest.approx(0.99)
    assert result.state == CASINO_NO_TRADE
    assert "LIQUIDITY_REJECT" in result.reasons

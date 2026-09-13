from __future__ import annotations

import math

import numpy as np
import pytest

from src.quant.risk import OptionLeg
from src.quant.risk_selection import (
    DistributionAssumptions,
    RiskBudget,
    evaluate_structure_distribution,
    payoff_bounds,
    simulate_terminal_prices,
)
from src.quant.types import QuantInputError


def _bull_call_spread() -> list[OptionLeg]:
    return [
        OptionLeg("CALL", 100.0, 1, 6.0),
        OptionLeg("CALL", 110.0, -1, 2.0),
    ]


def test_payoff_bounds_for_debit_call_spread_use_standard_contract_multiplier() -> None:
    entry, max_loss, max_profit, defined = payoff_bounds(_bull_call_spread(), total_costs=0.50)
    assert entry == pytest.approx(400.0)
    assert defined is True
    assert max_loss == pytest.approx(400.50)
    assert max_profit == pytest.approx(599.50)


def test_payoff_bounds_can_use_explicit_unit_multiplier_for_research() -> None:
    entry, max_loss, max_profit, defined = payoff_bounds(
        _bull_call_spread(),
        total_costs=0.50,
        contract_multiplier=1,
    )
    assert entry == pytest.approx(4.0)
    assert defined is True
    assert max_loss == pytest.approx(4.50)
    assert max_profit == pytest.approx(5.50)


def test_naked_short_call_is_rejected_as_unbounded_loss() -> None:
    legs = [OptionLeg("CALL", 100.0, -1, 3.0)]
    entry, max_loss, max_profit, defined = payoff_bounds(legs)
    assert entry == pytest.approx(-300.0)
    assert defined is False
    assert max_loss is None
    assert max_profit == pytest.approx(300.0)

    result = evaluate_structure_distribution(
        legs,
        spot=100.0,
        time_to_expiry=30 / 365,
        assumptions=DistributionAssumptions(annual_drift=0.0, annual_volatility=0.20),
        risk_budget=RiskBudget(bankroll=500.0, max_loss_fraction=0.05),
        simulation_paths=20_000,
        seed=1,
    )
    assert result.budget_state == "REJECT_UNBOUNDED_LOSS"
    assert result.max_contracts_at_budget is None


def test_distribution_evaluation_reports_cash_contract_risk_costs_tail_and_budget() -> None:
    result = evaluate_structure_distribution(
        _bull_call_spread(),
        spot=100.0,
        time_to_expiry=30 / 365,
        assumptions=DistributionAssumptions(annual_drift=0.05, annual_volatility=0.20),
        transaction_costs=0.25,
        slippage=0.25,
        risk_budget=RiskBudget(bankroll=500.0, max_loss_fraction=1.0),
        simulation_paths=30_000,
        seed=17,
    )
    assert result.structure_defined_risk is True
    assert result.contract_multiplier == 100
    assert result.max_loss == pytest.approx(400.50)
    assert result.max_profit == pytest.approx(599.50)
    assert result.total_costs == pytest.approx(0.50)
    assert 0.0 <= result.probability_of_profit <= 1.0
    assert 0.0 <= result.probability_of_loss <= 1.0
    assert result.loss_cvar_95 >= result.loss_var_95
    assert result.max_loss_bankroll_fraction == pytest.approx(400.5 / 500.0)
    assert result.risk_budget_amount == pytest.approx(500.0)
    assert result.max_contracts_at_budget == 1
    assert result.budget_state == "WITHIN_BOUNDED_RISK_BUDGET"
    assert result.decision_authority == "NONE_RESEARCH_ONLY"
    assert result.pnl_p05 <= result.pnl_p25 <= result.pnl_p50 <= result.pnl_p75 <= result.pnl_p95


def test_small_bankroll_correctly_rejects_standard_contract_that_exceeds_budget() -> None:
    result = evaluate_structure_distribution(
        _bull_call_spread(),
        spot=100.0,
        time_to_expiry=30 / 365,
        assumptions=DistributionAssumptions(annual_drift=0.0, annual_volatility=0.20),
        risk_budget=RiskBudget(bankroll=500.0, max_loss_fraction=0.02),
        simulation_paths=20_000,
        seed=4,
    )
    assert result.structure_defined_risk is True
    assert result.max_loss == pytest.approx(400.0)
    assert result.risk_budget_amount == pytest.approx(10.0)
    assert result.budget_state == "EXCEEDS_SINGLE_STRUCTURE_RISK_BUDGET"
    assert result.max_contracts_at_budget == 0


def test_terminal_simulation_is_seed_deterministic_and_jump_capable() -> None:
    assumptions = DistributionAssumptions(
        annual_drift=0.03,
        annual_volatility=0.18,
        jump_intensity=2.0,
        jump_mean=-0.04,
        jump_volatility=0.10,
    )
    first = simulate_terminal_prices(
        spot=100.0,
        time_to_expiry=0.5,
        assumptions=assumptions,
        simulation_paths=10_000,
        seed=99,
    )
    second = simulate_terminal_prices(
        spot=100.0,
        time_to_expiry=0.5,
        assumptions=assumptions,
        simulation_paths=10_000,
        seed=99,
    )
    assert np.array_equal(first, second)
    assert np.all(np.isfinite(first))
    assert np.all(first > 0)


def test_invalid_risk_inputs_fail_closed() -> None:
    with pytest.raises(QuantInputError):
        RiskBudget(bankroll=500.0, max_loss_fraction=0.0).validate()
    with pytest.raises(QuantInputError):
        DistributionAssumptions(annual_drift=0.0, annual_volatility=-0.1).validate()
    with pytest.raises(QuantInputError):
        simulate_terminal_prices(
            spot=100.0,
            time_to_expiry=0.1,
            assumptions=DistributionAssumptions(0.0, 0.2),
            simulation_paths=9999,
            seed=1,
        )
    with pytest.raises(QuantInputError):
        payoff_bounds(_bull_call_spread(), contract_multiplier=0)
    with pytest.raises(QuantInputError):
        payoff_bounds(_bull_call_spread(), contract_multiplier=1.5)  # type: ignore[arg-type]


def test_expected_pnl_ratio_is_not_fabricated_when_max_loss_is_zero() -> None:
    legs = [OptionLeg("CALL", 100.0, 1, 0.0)]
    result = evaluate_structure_distribution(
        legs,
        spot=100.0,
        time_to_expiry=0.0,
        assumptions=DistributionAssumptions(0.0, 0.0),
        simulation_paths=10_000,
        seed=2,
    )
    assert result.max_loss == pytest.approx(0.0)
    assert result.expected_pnl_to_max_loss is None
    assert math.isfinite(result.expected_pnl)

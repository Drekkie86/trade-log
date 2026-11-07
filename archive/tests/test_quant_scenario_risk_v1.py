from __future__ import annotations

import pytest

from src.quant.risk import OptionLeg, evaluate_lognormal
from src.quant.scenario import vanilla_grid
from src.quant.types import VanillaOption


def test_scenario_grid_cartesian_size():
    option = VanillaOption(100, 100, 0.5, 0.02, 0.25, "CALL")
    points = vanilla_grid(
        option,
        spots=[90, 100, 110],
        volatilities=[0.2, 0.25],
        times_to_expiry=[0.25, 0.5],
    )
    assert len(points) == 12


def test_reference_scenario_has_zero_pnl():
    option = VanillaOption(100, 100, 0.5, 0.02, 0.25, "CALL")
    point = vanilla_grid(
        option,
        spots=[100],
        volatilities=[0.25],
        times_to_expiry=[0.5],
    )[0]
    assert point.pnl_vs_reference == pytest.approx(0.0)


def test_long_call_has_defined_max_loss_and_unbounded_profit():
    result = evaluate_lognormal(
        [OptionLeg("CALL", 100, 1, 5.0)],
        spot=100,
        time_to_expiry=0.5,
        rate=0.02,
        volatility=0.25,
        simulation_paths=20_000,
    )
    assert result.defined_risk is True
    assert result.max_loss == pytest.approx(5.0)
    assert result.max_profit is None


def test_naked_short_call_is_not_defined_risk():
    result = evaluate_lognormal(
        [OptionLeg("CALL", 100, -1, 5.0)],
        spot=100,
        time_to_expiry=0.5,
        rate=0.02,
        volatility=0.25,
        simulation_paths=20_000,
    )
    assert result.defined_risk is False
    assert result.max_loss is None


def test_vertical_call_spread_has_finite_max_loss_and_profit():
    result = evaluate_lognormal(
        [
            OptionLeg("CALL", 100, 1, 6.0),
            OptionLeg("CALL", 110, -1, 2.0),
        ],
        spot=100,
        time_to_expiry=0.5,
        rate=0.02,
        volatility=0.25,
        transaction_costs=0.5,
        slippage=0.25,
        simulation_paths=30_000,
    )
    assert result.defined_risk is True
    assert result.max_loss == pytest.approx(4.75)
    assert result.max_profit == pytest.approx(5.25)


def test_costs_reduce_expected_value_exactly():
    result = evaluate_lognormal(
        [OptionLeg("PUT", 90, 1, 2.0)],
        spot=100,
        time_to_expiry=0.5,
        rate=0.02,
        volatility=0.25,
        transaction_costs=0.4,
        slippage=0.3,
        simulation_paths=20_000,
    )
    assert result.pricing_measure_ev_after_costs == pytest.approx(
        result.pricing_measure_ev_before_costs - 0.7
    )


def test_probability_and_tail_metrics_are_populated():
    result = evaluate_lognormal(
        [OptionLeg("CALL", 100, 1, 5.0)],
        spot=100,
        time_to_expiry=0.25,
        rate=0.01,
        volatility=0.3,
        simulation_paths=20_000,
    )
    assert 0 <= result.risk_neutral_probability_of_profit <= 1
    assert result.cvar_95 >= result.var_95

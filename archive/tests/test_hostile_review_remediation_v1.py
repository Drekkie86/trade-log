from __future__ import annotations

import warnings

import numpy as np
import pytest
from scipy.integrate import IntegrationWarning

import src.quant.heston as heston_module
from src.quant.heston import HestonNumericalError, HestonParameters, price as heston_price
from src.quant.risk import OptionLeg
from src.quant.risk_selection import (
    DistributionAssumptions,
    RiskBudget,
    evaluate_portfolio_scenarios,
    evaluate_structure_distribution,
)
from src.quant.sabr import (
    SABRParameters,
    checked_smile as checked_sabr_smile,
    sampled_static_arbitrage as sampled_sabr_static_arbitrage,
)
from src.quant.svi import SVIParameters, sampled_static_arbitrage as sampled_svi_static_arbitrage
from src.quant.tails import diagnose
from src.quant.types import QuantInputError, VanillaOption


def test_heston_integration_warning_fails_closed(monkeypatch) -> None:
    original_quad = heston_module.quad

    def warning_quad(*args, **kwargs):
        warnings.warn("synthetic integration instability", IntegrationWarning)
        return original_quad(*args, **kwargs)

    monkeypatch.setattr(heston_module, "quad", warning_quad)
    option = VanillaOption(100, 100, 1.0, 0.02, 0.2, "CALL", 0.01)
    params = HestonParameters(1.5, 0.04, 0.6, -0.7, 0.04)
    with pytest.raises(HestonNumericalError, match="integration warning"):
        heston_price(option, params)


def test_tail_diagnostics_expose_empirical_resolution_and_tail_support() -> None:
    result = diagnose(np.linspace(-0.02, 0.02, 20))
    assert result.empirical_probability_resolution == pytest.approx(0.05)
    assert result.var_95_tail_observations >= 1
    assert result.var_99_tail_observations >= 1
    assert "Do not infer precision" in result.sampling_note


def test_svi_diagnostics_detect_density_condition_butterfly_violation() -> None:
    params = SVIParameters(
        0.0704054331623131,
        2.3145079728684426,
        -0.07369979283911055,
        -0.10862594905146372,
        0.32914411816239114,
    )
    result = sampled_svi_static_arbitrage(params)
    assert result["negative_total_variance"] is False
    assert result["sampled_min_density_condition"] < 0
    assert result["sampled_butterfly_arbitrage"] is True


def test_sabr_diagnostics_reject_demonstrated_hagan_butterfly_breakdown() -> None:
    params = SABRParameters(alpha=0.5, beta=0.2, rho=-0.7, nu=2.5)
    result = sampled_sabr_static_arbitrage(
        100.0,
        2.0,
        params,
        strike_min=50.0,
        strike_max=150.0,
        points=101,
    )
    assert result["sampled_static_arbitrage"] is True
    assert result["call_convexity_violations"] > 0
    with pytest.raises(QuantInputError, match="static-arbitrage"):
        checked_sabr_smile(
            100.0,
            np.linspace(50.0, 150.0, 101),
            2.0,
            params,
        )


def test_portfolio_ruin_uses_joint_scenarios_and_single_trade_metric_is_named() -> None:
    first = np.full(10_000, -300.0)
    second = np.full(10_000, -300.0)
    portfolio = evaluate_portfolio_scenarios([first, second], bankroll=500.0)
    assert portfolio.structure_count == 2
    assert portfolio.probability_of_bankroll_ruin == pytest.approx(1.0)
    assert portfolio.worst_scenario_pnl == pytest.approx(-600.0)

    structure = evaluate_structure_distribution(
        [OptionLeg("CALL", 100.0, 1, 6.0), OptionLeg("CALL", 110.0, -1, 2.0)],
        spot=100.0,
        time_to_expiry=30 / 365,
        assumptions=DistributionAssumptions(annual_drift=0.0, annual_volatility=0.20),
        risk_budget=RiskBudget(bankroll=500.0, max_loss_fraction=1.0),
        simulation_paths=10_000,
        seed=11,
    )
    assert (
        structure.single_structure_bankroll_ruin_probability
        == structure.probability_of_bankroll_ruin
    )

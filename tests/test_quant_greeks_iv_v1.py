from __future__ import annotations

import pytest

from src.quant.black_scholes import no_arbitrage_bounds, price
from src.quant.greeks import analytic, numerical
from src.quant.implied_vol import solve
from src.quant.types import VanillaOption


def test_iv_round_trip_call():
    option = VanillaOption(100, 103, 0.7, 0.025, 0.31, "CALL", 0.01)
    result = solve(price(option), option)
    assert result.state == "SOLVED"
    assert result.volatility == pytest.approx(0.31, abs=1e-10)
    assert abs(result.pricing_error) < 1e-9


def test_iv_round_trip_put():
    option = VanillaOption(80, 90, 0.25, 0.015, 0.47, "PUT", 0.0)
    result = solve(price(option), option)
    assert result.volatility == pytest.approx(0.47, abs=1e-10)


def test_iv_rejects_price_below_no_arbitrage_bound():
    option = VanillaOption(150, 100, 1, 0.02, 0.2, "CALL", 0.0)
    lower, _ = no_arbitrage_bounds(option)
    result = solve(lower - 1.0, option)
    assert result.state == "NO_ARBITRAGE_VIOLATION"
    assert result.volatility is None


def test_iv_rejects_price_above_upper_bound():
    option = VanillaOption(100, 100, 1, 0.02, 0.2, "CALL", 0.0)
    _, upper = no_arbitrage_bounds(option)
    result = solve(upper + 1.0, option)
    assert result.state == "NO_ARBITRAGE_VIOLATION"


def test_iv_lower_bound_maps_to_zero_vol():
    option = VanillaOption(100, 150, 1, 0.0, 0.2, "CALL")
    lower, _ = no_arbitrage_bounds(option)
    result = solve(lower, option)
    assert result.state == "AT_LOWER_BOUND"
    assert result.volatility == 0.0


def test_analytic_greeks_match_finite_differences():
    option = VanillaOption(100, 105, 0.8, 0.03, 0.27, "CALL", 0.012)
    a = analytic(option)
    n = numerical(option)
    assert a.delta == pytest.approx(n["delta"], abs=2e-6)
    assert a.gamma == pytest.approx(n["gamma"], abs=2e-6)
    assert a.vega == pytest.approx(n["vega"], abs=2e-5)
    assert a.theta == pytest.approx(n["theta"], abs=2e-4)
    assert a.rho == pytest.approx(n["rho"], abs=2e-4)


def test_put_delta_is_negative_and_gamma_vega_positive():
    g = analytic(VanillaOption(100, 100, 0.5, 0.03, 0.25, "PUT"))
    assert g.delta < 0
    assert g.gamma > 0
    assert g.vega > 0


def test_higher_order_greeks_are_finite():
    g = analytic(VanillaOption(100, 95, 0.4, 0.02, 0.4, "CALL"))
    for value in (g.vanna, g.vomma, g.charm):
        assert value == pytest.approx(value)
        assert abs(value) < 1e6

"""Charm is minus the time-to-expiry derivative of delta.

Black-Scholes with continuous dividends: call-put delta parity is exp(-qT),
so call-put charm parity is q*exp(-qT). Independent central differences
protect against a sign error for both calls and puts when q is nonzero.
"""
from dataclasses import replace
import math

import pytest

from src.quant.greeks import analytic
from src.quant.types import VanillaOption


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("dividend_yield", [0.0, 0.01, 0.03, 0.08])
@pytest.mark.parametrize("t_years", [3.0 / 365, 0.25, 1.0])
def test_charm_matches_negative_time_to_expiry_delta_derivative(
    right, dividend_yield, t_years
):
    option = VanillaOption(
        spot=100.0, strike=105.0, time_to_expiry=t_years,
        rate=0.045, volatility=0.27,
        right=right, dividend_yield=dividend_yield,
    )
    h = min(1e-5, t_years / 100.0)
    plus = analytic(replace(option, time_to_expiry=t_years + h)).delta
    minus = analytic(replace(option, time_to_expiry=t_years - h)).delta
    expected = -(plus - minus) / (2.0 * h)
    assert analytic(option).charm == pytest.approx(expected, rel=2e-5, abs=1e-6)


@pytest.mark.parametrize("dividend_yield", [0.0, 0.01, 0.03, 0.08])
def test_charm_call_put_parity_with_dividend_yield(dividend_yield):
    base = VanillaOption(
        spot=100.0, strike=105.0, time_to_expiry=0.25,
        rate=0.045, volatility=0.27,
        dividend_yield=dividend_yield,
    )
    call = analytic(replace(base, right="CALL")).charm
    put = analytic(replace(base, right="PUT")).charm
    assert call - put == pytest.approx(
        dividend_yield * math.exp(-dividend_yield * base.time_to_expiry),
        abs=1e-12,
    )

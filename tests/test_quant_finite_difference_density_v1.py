from __future__ import annotations

import numpy as np
import pytest

from src.quant.black_scholes import price
from src.quant.density import approximate_mass, breeden_litzenberger
from src.quant.finite_difference import crank_nicolson_price
from src.quant.types import VanillaOption
from src.quant.variance_comparison import implied_vs_realized


def test_crank_nicolson_call_converges_to_bsm():
    option = VanillaOption(100, 100, 0.5, 0.03, 0.25, "CALL", 0.01)
    fd = crank_nicolson_price(option, spot_steps=300, time_steps=300)
    assert fd == pytest.approx(price(option), abs=0.03)


def test_crank_nicolson_put_converges_to_bsm():
    option = VanillaOption(100, 110, 0.75, 0.02, 0.30, "PUT", 0.0)
    fd = crank_nicolson_price(option, spot_steps=320, time_steps=320)
    assert fd == pytest.approx(price(option), abs=0.04)


def test_breeden_litzenberger_density_is_nonnegative_for_bsm_slice():
    strikes = np.linspace(55, 145, 91)
    calls = [price(VanillaOption(100, float(k), 0.5, 0.02, 0.25, "CALL")) for k in strikes]
    points = breeden_litzenberger(strikes, calls, time_to_expiry=0.5, rate=0.02)
    assert all(p.state == "VALID" for p in points)
    assert all(p.density >= 0 for p in points)
    mass = approximate_mass(points)
    assert 0.90 < mass < 1.02


def test_density_flags_convexity_break_as_negative_density():
    strikes = [80, 90, 100, 110, 120, 130]
    calls = [25, 20, 19, 5, 3, 2]
    points = breeden_litzenberger(strikes, calls, time_to_expiry=0.5, rate=0.0)
    assert any(p.state == "NEGATIVE_DENSITY" for p in points)


def test_implied_vs_realized_variance_math():
    result = implied_vs_realized(0.30, 0.20)
    assert result["variance_spread"] == pytest.approx(0.05)
    assert result["variance_ratio"] == pytest.approx(2.25)

from __future__ import annotations

import pytest

from src.quant.black_scholes import price as bsm_price
from src.quant.monte_carlo import price as mc_price
from src.quant.trees import crr_price
from src.quant.types import VanillaOption
from src.quant.validation import validate_vanilla_kernel


def test_european_tree_converges_to_bsm():
    option = VanillaOption(100, 100, 1, 0.05, 0.2, "CALL")
    assert crr_price(option, steps=1000) == pytest.approx(bsm_price(option), abs=0.003)


def test_american_put_is_not_below_european_put():
    option = VanillaOption(100, 110, 1, 0.05, 0.25, "PUT")
    european = crr_price(option, steps=600, american=False)
    american = crr_price(option, steps=600, american=True)
    assert american >= european


def test_non_dividend_american_call_near_european():
    option = VanillaOption(100, 100, 1, 0.03, 0.2, "CALL", 0.0)
    european = crr_price(option, steps=600, american=False)
    american = crr_price(option, steps=600, american=True)
    assert american == pytest.approx(european, abs=1e-10)


def test_seeded_mc_is_deterministic():
    option = VanillaOption(100, 110, 0.5, 0.02, 0.3, "CALL")
    a = mc_price(option, paths=20_000, seed=99)
    b = mc_price(option, paths=20_000, seed=99)
    assert a == b


def test_mc_confidence_interval_covers_bsm_with_variance_reduction():
    option = VanillaOption(100, 100, 1, 0.03, 0.25, "CALL")
    mc = mc_price(option, paths=150_000, seed=123)
    bsm = bsm_price(option)
    assert mc.confidence_low_95 - 0.02 <= bsm <= mc.confidence_high_95 + 0.02


def test_control_variate_reduces_standard_error_for_call():
    option = VanillaOption(100, 100, 1, 0.03, 0.25, "CALL")
    raw = mc_price(option, paths=50_000, seed=777, control_variate=False)
    cv = mc_price(option, paths=50_000, seed=777, control_variate=True)
    assert cv.standard_error < raw.standard_error


def test_validation_report_passes_reference_case():
    option = VanillaOption(100, 100, 1, 0.03, 0.2, "CALL", 0.01)
    report = validate_vanilla_kernel(option, tree_steps=1000, mc_paths=100_000)
    assert report.passed is True
    assert abs(report.put_call_parity_residual) < 1e-10
